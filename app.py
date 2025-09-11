import os
import logging
from flask import Flask, request
from twilio.rest import Client
from supabase import create_client
from cryptography.fernet import Fernet
import openai
from uuid import uuid4

# -------------------------------------------------
# Configuração de logging seguro
# -------------------------------------------------
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# -------------------------------------------------
# Variáveis de ambiente (Render ou .env local)
# -------------------------------------------------
required_env_vars = [
    "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER",
    "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY",
    "OPENAI_API_KEY", "ENCRYPTION_KEY"
]

for var in required_env_vars:
    if not os.getenv(var):
        raise ValueError(f"❌ Variável de ambiente obrigatória não definida: {var}")

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

# -------------------------------------------------
# Inicializações
# -------------------------------------------------
app = Flask(__name__)
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
openai.api_key = OPENAI_API_KEY
fernet = Fernet(ENCRYPTION_KEY)

conversation_state = {}

# -------------------------------------------------
# Funções auxiliares
# -------------------------------------------------
def encrypt(value: str) -> str:
    return fernet.encrypt(value.encode()).decode() if value else None

def send_message(to, body):
    logger.debug(f"Enviando para {to}: {body}")
    twilio_client.messages.create(
        body=body,
        from_=f"whatsapp:{TWILIO_PHONE_NUMBER}",
        to=to
    )

def corrigir_texto(texto: str) -> str:
    try:
        resp = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Você é um assistente de revisão de texto. Corrija apenas ortografia e gramática, sem mudar o sentido."},
                {"role": "user", "content": texto}
            ]
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Erro ao corrigir texto: {e}")
        return texto

# -------------------------------------------------
# Webhook principal
# -------------------------------------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    from_number = request.form.get("From")
    message = request.form.get("Body", "").strip()
    num_media = int(request.form.get("NumMedia", 0))

    if from_number not in conversation_state:
        conversation_state[from_number] = {"step": "inicio", "dados": {}}

    step = conversation_state[from_number]["step"]
    dados = conversation_state[from_number]["dados"]

    # -------------------------------------------------
    # Fluxo da conversa
    # -------------------------------------------------
    if step == "inicio":
        send_message(from_number,
            "👋 Olá! Bem-vindo ao Canal de Denúncias de Compliance.\n\n"
            "Escolha uma opção:\n"
            "1️⃣ Fazer denúncia *anônima*\n"
            "2️⃣ Fazer denúncia *identificada*\n"
            "3️⃣ Consultar protocolo existente\n"
            "4️⃣ Encerrar atendimento"
        )
        conversation_state[from_number]["step"] = "escolha"

    elif step == "escolha":
        if message == "1":
            dados["tipo"] = "Anônima"
            dados["nome"] = None
            dados["email"] = None
            dados["telefone"] = None
            send_message(from_number, "✍️ Por favor, descreva sua denúncia:")
            conversation_state[from_number]["step"] = "descricao"
        elif message == "2":
            dados["tipo"] = "Identificada"
            send_message(from_number, "👤 Informe seu nome completo:")
            conversation_state[from_number]["step"] = "nome"
        elif message == "3":
            send_message(from_number, "🔎 Consulta de protocolo ainda não implementada.")
        elif message == "4":
            send_message(from_number, "✅ Atendimento encerrado.")
            conversation_state.pop(from_number, None)
        else:
            send_message(from_number, "⚠️ Opção inválida. Digite 1, 2, 3 ou 4.")

    elif step == "nome":
        dados["nome"] = encrypt(corrigir_texto(message))
        send_message(from_number, "📧 Informe seu e-mail:")
        conversation_state[from_number]["step"] = "email"

    elif step == "email":
        dados["email"] = encrypt(corrigir_texto(message))
        send_message(from_number, "📱 Informe seu telefone:")
        conversation_state[from_number]["step"] = "telefone"

    elif step == "telefone":
        dados["telefone"] = encrypt(corrigir_texto(message))
        send_message(from_number, "✍️ Agora descreva sua denúncia:")
        conversation_state[from_number]["step"] = "descricao"

    elif step == "descricao":
        dados["descricao"] = corrigir_texto(message)
        send_message(from_number, "🗓️ Quando o fato ocorreu (data e horário aproximados)?")
        conversation_state[from_number]["step"] = "data"

    elif step == "data":
        dados["data"] = corrigir_texto(message)
        send_message(from_number, "📍 Onde aconteceu o fato (setor, filial, área, etc.)?")
        conversation_state[from_number]["step"] = "local"

    elif step == "local":
        dados["local"] = corrigir_texto(message)
        send_message(from_number, "👥 Quem estava envolvido? (cargos ou funções)")
        conversation_state[from_number]["step"] = "envolvidos"

    elif step == "envolvidos":
        dados["envolvidos"] = corrigir_texto(message)
        send_message(from_number, "👀 Havia testemunhas?")
        conversation_state[from_number]["step"] = "testemunhas"

    elif step == "testemunhas":
        dados["testemunhas"] = corrigir_texto(message)
        send_message(from_number, "📎 Você possui documentos, fotos, vídeos ou outras evidências que possam ajudar?")
        conversation_state[from_number]["step"] = "evidencias"

    elif step == "evidencias":
        if "sim" in message.lower():
            conversation_state[from_number]["step"] = "evidencias_confirmar"
            send_message(from_number,
                "Deseja anexar agora?\n"
                "Digite 1️⃣ para enviar as evidências\n"
                "Digite 2️⃣ para prosseguir sem anexar"
            )
        else:
            dados["evidencias"] = "Não"
            conversation_state[from_number]["step"] = "frequencia"
            send_message(from_number, "🔄 Esse fato ocorreu apenas uma vez ou é recorrente?")

    elif step == "evidencias_confirmar":
        if message == "1":
            conversation_state[from_number]["step"] = "aguardando_upload"
            send_message(from_number, "📤 Envie os arquivos (fotos, vídeos ou documentos).")
        else:
            dados["evidencias"] = "Não anexadas"
            conversation_state[from_number]["step"] = "frequencia"
            send_message(from_number, "🔄 Esse fato ocorreu apenas uma vez ou é recorrente?")

    elif step == "aguardando_upload":
        if num_media > 0:
            media_urls = [request.form.get(f"MediaUrl{i}") for i in range(num_media)]
            dados["midias"] = media_urls
            dados["evidencias"] = "Anexadas"
            conversation_state[from_number]["step"] = "frequencia"
            send_message(from_number, "✅ Evidências anexadas.\n\n🔄 Esse fato ocorreu apenas uma vez ou é recorrente?")
        else:
            send_message(from_number, "⚠️ Nenhum arquivo recebido. Envie novamente ou digite 'pular' para continuar.")

    elif step == "frequencia":
        dados["frequencia"] = corrigir_texto(message)
        send_message(from_number, "⚖️ Qual o impacto ou gravidade do ocorrido?")
        conversation_state[from_number]["step"] = "impacto"

    elif step == "impacto":
        dados["impacto"] = corrigir_texto(message)
        resumo = (
            f"📋 Resumo da denúncia:\n\n"
            f"👤 Tipo: {dados.get('tipo')}\n"
            f"📝 Descrição: {dados.get('descricao')}\n"
            f"🗓️ Data: {dados.get('data')}\n"
            f"📍 Local: {dados.get('local')}\n"
            f"👥 Envolvidos: {dados.get('envolvidos')}\n"
            f"👀 Testemunhas: {dados.get('testemunhas')}\n"
            f"📎 Evidências: {dados.get('evidencias')}\n"
            f"🔄 Frequência: {dados.get('frequencia')}\n"
            f"⚖️ Impacto: {dados.get('impacto')}\n\n"
            "✅ Se estas informações estão corretas:\n"
            "Digite 1️⃣ para confirmar e registrar sua denúncia\n"
            "Digite 2️⃣ para corrigir alguma informação\n"
            "Digite 3️⃣ para cancelar."
        )
        send_message(from_number, resumo)
        conversation_state[from_number]["step"] = "confirmar"

    elif step == "confirmar":
        if message == "1":
            protocolo = str(uuid4())[:8]

            registro = {
                "protocolo": protocolo,
                "tipo": dados.get("tipo"),
                "nome": dados.get("nome"),
                "email": dados.get("email"),
                "telefone": dados.get("telefone"),
                "descricao": dados.get("descricao"),
                "data": dados.get("data"),
                "local": dados.get("local"),
                "envolvidos": dados.get("envolvidos"),
                "testemunhas": dados.get("testemunhas"),
                "evidencias": dados.get("evidencias"),
                "frequencia": dados.get("frequencia"),
                "impacto": dados.get("impacto"),
                "midias": dados.get("midias", [])
            }

            supabase.table("denuncias").insert(registro).execute()
            send_message(from_number, f"✅ Sua denúncia foi registrada.\n📌 Protocolo: {protocolo}")
            conversation_state.pop(from_number, None)

        elif message == "2":
            send_message(from_number, "⚙️ Função de correção ainda não implementada.")
        elif message == "3":
            send_message(from_number, "❌ Denúncia cancelada.")
            conversation_state.pop(from_number, None)
        else:
            send_message(from_number, "⚠️ Digite 1, 2 ou 3.")

    return "OK", 200

# -------------------------------------------------
# Início
# -------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
