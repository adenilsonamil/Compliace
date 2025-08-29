import os
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from supabase import create_client, Client
from datetime import datetime
import uuid

# ----------------------------
# Configurações do Supabase
# ----------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ----------------------------
# App Flask
# ----------------------------
app = Flask(__name__)

# ----------------------------
# Rota principal (health-check)
# ----------------------------
@app.route("/")
def home():
    return "✅ Compliance Bot rodando!"

# ----------------------------
# Função para salvar denúncia
# ----------------------------
def salvar_denuncia(user_phone, mensagem, anonimo=False):
    denuncia_id = str(uuid.uuid4())[:8]  # protocolo curto
    data = datetime.utcnow().isoformat()

    dados = {
        "id": denuncia_id,
        "telefone": None if anonimo else user_phone,
        "mensagem": mensagem,
        "status": "registrada",
        "data": data,
    }

    supabase.table("denuncias").insert(dados).execute()
    return denuncia_id

# ----------------------------
# Webhook do WhatsApp
# ----------------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    user_phone = request.values.get("From", "").replace("whatsapp:", "")

    resp = MessagingResponse()
    msg = resp.message()

    # Fluxo de denúncia anônima
    if incoming_msg.lower().startswith("anonimo"):
        texto = incoming_msg.replace("anonimo", "", 1).strip()
        if not texto:
            msg.body("⚠️ Envie sua denúncia anônima no formato:\n\n*Anonimo minha mensagem aqui*")
        else:
            protocolo = salvar_denuncia(user_phone, texto, anonimo=True)
            msg.body(f"✅ Sua denúncia anônima foi registrada com sucesso!\n\n📌 Protocolo: *{protocolo}*\n\nObrigado por confiar no nosso canal de Compliance.")
        return str(resp)

    # Fluxo normal de denúncia (não anônima)
    elif incoming_msg.lower().startswith("denuncia"):
        texto = incoming_msg.replace("denuncia", "", 1).strip()
        if not texto:
            msg.body("⚠️ Envie sua denúncia no formato:\n\n*Denuncia minha mensagem aqui*")
        else:
            protocolo = salvar_denuncia(user_phone, texto, anonimo=False)
            msg.body(f"✅ Sua denúncia foi registrada com sucesso!\n\n📌 Protocolo: *{protocolo}*\n👤 Registrada com seu número: {user_phone}\n\nObrigado por confiar no nosso canal de Compliance.")
        return str(resp)

    # Consultar status de uma denúncia
    elif incoming_msg.lower().startswith("status"):
        protocolo = incoming_msg.replace("status", "", 1).strip()
        if not protocolo:
            msg.body("⚠️ Envie no formato:\n\n*Status PROTOCOLO*")
        else:
            resultado = supabase.table("denuncias").select("*").eq("id", protocolo).execute()
            if resultado.data:
                denuncia = resultado.data[0]
                msg.body(f"📋 Status da denúncia {protocolo}:\n\n📝 {denuncia['mensagem']}\n📅 {denuncia['data']}\n📌 Status: {denuncia['status']}")
            else:
                msg.body("❌ Protocolo não encontrado. Verifique o código enviado.")
        return str(resp)

    # Ajuda
    elif incoming_msg.lower() in ["ajuda", "menu", "help"]:
        msg.body(
            "📖 *Menu do Canal de Compliance*\n\n"
            "1️⃣ Registrar denúncia identificada:\n"
            "   ➡️ *Denuncia sua mensagem aqui*\n\n"
            "2️⃣ Registrar denúncia anônima:\n"
            "   ➡️ *Anonimo sua mensagem aqui*\n\n"
            "3️⃣ Consultar status:\n"
            "   ➡️ *Status PROTOCOLO*\n\n"
            "4️⃣ Ajuda:\n"
            "   ➡️ *Ajuda*"
        )
        return str(resp)

    # Resposta padrão
    else:
        msg.body("👋 Bem-vindo ao Canal de Denúncias de Compliance!\n\nEnvie *Ajuda* para ver os comandos disponíveis.")
        return str(resp)


# ----------------------------
# Run local
# ----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)
