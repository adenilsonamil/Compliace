import os
import uuid
import datetime
import time
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from supabase import create_client, Client
from openai import OpenAI

# 🔑 Variáveis de ambiente (configure no Render Dashboard)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TWILIO_NUMBER = os.getenv("TWILIO_NUMBER")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = Flask(__name__)

# Sessões em memória: telefone -> estado
sessions = {}

def gerar_protocolo():
    agora = datetime.datetime.now()
    return f"{agora.year}-{str(uuid.uuid4())[:8]}"

def gerar_resumo(texto):
    prompt = f"Resuma em poucas linhas, de forma clara e humanizada, o seguinte relato de denúncia:\n\n{texto}"
    resposta = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    return resposta.choices[0].message.content.strip()

@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    telefone = request.form.get("From", "").replace("whatsapp:", "")
    mensagem = request.form.get("Body", "").strip()
    resp = MessagingResponse()

    # Se não há sessão iniciada, cria
    if telefone not in sessions:
        sessions[telefone] = {"step": "inicio"}
        resp.message("👋 Olá! Bem-vindo ao Canal de Denúncias de Compliance.\n"
                     "Aguarde um momento...")
        time.sleep(5)
        resp.message("Deseja fazer a denúncia de forma:\n1️⃣ Anônima\n2️⃣ Identificada")
        return str(resp)

    session = sessions[telefone]
    step = session["step"]

    # Fluxo inicial
    if step == "inicio":
        if mensagem == "1":
            session["tipo"] = "Anônima"
            session["step"] = "coleta_relato"
            resp.message("Você escolheu denúncia anônima ✅\n\nPor favor, descreva sua denúncia:")
        elif mensagem == "2":
            session["tipo"] = "Identificada"
            session["step"] = "coleta_nome"
            resp.message("Por favor, informe seu nome completo:")
        else:
            resp.message("Por favor, escolha:\n1️⃣ Anônima\n2️⃣ Identificada")
        return str(resp)

    # Coletar dados identificados
    if step == "coleta_nome":
        session["nome"] = mensagem
        session["step"] = "coleta_email"
        resp.message("Agora, informe seu e-mail:")
        return str(resp)

    if step == "coleta_email":
        session["email"] = mensagem
        session["step"] = "coleta_relato"
        resp.message("Obrigado 🙏 Agora descreva sua denúncia com o máximo de detalhes:")
        return str(resp)

    # Coleta de relato
    if step == "coleta_relato":
        session["relato"] = mensagem
        resumo = gerar_resumo(mensagem)
        session["resumo"] = resumo
        session["step"] = "confirmar"
        resp.message(f"📝 Aqui está o resumo da sua denúncia:\n\n{resumo}\n\n"
                     "Está correto?\nDigite 'SIM' para confirmar ou descreva o que deseja corrigir.")
        return str(resp)

    # Confirmação
    if step == "confirmar":
        if mensagem.upper() == "SIM":
            protocolo = gerar_protocolo()
            session["protocolo"] = protocolo

            # Salvar no Supabase
            supabase.table("denuncias").insert({
                "id": str(uuid.uuid4()),
                "telefone": telefone,
                "protocolo": protocolo,
                "tipo": session.get("tipo"),
                "nome": session.get("nome", None),
                "email": session.get("email", None),
                "relato": session.get("relato"),
                "resumo_ia": session.get("resumo"),
                "status": "Aberta",
                "criado_em": datetime.datetime.utcnow().isoformat()
            }).execute()

            resp.message(f"✅ Sua denúncia foi registrada com sucesso!\n"
                         f"📌 Protocolo: {protocolo}\n\n"
                         f"Guarde este número para consultas futuras.")
            session["step"] = "finalizado"
        else:
            session["relato"] = mensagem
            resumo = gerar_resumo(mensagem)
            session["resumo"] = resumo
            resp.message(f"🔄 Novo resumo gerado:\n\n{resumo}\n\n"
                         "Digite 'SIM' para confirmar ou corrija novamente.")
        return str(resp)

    # Consulta por protocolo
    if mensagem.lower().startswith("consultar"):
        try:
            protocolo_req = mensagem.split(" ")[1].strip()
            result = supabase.table("denuncias").select("*").eq("protocolo", protocolo_req).eq("telefone", telefone).execute()
            if result.data:
                denuncia = result.data[0]
                resp.message(f"📋 Protocolo: {denuncia['protocolo']}\n"
                             f"Status: {denuncia['status']}\n"
                             f"Resumo: {denuncia['resumo_ia']}")
            else:
                resp.message("⚠️ Protocolo não encontrado ou não pertence ao seu número.")
        except:
            resp.message("Use o formato: Consultar 2025-XXXX")
        return str(resp)

    # Se não for denúncia → IA ajuda
    if step in ["finalizado", "inicio"]:
        resposta = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": f"Um usuário mandou a mensagem '{mensagem}' no canal de denúncias. Responda de forma educada e útil."}]
        )
        resp.message(resposta.choices[0].message.content.strip())
        return str(resp)

    return str(resp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)
