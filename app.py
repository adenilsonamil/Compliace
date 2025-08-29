from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import time
import threading

app = Flask(__name__)

# estados de conversa por telefone
user_states = {}

def send_delayed_message(to, body, delay=5):
    """Envia mensagem com atraso (simulação)"""
    def delayed():
        time.sleep(delay)
        from twilio.rest import Client
        import os
        client = Client(os.getenv("TWILIO_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
        client.messages.create(
            body=body,
            from_=os.getenv("TWILIO_NUMBER"),
            to=to
        )
    threading.Thread(target=delayed).start()

@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    incoming_msg = request.values.get("Body", "").strip().lower()
    from_number = request.values.get("From")

    resp = MessagingResponse()
    msg = resp.message()

    # Se for a primeira mensagem do usuário
    if from_number not in user_states:
        user_states[from_number] = {"stage": "inicio"}
        msg.body("👋 Bem-vindo ao Canal de Denúncias de Compliance!")
        
        # dispara em 5 segundos a mensagem com as opções
        send_delayed_message(
            from_number,
            "Por favor, escolha uma opção:\n\n1️⃣ Fazer denúncia anônima\n2️⃣ Fazer denúncia identificada"
        )
        return str(resp)

    # Caso já esteja em andamento
    state = user_states[from_number]

    if state["stage"] == "inicio":
        if incoming_msg == "1":
            user_states[from_number]["stage"] = "anonima"
            msg.body("✅ Você escolheu denúncia anônima.\nPor favor, descreva sua denúncia:")
        elif incoming_msg == "2":
            user_states[from_number]["stage"] = "identificada_nome"
            msg.body("✍️ Você escolheu denúncia identificada.\nPor favor, informe seu *nome completo*:")
        else:
            msg.body("⚠️ Digite *1* para denúncia anônima ou *2* para denúncia identificada.")
    
    elif state["stage"] == "identificada_nome":
        user_states[from_number]["nome"] = incoming_msg
        user_states[from_number]["stage"] = "identificada_email"
        msg.body("📧 Agora, informe seu *e-mail*:")

    elif state["stage"] == "identificada_email":
        user_states[from_number]["email"] = incoming_msg
        user_states[from_number]["stage"] = "relato"
        msg.body("Por favor, descreva sua denúncia:")

    elif state["stage"] in ["anonima", "relato"]:
        user_states[from_number]["relato"] = incoming_msg
        user_states[from_number]["stage"] = "confirmar"
        msg.body(f"📄 Aqui está o resumo da sua denúncia:\n\n{incoming_msg}\n\n✅ Está correto? (Responda SIM ou NÃO)")

    elif state["stage"] == "confirmar":
        if "sim" in incoming_msg:
            protocolo = "PROTOCOLO123"  # aqui você vai gerar de verdade
            msg.body(f"🎫 Sua denúncia foi registrada com sucesso!\nNúmero de protocolo: {protocolo}")
            user_states[from_number]["stage"] = "finalizado"
        else:
            user_states[from_number]["stage"] = "relato"
            msg.body("🔄 Ok, por favor descreva novamente sua denúncia:")

    return str(resp)
