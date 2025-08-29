import os
import random
import string
import time
from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse
from supabase import create_client, Client
import openai

# Configs
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TWILIO_NUMBER = os.getenv("TWILIO_NUMBER")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
openai.api_key = OPENAI_API_KEY

app = Flask(__name__)

# Sessões temporárias
sessions = {}
SESSION_TIMEOUT = 300  # 5 minutos


def gerar_protocolo():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))


def resumir_texto(texto):
    try:
        resp = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Resuma a denúncia de forma clara e objetiva."},
                {"role": "user", "content": texto}
            ],
            max_tokens=60
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return texto  # fallback caso falhe a API


def resetar_sessao(telefone):
    if telefone in sessions:
        del sessions[telefone]


def processar_mensagem(telefone, msg):
    agora = time.time()

    # Reset automático após inatividade
    if telefone in sessions and agora - sessions[telefone]["ultimo_tempo"] > SESSION_TIMEOUT:
        resetar_sessao(telefone)

    # Nova sessão
    if telefone not in sessions:
        sessions[telefone] = {"etapa": "inicio", "ultimo_tempo": agora}
        return ("👋 Bem-vindo ao Canal de Denúncias de Compliance!\n"
                "Deseja prosseguir como:\n\n"
                "1️⃣ Anônimo\n"
                "2️⃣ Identificado")

    sessions[telefone]["ultimo_tempo"] = agora
    etapa = sessions[telefone]["etapa"]

    # Etapa escolha tipo
    if etapa == "inicio":
        if msg == "1":
            sessions[telefone]["tipo"] = "anonimo"
            sessions[telefone]["etapa"] = "descricao"
            return "✅ Ok! Você escolheu denúncia **anônima**.\n\nPor favor, descreva sua denúncia:"
        elif msg == "2":
            sessions[telefone]["tipo"] = "identificado"
            sessions[telefone]["etapa"] = "nome"
            return "✍️ Por favor, digite seu nome:"
        else:
            return "⚠️ Escolha inválida. Digite *1* para Anônimo ou *2* para Identificado."

    # Nome se identificado
    if etapa == "nome":
        sessions[telefone]["nome"] = msg
        sessions[telefone]["etapa"] = "descricao"
        return "✍️ Agora, descreva sua denúncia:"

    # Descrição
    if etapa == "descricao":
        resumo = resumir_texto(msg)
        sessions[telefone]["descricao"] = resumo
        sessions[telefone]["etapa"] = "confirmar"
        return (f"📝 Aqui está o resumo da sua denúncia:\n\n{resumo}\n\n"
                "Confirma que está correto?\n\n"
                "1️⃣ Confirmar\n"
                "2️⃣ Corrigir")

    # Confirmação
    if etapa == "confirmar":
        if msg == "1":
            protocolo = gerar_protocolo()
            sessions[telefone]["protocolo"] = protocolo

            # Salvar no Supabase
            try:
                supabase.table("denuncias").insert({
                    "protocolo": protocolo,
                    "tipo": sessions[telefone].get("tipo", "anonimo"),
                    "nome": sessions[telefone].get("nome"),
                    "descricao": sessions[telefone].get("descricao"),
                    "telefone": telefone
                }).execute()
            except Exception as e:
                return f"⚠️ Erro ao salvar denúncia: {e}"

            resetar_sessao(telefone)
            return (f"✅ Sua denúncia foi registrada com sucesso!\n\n"
                    f"📌 Protocolo: *{protocolo}*\n\n"
                    "Guarde este número para futuras consultas.")
        elif msg == "2":
            sessions[telefone]["etapa"] = "descricao"
            return "✍️ Ok, por favor reescreva sua denúncia:"
        else:
            return "⚠️ Resposta inválida. Digite *1* para Confirmar ou *2* para Corrigir."

    return "⚠️ Não entendi sua resposta. Digite novamente."


@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    telefone = request.values.get("From", "")

    resposta = processar_mensagem(telefone, incoming_msg)

    twilio_resp = MessagingResponse()
    twilio_resp.message(resposta)
    return Response(str(twilio_resp), mimetype="application/xml")


@app.route("/")
def index():
    return "Compliance Bot rodando 🚀", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
