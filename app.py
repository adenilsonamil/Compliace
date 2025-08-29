import os
import uuid
import time
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from supabase import create_client, Client
from openai import OpenAI

# ========================
# Configurações de API
# ========================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
openai = OpenAI(api_key=OPENAI_API_KEY)

# Flask App
app = Flask(__name__)

# Sessões temporárias em memória
sessions = {}
SESSION_TIMEOUT = 300  # 5 minutos


def reset_session(from_number):
    """Reseta a sessão de um usuário"""
    sessions[from_number] = {
        "step": "inicio",
        "dados": {},
        "last_activity": time.time()
    }


def update_activity(from_number):
    """Atualiza timestamp da sessão"""
    if from_number in sessions:
        sessions[from_number]["last_activity"] = time.time()


def check_session_timeout(from_number):
    """Reseta a sessão se passar de 5 minutos"""
    if from_number in sessions:
        if time.time() - sessions[from_number]["last_activity"] > SESSION_TIMEOUT:
            reset_session(from_number)


def resumir_texto(texto):
    """Usa IA para resumir a denúncia"""
    try:
        resposta = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Resuma a seguinte denúncia de forma clara, objetiva e formal."},
                {"role": "user", "content": texto}
            ],
            max_tokens=100
        )
        return resposta.choices[0].message.content.strip()
    except Exception:
        return texto  # fallback sem IA


@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    from_number = request.values.get("From", "")

    check_session_timeout(from_number)
    if from_number not in sessions:
        reset_session(from_number)

    session = sessions[from_number]
    update_activity(from_number)

    step = session["step"]
    msg = MessagingResponse().message()

    # ========================
    # Fluxo
    # ========================

    # Início
    if step == "inicio":
        session["step"] = "tipo_denuncia"
        msg.body(
            "👋 Bem-vindo ao Canal de Denúncias de Compliance!\n\n"
            "Deseja prosseguir como:\n\n"
            "1️⃣ Anônimo\n"
            "2️⃣ Identificado"
        )

    # Escolha tipo de denúncia
    elif step == "tipo_denuncia":
        if incoming_msg == "1":
            session["dados"]["anonima"] = True
            session["step"] = "denuncia"
            msg.body("✅ Ok! Você escolheu denúncia **anônima**.\n\nPor favor, descreva sua denúncia:")
        elif incoming_msg == "2":
            session["dados"]["anonima"] = False
            session["step"] = "nome"
            msg.body("✍️ Por favor, informe seu nome completo:")
        else:
            msg.body("⚠️ Opção inválida. Digite 1 para Anônimo ou 2 para Identificado.")

    # Nome identificado
    elif step == "nome":
        session["dados"]["nome"] = incoming_msg
        session["step"] = "email"
        msg.body("📧 Agora, informe seu e-mail:")

    # Email identificado
    elif step == "email":
        session["dados"]["email"] = incoming_msg
        session["step"] = "denuncia"
        msg.body("✍️ Obrigado! Agora descreva sua denúncia:")

    # Texto da denúncia
    elif step == "denuncia":
        session["dados"]["descricao"] = incoming_msg
        resumo = resumir_texto(incoming_msg)
        session["dados"]["resumo"] = resumo
        session["step"] = "confirmar"
        msg.body(
            f"📋 Aqui está o resumo da sua denúncia:\n\n"
            f"{resumo}\n\n"
            "Confirma que está correto?\n\n"
            "1️⃣ Confirmar\n"
            "2️⃣ Corrigir"
        )

    # Confirmação
    elif step == "confirmar":
        if incoming_msg == "1":
            protocolo = str(uuid.uuid4())[:8].upper()
            session["dados"]["protocolo"] = protocolo
            session["step"] = "finalizado"

            denuncia_data = {
                "telefone": from_number,
                "anonima": session["dados"].get("anonima", True),
                "nome": session["dados"].get("nome"),
                "email": session["dados"].get("email"),
                "descricao": session["dados"].get("descricao"),
                "resumo": session["dados"].get("resumo"),
                "protocolo": protocolo
            }
            supabase.table("denuncias").insert(denuncia_data).execute()

            msg.body(
                f"✅ Sua denúncia foi registrada com sucesso!\n\n"
                f"📋 Resumo:\n{session['dados']['resumo']}\n\n"
                f"📌 Protocolo: *{protocolo}*\n\n"
                "Guarde esse número para acompanhar o andamento. "
                "Basta enviá-lo aqui no chat para consultar futuramente."
            )

        elif incoming_msg == "2":
            session["step"] = "denuncia"
            msg.body("✍️ Ok, por favor reescreva sua denúncia:")
        else:
            msg.body("⚠️ Resposta inválida. Digite 1 para Confirmar ou 2 para Corrigir.")

    # Consulta de protocolo
    elif step in ["finalizado", "inicio", "tipo_denuncia"]:
        if len(incoming_msg) == 8:  # possível protocolo
            result = supabase.table("denuncias").select("*").eq("protocolo", incoming_msg).eq("telefone", from_number).execute()
            if result.data:
                denuncia = result.data[0]
                msg.body(
                    f"📌 Consulta de protocolo *{incoming_msg}*:\n\n"
                    f"Resumo: {denuncia['resumo']}\n\n"
                    "Caso queira abrir nova denúncia, digite *oi*."
                )
            else:
                msg.body("⚠️ Protocolo não encontrado ou não pertence a este número.")
        else:
            reset_session(from_number)
            session = sessions[from_number]
            msg.body(
                "👋 Bem-vindo ao Canal de Denúncias de Compliance!\n\n"
                "Deseja prosseguir como:\n\n"
                "1️⃣ Anônimo\n"
                "2️⃣ Identificado"
            )

    return str(msg)


if __name__ == "__main__":
    app.run(debug=True)
