import os
import time
import random
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from supabase import create_client, Client
from openai import OpenAI

# ==============================
# Variáveis de ambiente obrigatórias
# ==============================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("❌ Variáveis SUPABASE_URL e SUPABASE_KEY não configuradas.")

if not OPENAI_API_KEY:
    raise ValueError("❌ Variável OPENAI_API_KEY não configurada.")

# ==============================
# Inicializações
# ==============================
app = Flask(__name__)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
openai = OpenAI(api_key=OPENAI_API_KEY)

# Estados de sessão por usuário
user_sessions = {}

# ==============================
# Função para gerar protocolo único
# ==============================
def generate_protocol():
    return f"PROTO-{random.randint(10000, 99999)}"

# ==============================
# Função para resumir denúncia (com fallback)
# ==============================
def resumir_texto(texto):
    try:
        resposta = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Resuma a denúncia de forma clara e objetiva."},
                {"role": "user", "content": texto}
            ],
            max_tokens=100
        )
        return resposta.choices[0].message.content.strip()
    except Exception as e:
        print(f"⚠️ Erro ao resumir com OpenAI: {e}")
        return texto  # fallback → retorna o texto original

# ==============================
# Rota principal do webhook
# ==============================
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    from_number = request.values.get("From", "").replace("whatsapp:", "")
    resp = MessagingResponse()
    msg = resp.message()

    # Se não existir sessão, cria
    if from_number not in user_sessions:
        user_sessions[from_number] = {"state": "menu"}
        msg.body("👋 Bem-vindo ao Canal de Denúncias de Compliance!\n\nDeseja prosseguir como:\n\n1️⃣ Anônimo\n2️⃣ Identificado")
        return str(resp)

    session = user_sessions[from_number]

    # ==============================
    # Estado: menu inicial
    # ==============================
    if session["state"] == "menu":
        if incoming_msg == "1":
            session["anonimo"] = True
            session["state"] = "denuncia"
            msg.body("✅ Ok! Você escolheu denúncia **anônima**.\n\nPor favor, descreva sua denúncia:")
        elif incoming_msg == "2":
            session["anonimo"] = False
            session["state"] = "identificacao_nome"
            msg.body("Por favor, informe seu **nome completo**:")
        else:
            msg.body("❌ Opção inválida. Responda com:\n1️⃣ Anônimo\n2️⃣ Identificado")

    # ==============================
    # Identificação
    # ==============================
    elif session["state"] == "identificacao_nome":
        session["nome"] = incoming_msg
        session["state"] = "identificacao_email"
        msg.body("Agora, informe seu **e-mail**:")

    elif session["state"] == "identificacao_email":
        session["email"] = incoming_msg
        session["state"] = "denuncia"
        msg.body("Obrigado! Agora descreva sua denúncia:")

    # ==============================
    # Coleta da denúncia
    # ==============================
    elif session["state"] == "denuncia":
        session["denuncia_raw"] = incoming_msg
        resumo = resumir_texto(incoming_msg)
        session["denuncia_resumida"] = resumo
        session["state"] = "confirmacao"
        msg.body(f"Aqui está o resumo da sua denúncia:\n\n{resumo}\n\nConfirma que está correto?\n1️⃣ Confirmar\n2️⃣ Corrigir")

    # ==============================
    # Confirmação
    # ==============================
    elif session["state"] == "confirmacao":
        if incoming_msg == "1":
            protocolo = generate_protocol()
            session["protocolo"] = protocolo

            # Salvar no Supabase
            data = {
                "telefone": from_number,
                "anonimo": session.get("anonimo", True),
                "nome": session.get("nome", None),
                "email": session.get("email", None),
                "denuncia": session["denuncia_resumida"],
                "protocolo": protocolo
            }
            supabase.table("denuncias").insert(data).execute()

            msg.body(f"✅ Sua denúncia foi registrada com sucesso!\n\n📌 Protocolo: *{protocolo}*\n\nVocê pode consultar o andamento enviando o número do protocolo.")
            session["state"] = "menu"

        elif incoming_msg == "2":
            session["state"] = "denuncia"
            msg.body("✍️ Ok, por favor reescreva sua denúncia:")
        else:
            msg.body("❌ Resposta inválida. Digite:\n1️⃣ Confirmar\n2️⃣ Corrigir")

    # ==============================
    # Consulta de protocolo
    # ==============================
    else:
        if incoming_msg.startswith("PROTO-"):
            protocolo = incoming_msg.strip()
            result = supabase.table("denuncias").select("*").eq("telefone", from_number).eq("protocolo", protocolo).execute()
            if result.data:
                denuncia = result.data[0]
                msg.body(f"📋 Protocolo {protocolo}\n\nDenúncia registrada:\n{denuncia['denuncia']}")
            else:
                msg.body("❌ Protocolo não encontrado ou não pertence a este número.")
        else:
            msg.body("🤖 Não entendi. Digite:\n1️⃣ para denúncia anônima\n2️⃣ para denúncia identificada\nOu informe um número de protocolo.")

    return str(resp)

# ==============================
# Inicialização local
# ==============================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)
