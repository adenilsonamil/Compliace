from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import uuid
import os

app = Flask(__name__)

# Armazena temporariamente as denúncias em memória
denuncias = {}

@app.route("/webhook", methods=['POST'])
def webhook():
    incoming_msg = request.values.get('Body', '').strip().lower()
    sender = request.values.get('From')

    resp = MessagingResponse()
    msg = resp.message()

    if sender not in denuncias:
        denuncias[sender] = {"etapa": "inicio", "dados": {}}
        msg.body("🔒 Olá, este é o Canal de Denúncias de Compliance.\n\n"
                 "Você deseja fazer sua denúncia de forma:\n"
                 "1️⃣ Anônima\n2️⃣ Identificada")
        return str(resp)

    etapa = denuncias[sender]["etapa"]

    if etapa == "inicio":
        if "1" in incoming_msg:
            denuncias[sender]["dados"]["tipo"] = "Anônimo"
            denuncias[sender]["etapa"] = "descricao"
            msg.body("✅ Ok, sua denúncia será ANÔNIMA.\n\nPor favor, descreva a situação:")
        elif "2" in incoming_msg:
            denuncias[sender]["dados"]["tipo"] = "Identificado"
            denuncias[sender]["etapa"] = "nome"
            msg.body("Por favor, informe seu nome:")
        else:
            msg.body("Responda apenas com 1️⃣ ou 2️⃣ para continuar.")

    elif etapa == "nome":
        denuncias[sender]["dados"]["nome"] = incoming_msg
        denuncias[sender]["etapa"] = "descricao"
        msg.body("Obrigado. Agora, descreva a situação que deseja denunciar:")

    elif etapa == "descricao":
        denuncias[sender]["dados"]["descricao"] = incoming_msg
        protocolo = f"DEN-{str(uuid.uuid4())[:8]}"
        denuncias[sender]["dados"]["protocolo"] = protocolo
        denuncias[sender]["etapa"] = "fim"

        # Aqui você pode salvar no Supabase/Postgres
        msg.body(f"✅ Sua denúncia foi registrada com sucesso.\n\n"
                 f"📌 Protocolo: {protocolo}\n"
                 "🔒 Nossa equipe de Compliance irá analisar sua denúncia.\n\n"
                 "Se desejar registrar outra, escreva 'nova denúncia'.")
