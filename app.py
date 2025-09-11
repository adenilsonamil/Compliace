import os
import logging
import random
import string
from datetime import datetime
from flask import Flask, request
from twilio.rest import Client
from supabase import create_client, Client as SupabaseClient
from openai import OpenAI

# Configuração de logs
logging.basicConfig(level=logging.DEBUG)

# Flask app
app = Flask(__name__)

# Variáveis de ambiente
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE = os.getenv("TWILIO_PHONE_NUMBER")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

# Clientes
twilio_client = Client(TWILIO_SID, TWILIO_AUTH)
supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_KEY)
openai_client = OpenAI(api_key=OPENAI_KEY)

# Estado das conversas
conversas = {}

# Funções auxiliares
def gerar_protocolo():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def gerar_senha():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=6))

def enviar_whatsapp(to, mensagem):
    try:
        logging.debug(f"Enviando para {to}: {mensagem}")
        twilio_client.messages.create(
            from_=f"whatsapp:{TWILIO_PHONE}",
            to=to,
            body=mensagem
        )
    except Exception as e:
        logging.error(f"Erro ao enviar mensagem WhatsApp: {e}")

def interpretar_resposta(pergunta, resposta):
    try:
        completion = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Você é um assistente de compliance acolhedor. Corrija erros de português e extraia insights (categoria, gravidade, envolvidos, local). Responda em JSON."},
                {"role": "user", "content": f"Pergunta: {pergunta}\nResposta: {resposta}"}
            ],
            max_tokens=200,
            response_format={"type": "json_object"}  # corrigido
        )
        return completion.choices[0].message.content
    except Exception as e:
        logging.error(f"Erro interpretar_resposta: {e}")
        return "{}"

# Rota Webhook
@app.route("/webhook", methods=["POST"])
def webhook():
    sender = request.form.get("From")
    mensagem = request.form.get("Body", "").strip().lower()
    midia_url = request.form.get("MediaUrl0")

    if sender not in conversas:
        conversas[sender] = {"etapa": "menu", "dados": {}, "midias": []}
        enviar_whatsapp(sender,
            "👋 Olá! Bem-vindo ao *Canal de Denúncias de Compliance.*\n\n"
            "Escolha uma opção:\n"
            "1️⃣ Fazer denúncia *anônima*\n"
            "2️⃣ Fazer denúncia *identificada*\n"
            "3️⃣ Consultar protocolo existente\n"
            "4️⃣ Encerrar atendimento"
        )
        return "OK", 200

    conversa = conversas[sender]

    # Captura de mídias
    if midia_url:
        conversa["midias"].append(midia_url)
        enviar_whatsapp(sender, "📎 Evidência recebida com sucesso.")
        return "OK", 200

    # Fluxo principal
    etapa = conversa["etapa"]

    if etapa == "menu":
        if mensagem == "1":
            conversa["dados"]["tipo"] = "anônima"
            conversa["etapa"] = "descricao"
            enviar_whatsapp(sender, "✍️ Pode me contar com suas palavras o que aconteceu?")
        elif mensagem == "2":
            conversa["dados"]["tipo"] = "identificada"
            conversa["etapa"] = "nome"
            enviar_whatsapp(sender, "👤 Qual é o seu nome?")
        elif mensagem == "3":
            conversa["etapa"] = "consultar"
            enviar_whatsapp(sender, "🔎 Informe o protocolo que deseja consultar:")
        elif mensagem == "4":
            enviar_whatsapp(sender, "✅ Atendimento encerrado. Obrigado.")
            conversas.pop(sender, None)
        else:
            enviar_whatsapp(sender, "❌ Opção inválida. Escolha entre 1, 2, 3 ou 4.")

    elif etapa == "nome":
        conversa["dados"]["nome"] = mensagem
        conversa["etapa"] = "email"
        enviar_whatsapp(sender, "📧 Informe seu e-mail:")

    elif etapa == "email":
        conversa["dados"]["email"] = mensagem
        conversa["etapa"] = "descricao"
        enviar_whatsapp(sender, "✍️ Pode me contar com suas palavras o que aconteceu?")

    elif etapa == "descricao":
        conversa["dados"]["descricao"] = mensagem
        conversa["etapa"] = "data"
        enviar_whatsapp(sender, "🗓️ Quando o fato ocorreu?")

    elif etapa == "data":
        conversa["dados"]["data"] = mensagem
        conversa["etapa"] = "local"
        enviar_whatsapp(sender, "📍 Onde aconteceu?")

    elif etapa == "local":
        conversa["dados"]["local"] = mensagem
        conversa["etapa"] = "envolvidos"
        enviar_whatsapp(sender, "👥 Quem estava envolvido?")

    elif etapa == "envolvidos":
        conversa["dados"]["envolvidos"] = mensagem
        conversa["etapa"] = "testemunhas"
        enviar_whatsapp(sender, "👀 Alguém presenciou o ocorrido?")

    elif etapa == "testemunhas":
        conversa["dados"]["testemunhas"] = mensagem
        conversa["etapa"] = "impacto"
        enviar_whatsapp(sender, "⚖️ Qual foi o impacto do ocorrido?")

    elif etapa == "impacto":
        conversa["dados"]["impacto"] = mensagem
        conversa["etapa"] = "evidencias"
        enviar_whatsapp(sender, "📎 Você possui evidências? Digite 'sim' ou 'não'.")

    elif etapa == "evidencias":
        if mensagem in ["sim", "s"]:
            conversa["etapa"] = "anexar"
            enviar_whatsapp(sender, "📤 Pode enviar as evidências (fotos, vídeos ou documentos).")
        else:
            conversa["etapa"] = "finalizar"
            enviar_whatsapp(sender, "✅ Entendido. Estamos quase finalizando sua denúncia.")

    elif etapa == "anexar":
        conversa["etapa"] = "finalizar"
        enviar_whatsapp(sender, "✅ Evidências registradas. Estamos quase finalizando sua denúncia.")

    elif etapa == "finalizar":
        protocolo = gerar_protocolo()
        senha = gerar_senha()
        dados = conversa["dados"]
        midias = conversa["midias"]

        supabase.table("denuncias").insert({
            "protocolo": protocolo,
            "senha": senha,
            "tipo": dados.get("tipo"),
            "nome": dados.get("nome"),
            "email": dados.get("email"),
            "telefone": sender.replace("whatsapp:", ""),
            "descricao": dados.get("descricao"),
            "categoria": dados.get("categoria"),
            "data_fato": dados.get("data"),
            "local": dados.get("local"),
            "envolvidos": dados.get("envolvidos"),
            "testemunhas": dados.get("testemunhas"),
            "impacto": dados.get("impacto"),
            "midias": midias,
            "status": "aberto"
        }).execute()

        enviar_whatsapp(sender,
            f"✅ Sua denúncia foi registrada com sucesso!\n\n"
            f"📌 Protocolo: *{protocolo}*\n"
            f"🔑 Senha: *{senha}*\n\n"
            "Guarde essas informações para consultar o andamento futuramente."
        )
        conversas.pop(sender, None)

    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
