import os
import time
import uuid
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from supabase import create_client, Client
import openai

# ================== CONFIG ==================
app = Flask(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

openai.api_key = os.getenv("OPENAI_API_KEY")

# ================== ESTADO DE CONVERSAS ==================
sessions = {}  # {"telefone": {"etapa": ..., "dados": {...}}}

def gerar_protocolo():
    return str(uuid.uuid4())[:8].upper()

# ================== ROTA PRINCIPAL ==================
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    from_number = request.values.get("From")

    resp = MessagingResponse()
    msg = resp.message()

    # Criar sessão caso não exista
    if from_number not in sessions:
        sessions[from_number] = {"etapa": "inicio", "dados": {}}
        msg.body("👋 Bem-vindo ao Canal de Denúncias de Compliance!")
        time.sleep(5)
        msg.body("Deseja prosseguir como:\n\n1️⃣ Anônimo\n2️⃣ Identificado")
        return str(resp)

    etapa = sessions[from_number]["etapa"]
    dados = sessions[from_number]["dados"]

    # ====== FLUXO PRINCIPAL ======
    if etapa == "inicio":
        if incoming_msg == "1":
            sessions[from_number]["etapa"] = "coletar_denuncia"
            msg.body("✅ Ok! Você escolheu denúncia anônima.\n\nPor favor, descreva sua denúncia:")
        elif incoming_msg == "2":
            sessions[from_number]["etapa"] = "coletar_nome"
            msg.body("✍️ Por favor, informe seu *nome completo*:")
        else:
            msg.body("⚠️ Responda apenas com 1️⃣ para Anônima ou 2️⃣ para Identificada.")
    
    elif etapa == "coletar_nome":
        dados["nome"] = incoming_msg
        sessions[from_number]["etapa"] = "coletar_email"
        msg.body("📧 Agora, informe seu *e-mail*:")
    
    elif etapa == "coletar_email":
        dados["email"] = incoming_msg
        sessions[from_number]["etapa"] = "coletar_denuncia"
        msg.body("✅ Obrigado!\n\nAgora, descreva sua denúncia:")
    
    elif etapa == "coletar_denuncia":
        dados["descricao"] = incoming_msg

        # Enviar para OpenAI para organizar
        try:
            completion = openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Você é um assistente de compliance. Reorganize a denúncia de forma clara e objetiva."},
                    {"role": "user", "content": incoming_msg}
                ]
            )
            resumo = completion.choices[0].message.content.strip()
        except Exception:
            resumo = incoming_msg

        dados["resumo"] = resumo
        sessions[from_number]["etapa"] = "confirmar"
        msg.body(f"📋 Aqui está o resumo da sua denúncia:\n\n{resumo}\n\nConfirma que está correto?\nResponda ✅ para confirmar ou ❌ para corrigir.")
    
    elif etapa == "confirmar":
        if incoming_msg.lower() in ["✅", "sim", "confirmo"]:
            protocolo = gerar_protocolo()
            dados["protocolo"] = protocolo
            dados["telefone"] = from_number

            supabase.table("denuncias").insert(dados).execute()

            msg.body(f"🎉 Sua denúncia foi registrada com sucesso!\n\n📌 Protocolo: *{protocolo}*\n\nUse esse número para consultar o andamento.")
            sessions.pop(from_number)
        elif incoming_msg.lower() in ["❌", "nao", "corrigir"]:
            sessions[from_number]["etapa"] = "coletar_denuncia"
            msg.body("✍️ Ok, por favor reescreva sua denúncia:")
        else:
            msg.body("⚠️ Responda apenas com ✅ para confirmar ou ❌ para corrigir.")
    
    else:
        # Verificar se o usuário está consultando protocolo
        if incoming_msg.upper().startswith("PROTOCOLO"):
            protocolo = incoming_msg.split()[-1].strip().upper()
            consulta = supabase.table("denuncias").select("*").eq("protocolo", protocolo).eq("telefone", from_number).execute()

            if consulta.data:
                denuncia = consulta.data[0]
                msg.body(f"📌 Consulta do protocolo *{protocolo}*:\n\nResumo: {denuncia['resumo']}\nStatus: Em análise ✅")
            else:
                msg.body("⚠️ Protocolo não encontrado ou não pertence a este número.")
        else:
            msg.body("🤖 Estou aqui para denúncias de compliance.\nDigite novamente ou envie 'Ajuda' para mais informações.")

    return str(resp)

# ================== MAIN ==================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)), debug=True)
