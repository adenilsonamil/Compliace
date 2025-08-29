import os
import random
import string
from datetime import datetime, timedelta
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from supabase import create_client, Client

# Configurações de ambiente
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TWILIO_NUMBER = os.getenv("TWILIO_NUMBER")

# Inicializar Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Flask app
app = Flask(__name__)

# Sessões de usuários
user_sessions = {}

# Função para gerar protocolo
def gerar_protocolo():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=7))

# Função para resetar sessão após inatividade
def verificar_timeout(session):
    if "last_active" in session:
        if datetime.now() - session["last_active"] > timedelta(minutes=5):
            return True
    return False

@app.route("/bot", methods=["POST"])
def bot():
    incoming_msg = request.values.get("Body", "").strip()
    from_number = request.values.get("From", "")
    response = MessagingResponse()

    # Recuperar ou criar sessão
    session = user_sessions.get(from_number, {"step": "inicio"})
    if verificar_timeout(session):
        session = {"step": "inicio"}
    session["last_active"] = datetime.now()

    # Fluxo inicial
    if session["step"] == "inicio":
        response.message(
            "👋 Bem-vindo ao Canal de Denúncias de Compliance!\n\n"
            "Deseja prosseguir como:\n\n"
            "1️⃣ Anônimo\n"
            "2️⃣ Identificado"
        )
        session["step"] = "tipo"
        user_sessions[from_number] = session
        return str(response)

    # Escolha do tipo
    elif session["step"] == "tipo":
        if incoming_msg == "1":
            session["tipo"] = "anonimo"
            session["step"] = "denuncia"
            response.message("✅ Você escolheu denúncia anônima.\n\nPor favor, descreva sua denúncia:")
        elif incoming_msg == "2":
            session["tipo"] = "identificado"
            session["step"] = "nome"
            response.message("✍️ Por favor, informe seu nome:")
        else:
            response.message("⚠️ Opção inválida. Responda com 1 para Anônimo ou 2 para Identificado.")
        user_sessions[from_number] = session
        return str(response)

    # Nome do denunciante
    elif session["step"] == "nome":
        session["nome"] = incoming_msg
        session["step"] = "denuncia"
        response.message("Por favor, descreva sua denúncia:")
        user_sessions[from_number] = session
        return str(response)

    # Descrição da denúncia
    elif session["step"] == "denuncia":
        session["denuncia"] = incoming_msg
        session["step"] = "confirmar"
        response.message(
            f"📋 Aqui está o resumo da sua denúncia:\n\n{incoming_msg}\n\n"
            "Confirma que está correto?\n\n"
            "1️⃣ Confirmar\n"
            "2️⃣ Corrigir"
        )
        user_sessions[from_number] = session
        return str(response)

    # Confirmação
    elif session["step"] == "confirmar":
        if incoming_msg == "1":
            protocolo = gerar_protocolo()

            # Inserir no Supabase
            supabase.table("denuncias").insert({
                "protocolo": protocolo,
                "tipo": session.get("tipo"),
                "nome": session.get("nome"),
                "descricao": session.get("denuncia"),
                "telefone": from_number,
                "created_at": datetime.now().isoformat()
            }).execute()

            # Resposta final com protocolo
            response.message(
                f"✅ Sua denúncia foi registrada com sucesso!\n\n"
                f"📋 Protocolo: *{protocolo}*\n"
                f"Você pode consultar sua denúncia posteriormente usando este número."
            )

            # Resetar sessão
            user_sessions.pop(from_number, None)
            return str(response)

        elif incoming_msg == "2":
            session["step"] = "denuncia"
            response.message("✍️ Ok, por favor reescreva sua denúncia:")
            user_sessions[from_number] = session
            return str(response)

        else:
            response.message("⚠️ Responda com 1 para Confirmar ou 2 para Corrigir.")
            return str(response)

    # Caso não bata com nenhum estado
    else:
        response.message("⚠️ Algo deu errado. Digite qualquer coisa para reiniciar o processo.")
        user_sessions.pop(from_number, None)
        return str(response)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
