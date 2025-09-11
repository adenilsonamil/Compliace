import os
import logging
import secrets
from datetime import datetime
from flask import Flask, request
from twilio.rest import Client
from supabase import create_client, Client as SupabaseClient

# ======================================================
# Configuração de logs
# ======================================================
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)

# ======================================================
# Variáveis obrigatórias de ambiente
# ======================================================
REQUIRED_VARS = [
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_PHONE_NUMBER",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY"
]

for var in REQUIRED_VARS:
    if not os.getenv(var):
        raise ValueError(f"❌ Variável de ambiente obrigatória não definida: {var}")

# ======================================================
# Twilio
# ======================================================
_twilio_number = os.getenv("TWILIO_PHONE_NUMBER")
if not _twilio_number.startswith("whatsapp:"):
    TWILIO_WHATSAPP = f"whatsapp:{_twilio_number}"
else:
    TWILIO_WHATSAPP = _twilio_number

client_twilio = Client(
    os.getenv("TWILIO_ACCOUNT_SID"),
    os.getenv("TWILIO_AUTH_TOKEN")
)

# ======================================================
# Supabase
# ======================================================
supabase: SupabaseClient = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_ROLE_KEY")
)

# ======================================================
# Sessões de usuários em memória
# ======================================================
user_sessions = {}

# ======================================================
# Funções auxiliares
# ======================================================
def enviar_whatsapp(destino, mensagem):
    """Envia mensagem formatada para WhatsApp"""
    try:
        numero_formatado = destino if destino.startswith("whatsapp:") else f"whatsapp:{destino}"
        logging.debug(f"Enviando para {numero_formatado}: {mensagem}")
        client_twilio.messages.create(
            from_=TWILIO_WHATSAPP,
            body=mensagem,
            to=numero_formatado
        )
    except Exception as e:
        logging.error(f"Erro ao enviar mensagem WhatsApp: {e}")


def gerar_protocolo():
    """Gera protocolo único"""
    return f"DEN-{secrets.token_hex(4).upper()}"


def gerar_senha():
    """Gera senha aleatória segura"""
    return secrets.token_urlsafe(6)


# ======================================================
# Fluxo principal
# ======================================================
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.form
    user_number = data.get("From", "").replace("whatsapp:", "")
    body = data.get("Body", "").strip()
    session = user_sessions.get(user_number, {"step": 0, "dados": {}})

    step = session["step"]
    dados = session["dados"]

    # ------------------ Etapa 0 (Menu inicial) ------------------
    if step == 0:
        enviar_whatsapp(
            user_number,
            "👋 Olá! Bem-vindo ao Canal de Denúncias de Compliance.\n\n"
            "Escolha uma opção:\n"
            "1️⃣ Fazer denúncia anônima\n"
            "2️⃣ Fazer denúncia identificada\n"
            "3️⃣ Consultar protocolo existente\n"
            "4️⃣ Encerrar atendimento"
        )
        session["step"] = 1

    # ------------------ Etapa 1 (Escolha inicial) ------------------
    elif step == 1:
        if body == "1":
            dados["anonimo"] = True
            dados["tipo"] = "Anônima"
            enviar_whatsapp(user_number, "📝 Por favor, descreva sua denúncia:")
            session["step"] = 2

        elif body == "2":
            dados["anonimo"] = False
            dados["tipo"] = "Identificada"
            enviar_whatsapp(user_number, "👤 Informe seu nome completo:")
            session["step"] = 10

        elif body == "3":
            enviar_whatsapp(user_number, "🔎 Digite seu protocolo:")
            session["step"] = 20

        elif body == "4":
            enviar_whatsapp(user_number, "✅ Atendimento encerrado. Obrigado por utilizar o canal de compliance.")
            session = {"step": 0, "dados": {}}

        else:
            enviar_whatsapp(user_number, "⚠️ Opção inválida. Digite 1, 2, 3 ou 4.")

    # ------------------ Etapa 2 (Descrição da denúncia) ------------------
    elif step == 2:
        dados["descricao"] = body
        resumo = f"📋 Resumo da denúncia:\n\n👤 Tipo: {dados['tipo']}\n📝 Descrição: {dados['descricao']}\n\n" \
                 "✅ Se estas informações estão corretas:\n" \
                 "Digite 1️⃣ para confirmar e registrar sua denúncia\n" \
                 "Digite 2️⃣ para corrigir alguma informação\n" \
                 "Digite 3️⃣ para cancelar."
        enviar_whatsapp(user_number, resumo)
        session["step"] = 3

    # ------------------ Etapa 3 (Confirmação denúncia) ------------------
    elif step == 3:
        if body == "1":
            protocolo = gerar_protocolo()
            senha = gerar_senha()
            dados["protocolo"] = protocolo
            dados["senha"] = senha
            dados["criado_em"] = datetime.utcnow().isoformat()
            dados["status"] = "registrada"

            # Insere no Supabase
            supabase.table("denuncias").insert(dados).execute()

            enviar_whatsapp(
                user_number,
                f"✅ Sua denúncia foi registrada com sucesso!\n\n"
                f"📌 Protocolo: {protocolo}\n🔑 Senha: {senha}\n\n"
                "Guarde estas informações para futuras consultas."
            )
            session = {"step": 0, "dados": {}}

        elif body == "2":
            enviar_whatsapp(user_number, "🔄 Ok, por favor descreva novamente sua denúncia:")
            session["step"] = 2

        elif body == "3":
            enviar_whatsapp(user_number, "❌ Denúncia cancelada.")
            session = {"step": 0, "dados": {}}

        else:
            enviar_whatsapp(user_number, "⚠️ Opção inválida. Digite 1, 2 ou 3.")

    # ------------------ Etapas Identificada ------------------
    elif step == 10:
        dados["nome"] = body
        enviar_whatsapp(user_number, "📧 Informe seu e-mail:")
        session["step"] = 11

    elif step == 11:
        dados["email"] = body
        enviar_whatsapp(user_number, "📱 Informe seu telefone:")
        session["step"] = 12

    elif step == 12:
        dados["telefone"] = body
        enviar_whatsapp(user_number, "📝 Agora descreva sua denúncia:")
        session["step"] = 2

    # ------------------ Consulta de protocolo ------------------
    elif step == 20:
        dados["consulta_protocolo"] = body
        enviar_whatsapp(user_number, "🔑 Digite sua senha:")
        session["step"] = 21

    elif step == 21:
        protocolo = dados.get("consulta_protocolo")
        senha = body

        result = supabase.table("denuncias").select("*").eq("protocolo", protocolo).eq("senha", senha).execute()

        if result.data:
            denuncia = result.data[0]
            enviar_whatsapp(
                user_number,
                f"📌 Consulta realizada com sucesso!\n\n"
                f"👤 Tipo: {denuncia.get('tipo')}\n"
                f"📝 Descrição: {denuncia.get('descricao')}\n"
                f"📅 Criado em: {denuncia.get('criado_em')}\n"
                f"📊 Status: {denuncia.get('status')}"
            )
        else:
            enviar_whatsapp(user_number, "❌ Protocolo ou senha inválidos.")

        session = {"step": 0, "dados": {}}

    # ======================================================
    # Atualiza sessão
    # ======================================================
    user_sessions[user_number] = session
    return "OK", 200


# ======================================================
# Health-check
# ======================================================
@app.route("/", methods=["GET"])
def index():
    return "✅ Serviço de denúncias ativo", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
