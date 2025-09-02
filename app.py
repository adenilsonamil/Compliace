import os
import uuid
import logging
from datetime import datetime, timedelta
from flask import Flask, request
from twilio.rest import Client
from supabase import create_client, Client as SupabaseClient
import openai

# Configurações
app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)

# ==============================
# 🔐 Carregamento das variáveis
# ==============================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = os.getenv("TWILIO_NUMBER")

# Validação obrigatória das env vars
REQUIRED_ENV_VARS = {
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_KEY": SUPABASE_KEY,
    "OPENAI_API_KEY": OPENAI_API_KEY,
    "TWILIO_ACCOUNT_SID": TWILIO_ACCOUNT_SID,
    "TWILIO_AUTH_TOKEN": TWILIO_AUTH_TOKEN,
    "TWILIO_NUMBER": TWILIO_NUMBER,
}

for var, value in REQUIRED_ENV_VARS.items():
    if not value:
        raise ValueError(f"❌ Variável de ambiente obrigatória não definida: {var}")

# Ajusta número para formato whatsapp:+...
if not TWILIO_NUMBER.startswith("whatsapp:"):
    TWILIO_NUMBER = f"whatsapp:{TWILIO_NUMBER}"

logging.debug(f"✅ TWILIO_NUMBER carregado: {TWILIO_NUMBER}")

# Inicializa clientes
supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_KEY)
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
openai.api_key = OPENAI_API_KEY

# Sessões temporárias
sessoes = {}
TIMEOUT = timedelta(minutes=5)

# ==============================
# 🔧 Funções auxiliares
# ==============================

def reset_sessao(telefone):
    sessoes.pop(telefone, None)
    supabase.table("sessoes").delete().eq("telefone", telefone).execute()


def salvar_sessao(telefone, etapa, dados, ultima_interacao):
    sessoes[telefone] = {"etapa": etapa, "dados": dados, "ultima_interacao": ultima_interacao}
    supabase.table("sessoes").upsert({
        "telefone": telefone,
        "etapa": etapa,
        "dados": dados,
        "ultima_interacao": ultima_interacao.isoformat()
    }).execute()


def carregar_sessao(telefone):
    if telefone in sessoes:
        return sessoes[telefone]
    result = supabase.table("sessoes").select("*").eq("telefone", telefone).execute()
    if result.data:
        sessao = result.data[0]
        sessao["ultima_interacao"] = datetime.fromisoformat(sessao["ultima_interacao"])
        sessoes[telefone] = sessao
        return sessao
    return None


def enviar_msg(para, texto):
    """Envia mensagem pelo WhatsApp"""
    logging.debug(f"Enviando para {para}: {texto}")
    twilio_client.messages.create(
        from_=TWILIO_NUMBER,
        to=para,
        body=texto
    )


def corrigir_texto(texto: str) -> str:
    """Usa a IA para corrigir ortografia e gramática"""
    try:
        resposta = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": (
                    "Você é um assistente de revisão de texto. "
                    "Corrija o texto do usuário apenas em ortografia e gramática, "
                    "sem mudar o sentido ou acrescentar informações."
                )},
                {"role": "user", "content": texto}
            ]
        )
        return resposta.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"Erro na correção do texto: {e}")
        return texto

# ==============================
# 📲 Webhook principal
# ==============================
@app.route("/webhook", methods=["POST"])
def webhook():
    telefone = request.form.get("From")
    msg = request.form.get("Body").strip() if request.form.get("Body") else ""
    logging.debug(f"Mensagem recebida de {telefone}: {msg}")

    agora = datetime.now()

    sessao = carregar_sessao(telefone)
    if not sessao or agora - sessao["ultima_interacao"] > TIMEOUT:
        sessao = {"etapa": "inicio", "dados": {}, "ultima_interacao": agora}
        salvar_sessao(telefone, "inicio", {}, agora)
        enviar_msg(telefone, "👋 Olá! Bem-vindo ao Canal de Denúncias de Compliance.\n\n"
                             "Escolha uma opção:\n"
                             "1️⃣ Fazer denúncia *anônima*\n"
                             "2️⃣ Fazer denúncia *identificada*\n"
                             "3️⃣ Consultar protocolo existente\n"
                             "4️⃣ Encerrar atendimento")
        return "OK", 200

    etapa = sessao["etapa"]
    dados = sessao["dados"]

    # ========================================
    # Encerrar
    # ========================================
    if msg == "4":
        reset_sessao(telefone)
        enviar_msg(telefone, "✅ Atendimento encerrado. Digite qualquer mensagem para começar de novo.")
        return "OK", 200

    # ========================================
    # Consultar protocolo
    # ========================================
    if msg == "3":
        salvar_sessao(telefone, "consultar_protocolo", dados, agora)
        enviar_msg(telefone, "📄 Informe o número do protocolo que deseja consultar:")
        return "OK", 200

    if etapa == "consultar_protocolo":
        protocolo = corrigir_texto(msg)
        result = supabase.table("denuncias").select("*").eq("protocolo", protocolo).eq("telefone", telefone).execute()
        if result.data:
            denuncia = result.data[0]
            enviar_msg(telefone, f"📌 Protocolo {protocolo} encontrado:\n\n"
                                 f"Resumo: {denuncia.get('resumo', 'Sem resumo')}\n"
                                 f"Categoria: {denuncia.get('categoria', 'Não classificada')}")
        else:
            enviar_msg(telefone, "⚠️ Nenhum protocolo encontrado para o seu número.")
        reset_sessao(telefone)
        return "OK", 200

    # ========================================
    # Início
    # ========================================
    if etapa == "inicio":
        if msg == "1":
            dados["anonimo"] = True
            salvar_sessao(telefone, "coletar_descricao", dados, agora)
            enviar_msg(telefone, "✍️ Por favor, descreva sua denúncia:")
        elif msg == "2":
            dados["anonimo"] = False
            salvar_sessao(telefone, "coletar_nome", dados, agora)
            enviar_msg(telefone, "👤 Informe seu nome completo:")
        else:
            enviar_msg(telefone, "⚠️ Opção inválida. Escolha:\n1️⃣ Anônima\n2️⃣ Identificada\n3️⃣ Consultar\n4️⃣ Encerrar")
        return "OK", 200

    # ========================================
    # Nome e Email (se identificado)
    # ========================================
    if etapa == "coletar_nome":
        dados["nome"] = corrigir_texto(msg)
        salvar_sessao(telefone, "coletar_email", dados, agora)
        enviar_msg(telefone, "📧 Agora, informe seu e-mail:")
        return "OK", 200

    if etapa == "coletar_email":
        dados["email"] = corrigir_texto(msg)
        salvar_sessao(telefone, "coletar_descricao", dados, agora)
        enviar_msg(telefone, "✍️ Por favor, descreva sua denúncia:")
        return "OK", 200

    # ========================================
    # Resumo final (com email corrigido)
    # ========================================
    if etapa == "coletar_impacto":
        dados["impacto"] = corrigir_texto(msg)

        telefone_str = telefone if not dados.get("anonimo") else "—"
        nome_str = dados.get("nome", "—") if not dados.get("anonimo") else "—"
        email_str = dados.get("email", "—") if not dados.get("anonimo") else "—"

        resumo_detalhado = (
            "📋 Resumo da sua denúncia:\n\n"
            f"👤 Tipo: {'Anônima' if dados.get('anonimo') else 'Identificada'}\n"
            f"Nome: {nome_str}\n"
            f"E-mail: {email_str}\n"
            f"Telefone: {telefone_str}\n\n"
            f"📝 Descrição: {dados.get('descricao', '—')}\n"
            f"📄 Resumo (IA): {dados.get('resumo', '—')}\n"
            f"🗂️ Categoria: {dados.get('categoria', '—')}\n\n"
            f"🗓️ Data do fato: {dados.get('data_fato', '—')}\n"
            f"📍 Local: {dados.get('local', '—')}\n"
            f"👥 Envolvidos: {dados.get('envolvidos', '—')}\n"
            f"👀 Testemunhas: {dados.get('testemunhas', '—')}\n"
            f"📎 Evidências: {dados.get('evidencias', '—')}\n"
            f"🔄 Frequência: {dados.get('frequencia', '—')}\n"
            f"⚖️ Impacto: {dados.get('impacto', '—')}\n\n"
            "✅ Se estas informações estão corretas,\n"
            "Digite 1️⃣ para confirmar\n"
            "Digite 2️⃣ para corrigir\n"
            "Digite 3️⃣ para cancelar"
        )

        salvar_sessao(telefone, "confirmar_final", dados, agora)
        enviar_msg(telefone, resumo_detalhado)
        return "OK", 200

    return "OK", 200

# ==============================
# 🌐 Endpoint principal
# ==============================
@app.route("/", methods=["GET", "HEAD"])
def home():
    return "✅ Compliance Bot está rodando!", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
