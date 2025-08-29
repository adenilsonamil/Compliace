import os
import random
import string
import time
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from supabase import create_client, Client
from openai import OpenAI

# Configurações de ambiente
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
openai = OpenAI(api_key=OPENAI_API_KEY)

app = Flask(__name__)

# Sessões de conversa em memória
sessions = {}

# Função para gerar protocolo único
def gerar_protocolo():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    from_number = request.values.get("From", "")
    resp = MessagingResponse()
    msg = resp.message()

    # Reiniciar fluxo se usuário pedir
    if incoming_msg.lower() in ["menu", "nova denúncia", "nova denuncia"]:
        sessions.pop(from_number, None)
        msg.body("👋 Bem-vindo ao Canal de Denúncias de Compliance!\n\n"
                 "Deseja prosseguir como:\n\n"
                 "1️⃣ Anônimo\n2️⃣ Identificado")
        sessions[from_number] = {"etapa": "inicio", "dados": {}}
        return str(resp)

    # Se não existe sessão, inicia fluxo
    if from_number not in sessions:
        msg.body("👋 Bem-vindo ao Canal de Denúncias de Compliance!\n\n"
                 "Deseja prosseguir como:\n\n"
                 "1️⃣ Anônimo\n2️⃣ Identificado")
        sessions[from_number] = {"etapa": "inicio", "dados": {}}
        return str(resp)

    etapa = sessions[from_number]["etapa"]
    dados = sessions[from_number]["dados"]

    # Escolha inicial
    if etapa == "inicio":
        if incoming_msg == "1":
            sessions[from_number]["etapa"] = "coletar_denuncia"
            msg.body("✅ Ok! Você escolheu denúncia **anônima**.\n\n"
                     "Por favor, descreva sua denúncia:")
        elif incoming_msg == "2":
            sessions[from_number]["etapa"] = "coletar_nome"
            msg.body("📝 Ok! Você escolheu denúncia **identificada**.\n\n"
                     "Por favor, informe seu nome completo:")
        else:
            msg.body("⚠️ Resposta inválida.\nDigite `1` para Anônimo ou `2` para Identificado.")

    # Coleta dados identificados
    elif etapa == "coletar_nome":
        dados["nome"] = incoming_msg
        sessions[from_number]["etapa"] = "coletar_email"
        msg.body("📧 Agora, por favor informe seu e-mail:")

    elif etapa == "coletar_email":
        dados["email"] = incoming_msg
        sessions[from_number]["etapa"] = "coletar_denuncia"
        msg.body("✍️ Obrigado! Agora descreva sua denúncia:")

    # Coleta denúncia (resumida pela IA)
    elif etapa == "coletar_denuncia":
        dados["descricao"] = incoming_msg

        # Tenta resumir com IA
        try:
            completion = openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Você é um assistente de compliance. Reformule a denúncia em linguagem clara, objetiva e formal."},
                    {"role": "user", "content": incoming_msg}
                ]
            )
            resumo = completion.choices[0].message.content.strip()
        except Exception:
            resumo = incoming_msg

        dados["resumo"] = resumo
        sessions[from_number]["etapa"] = "confirmar"
        msg.body(f"📋 Aqui está o resumo da sua denúncia:\n\n"
                 f"{resumo}\n\n"
                 f"Confirma que está correto?\n\n"
                 f"1️⃣ Confirmar\n2️⃣ Corrigir")

    # Confirmação
    elif etapa == "confirmar":
        if incoming_msg == "1":
            protocolo = gerar_protocolo()
            dados["protocolo"] = protocolo
            dados["telefone"] = from_number

            supabase.table("denuncias").insert(dados).execute()

            msg.body(f"🎉 Sua denúncia foi registrada com sucesso!\n\n"
                     f"📌 Protocolo: *{protocolo}*\n\n"
                     f"Use esse número para consultar o andamento.\n\n"
                     f"Digite 'menu' para iniciar uma nova denúncia.")
            sessions.pop(from_number)
        elif incoming_msg == "2":
            sessions[from_number]["etapa"] = "coletar_denuncia"
            msg.body("✍️ Ok, por favor reescreva sua denúncia:")
        else:
            msg.body("⚠️ Resposta inválida.\nDigite `1` para confirmar ou `2` para corrigir.")

    return str(resp)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
