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

# Sessões temporárias na memória
sessoes = {}
TIMEOUT = timedelta(minutes=5)


def reset_sessao(telefone):
    if telefone in sessoes:
        del sessoes[telefone]


def enviar_msg(para, texto):
    """Envia mensagem pelo WhatsApp"""
    logging.debug(f"Enviando para {para}: {texto}")
    twilio_client.messages.create(
        from_=TWILIO_NUMBER,
        to=para,
        body=texto
    )


@app.route("/webhook", methods=["POST"])
def webhook():
    telefone = request.form.get("From")
    msg = request.form.get("Body").strip() if request.form.get("Body") else ""
    logging.debug(f"Mensagem recebida de {telefone}: {msg}")

    agora = datetime.now()

    # Cria sessão se não existir ou se expirou
    if telefone not in sessoes or agora - sessoes[telefone]["ultima_interacao"] > TIMEOUT:
        sessoes[telefone] = {"etapa": "inicio", "dados": {}, "ultima_interacao": agora}
        enviar_msg(telefone, "👋 Olá! Bem-vindo ao Canal de Denúncias de Compliance.\n\n"
                             "Escolha uma opção:\n"
                             "1️⃣ Fazer denúncia *anônima*\n"
                             "2️⃣ Fazer denúncia *identificada*\n"
                             "3️⃣ Consultar protocolo existente\n"
                             "4️⃣ Encerrar atendimento")
        return "OK", 200

    # Atualiza timestamp da sessão
    sessoes[telefone]["ultima_interacao"] = agora
    etapa = sessoes[telefone]["etapa"]
    dados = sessoes[telefone]["dados"]

    # Encerrar atendimento
    if msg == "4":
        reset_sessao(telefone)
        enviar_msg(telefone, "✅ Atendimento encerrado. Digite qualquer mensagem para começar de novo.")
        return "OK", 200

    # Consultar protocolo
    if msg == "3":
        sessoes[telefone]["etapa"] = "consultar_protocolo"
        enviar_msg(telefone, "📄 Informe o número do protocolo que deseja consultar:")
        return "OK", 200

    if etapa == "consultar_protocolo":
        protocolo = msg
        result = supabase.table("denuncias").select("*").eq("protocolo", protocolo).eq("telefone", telefone).execute()
        if result.data:
            descricao = result.data[0]
            enviar_msg(telefone, f"📌 Protocolo {protocolo} encontrado:\n\nResumo: {descricao.get('resumo', 'Sem resumo disponível')}\n"
                                 f"Categoria: {descricao.get('categoria', 'Não classificada')}")
        else:
            enviar_msg(telefone, "⚠️ Nenhum protocolo encontrado para o seu número.")
        reset_sessao(telefone)
        return "OK", 200

    # Início do fluxo
    if etapa == "inicio":
        if msg == "1":
            sessoes[telefone]["etapa"] = "coletar_descricao"
            sessoes[telefone]["dados"]["anonimo"] = True
            sessoes[telefone]["dados"]["tipo"] = "anonimo"
            enviar_msg(telefone, "✍️ Por favor, descreva sua denúncia:")
        elif msg == "2":
            sessoes[telefone]["etapa"] = "coletar_nome"
            sessoes[telefone]["dados"]["anonimo"] = False
            sessoes[telefone]["dados"]["tipo"] = "identificado"
            enviar_msg(telefone, "👤 Informe seu nome completo:")
        elif msg not in ["1", "2", "3", "4"]:
            enviar_msg(telefone, "⚠️ Opção inválida. Escolha:\n1️⃣ Anônima\n2️⃣ Identificada\n3️⃣ Consultar\n4️⃣ Encerrar")
        return "OK", 200

    # Fluxo denúncia identificada
    if etapa == "coletar_nome":
        dados["nome"] = msg
        sessoes[telefone]["etapa"] = "coletar_email"
        enviar_msg(telefone, "📧 Agora, informe seu e-mail:")
        return "OK", 200

    if etapa == "coletar_email":
        dados["email"] = msg
        sessoes[telefone]["etapa"] = "coletar_descricao"
        enviar_msg(telefone, "✍️ Por favor, descreva sua denúncia:")
        return "OK", 200

    # Coleta da denúncia
    if etapa == "coletar_descricao":
        dados["descricao"] = msg

        # Resumir e classificar denúncia com IA
        resposta = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": (
                    "Você é um assistente de compliance. "
                    "Sua tarefa é: "
                    "1. Resumir a denúncia em até 3 linhas de forma clara e objetiva. "
                    "2. Classificar a denúncia em UMA categoria da lista abaixo:\n"
                    "- Assédio moral\n"
                    "- Assédio sexual\n"
                    "- Discriminação\n"
                    "- Corrupção / Suborno\n"
                    "- Fraude\n"
                    "- Conflito de interesses\n"
                    "- Outro"
                )},
                {"role": "user", "content": dados["descricao"]}
            ]
        ).choices[0].message.content

        # Separar resumo e categoria
        resumo, categoria = "", "Outro"
        if "Categoria:" in resposta:
            partes = resposta.split("Categoria:")
            resumo = partes[0].replace("Resumo:", "").strip()
            categoria = partes[1].strip()
        else:
            resumo = resposta.strip()

        dados["resumo"] = resumo
        dados["categoria"] = categoria
        sessoes[telefone]["etapa"] = "confirmar"

        enviar_msg(telefone, f"📋 Aqui está o resumo da sua denúncia:\n\n{resumo}\n\n"
                             f"🗂️ Categoria sugerida: {categoria}\n\n"
                             "Digite 1️⃣ para confirmar ou 2️⃣ para corrigir.")
        return "OK", 200

    # Confirmação
    if etapa == "confirmar":
        if msg == "1":
            protocolo = str(uuid.uuid4())[:8]
            dados["protocolo"] = protocolo
            dados["telefone"] = telefone

            supabase.table("denuncias").insert(dados).execute()

            enviar_msg(telefone, f"✅ Sua denúncia foi registrada com sucesso!\n"
                                 f"📌 Número de protocolo: {protocolo}\n\n"
                                 f"Guarde este número para futuras consultas.")
            reset_sessao(telefone)
        elif msg == "2":
            sessoes[telefone]["etapa"] = "coletar_descricao"
            enviar_msg(telefone, "✍️ Ok, descreva novamente sua denúncia:")
        else:
            enviar_msg(telefone, "⚠️ Resposta inválida. Digite 1️⃣ para confirmar ou 2️⃣ para corrigir.")
        return "OK", 200

    return "OK", 200


@app.route("/", methods=["GET"])
def home():
    return "✅ Compliance Bot está rodando!", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
