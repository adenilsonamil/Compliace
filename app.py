from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from supabase import create_client, Client
import uuid
import os

app = Flask(__name__)

# Conexão com Supabase
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Armazena etapas por usuário
fluxos = {}

@app.route("/webhook", methods=['POST'])
def webhook():
    incoming_msg = request.values.get('Body', '').strip()
    sender = request.values.get('From')

    resp = MessagingResponse()
    msg = resp.message()

    # Início do fluxo
    if sender not in fluxos:
        fluxos[sender] = {"etapa": "inicio", "dados": {}}
        msg.body("🔒 Olá, este é o Canal de Denúncias de Compliance.\n\n"
                 "Você deseja fazer sua denúncia de forma:\n"
                 "1️⃣ Anônima\n2️⃣ Identificada")
        return str(resp)

    etapa = fluxos[sender]["etapa"]

    if etapa == "inicio":
        if incoming_msg == "1":
            fluxos[sender]["dados"]["tipo"] = "Anônimo"
            fluxos[sender]["etapa"] = "descricao"
            msg.body("✅ Ok, sua denúncia será **ANÔNIMA**.\n\nPor favor, descreva a situação:")
        elif incoming_msg == "2":
            fluxos[sender]["dados"]["tipo"] = "Identificado"
            fluxos[sender]["etapa"] = "nome"
            msg.body("Por favor, informe seu **nome**:")
        else:
            msg.body("Responda apenas com 1️⃣ ou 2️⃣ para continuar.")

    elif etapa == "nome":
        fluxos[sender]["dados"]["nome"] = incoming_msg
        fluxos[sender]["etapa"] = "descricao"
        msg.body("Obrigado. Agora, descreva a situação que deseja denunciar:")

    elif etapa == "descricao":
        fluxos[sender]["dados"]["descricao"] = incoming_msg
        protocolo = f"DEN-{str(uuid.uuid4())[:8]}"
        fluxos[sender]["dados"]["protocolo"] = protocolo
        fluxos[sender]["etapa"] = "fim"

        # Salvar no Supabase
        data = {
            "protocolo": protocolo,
            "tipo": fluxos[sender]["dados"].get("tipo"),
            "nome": fluxos[sender]["dados"].get("nome"),
            "descricao": fluxos[sender]["dados"].get("descricao")
        }
        supabase.table("denuncias").insert(data).execute()

        msg.body(f"✅ Sua denúncia foi registrada com sucesso.\n\n"
                 f"📌 Protocolo: *{protocolo}*\n"
                 "🔒 Nossa equipe de Compliance irá analisar sua denúncia.\n\n"
                 "Se desejar registrar outra, escreva 'nova denúncia'.")

    elif etapa == "fim" and "nova" in incoming_msg.lower():
        fluxos[sender] = {"etapa": "inicio", "dados": {}}
        msg.body("🔄 Iniciando um novo registro.\n\n"
                 "Você deseja fazer sua denúncia de forma:\n"
                 "1️⃣ Anônima\n2️⃣ Identificada")

    else:
        msg.body("✅ Sua denúncia já foi registrada. Digite 'nova denúncia' para abrir outra.")

    return str(resp)


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
