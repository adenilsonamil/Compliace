import os
import random
import string
import time
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from supabase import create_client, Client
import openai

# Configurações
app = Flask(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
openai.api_key = OPENAI_API_KEY

# Sessões temporárias
sessions = {}

# Função para gerar protocolo
def gerar_protocolo():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    from_number = request.values.get("From", "").replace("whatsapp:", "")
    resp = MessagingResponse()
    msg = resp.message()

    # Recupera sessão
    if from_number not in sessions:
        sessions[from_number] = {"etapa": "inicio", "dados": {}}

    etapa = sessions[from_number]["etapa"]
    dados = sessions[from_number]["dados"]

    # Fluxo inicial
    if etapa == "inicio":
        msg.body("👋 Bem-vindo ao Canal de Denúncias de Compliance!\n\n"
                 "Deseja prosseguir como:\n\n"
                 "1️⃣ Anônimo\n2️⃣ Identificado")
        sessions[from_number]["etapa"] = "escolha"
    
    # Escolha de anonimato ou identificado
    elif etapa == "escolha":
        if incoming_msg == "1":
            dados["tipo"] = "anonimo"
            msg.body("✅ Você escolheu denúncia anônima.\n\nPor favor, descreva sua denúncia:")
            sessions[from_number]["etapa"] = "coletar_denuncia"
        elif incoming_msg == "2":
            dados["tipo"] = "identificado"
            msg.body("✍️ Por favor, informe seu *nome completo*:")
            sessions[from_number]["etapa"] = "coletar_nome"
        else:
            msg.body("⚠️ Resposta inválida. Digite `1` para Anônimo ou `2` para Identificado.")

    # Coleta de nome (se identificado)
    elif etapa == "coletar_nome":
        dados["nome"] = incoming_msg
        msg.body("📧 Agora, por favor, informe seu *e-mail*:")
        sessions[from_number]["etapa"] = "coletar_email"

    # Coleta de e-mail (se identificado)
    elif etapa == "coletar_email":
        dados["email"] = incoming_msg
        msg.body("✍️ Obrigado. Agora descreva sua denúncia:")
        sessions[from_number]["etapa"] = "coletar_denuncia"

    # Coleta da denúncia e resumo pela IA
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

    # Confirmação da denúncia
    elif etapa == "confirmar":
        if incoming_msg == "1":
            protocolo = gerar_protocolo()
            dados["protocolo"] = protocolo
            dados["telefone"] = from_number

            supabase.table("denuncias").insert(dados).execute()

            msg.body(f"🎉 Sua denúncia foi registrada com sucesso!\n\n"
                     f"📌 Protocolo: *{protocolo}*\n\n"
                     f"Use esse número para consultar o andamento.")
            sessions.pop(from_number)
        elif incoming_msg == "2":
            sessions[from_number]["etapa"] = "coletar_denuncia"
            msg.body("✍️ Ok, por favor reescreva sua denúncia:")
        else:
            msg.body("⚠️ Resposta inválida. Digite `1` para confirmar ou `2` para corrigir.")

    # Consulta de protocolo
    elif incoming_msg.lower().startswith("protocolo"):
        parts = incoming_msg.split()
        if len(parts) == 2:
            protocolo = parts[1].upper()
            result = supabase.table("denuncias").select("*").eq("protocolo", protocolo).eq("telefone", from_number).execute()
            if result.data:
                denuncia = result.data[0]
                msg.body(f"📌 Consulta do protocolo *{protocolo}*:\n\n"
                         f"Resumo: {denuncia['resumo']}\n"
                         f"Tipo: {denuncia['tipo']}\n"
                         f"Status: Em análise")
            else:
                msg.body("❌ Nenhuma denúncia encontrada com esse protocolo vinculado ao seu número.")
        else:
            msg.body("⚠️ Para consultar, envie: Protocolo XXXXXXXX")

    # Caso padrão - se não for denúncia ou protocolo
    else:
        msg.body("🤖 Este é o canal de denúncias de compliance.\n\n"
                 "Digite `oi` para iniciar uma denúncia\n"
                 "ou `Protocolo XXXXXXXX` para consultar.")

    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
