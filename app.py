import os
import time
import uuid
from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse
from supabase import create_client, Client
from openai import OpenAI

# Configurações de ambiente
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Conexão com Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Conexão com OpenAI
openai = OpenAI(api_key=OPENAI_API_KEY)

# Flask app
app = Flask(__name__)

# Estado da conversa em memória
user_sessions = {}

# Função IA para resumir denúncia
def resumir_texto(texto):
    try:
        resposta = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Você é um assistente especializado em compliance. Resuma a denúncia do usuário de forma clara e coerente."},
                {"role": "user", "content": texto}
            ]
        )
        return resposta.choices[0].message.content.strip()
    except Exception as e:
        return f"(Falha ao resumir com IA: {str(e)})"


@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    from_number = request.values.get("From", "").replace("whatsapp:", "")

    resp = MessagingResponse()
    msg = resp.message()

    # Se não existe sessão, cria
    if from_number not in user_sessions:
        user_sessions[from_number] = {"step": "inicio", "dados": {}}
        msg.body("👋 Olá! Bem-vindo ao Canal de Denúncias de Compliance.\n\n"
                 "Estamos aqui para ouvir você e tratar sua denúncia com sigilo e seriedade.")
        time.sleep(5)
        msg.body("Deseja realizar uma denúncia:\n1️⃣ Anônima\n2️⃣ Identificada")
        return str(resp)

    session = user_sessions[from_number]
    step = session["step"]

    # Etapas da conversa
    if step == "inicio":
        if incoming_msg == "1":
            session["dados"]["anonima"] = True
            session["step"] = "denuncia"
            msg.body("✅ Você escolheu fazer uma denúncia anônima.\n\nPor favor, descreva sua denúncia com o máximo de detalhes.")
        elif incoming_msg == "2":
            session["dados"]["anonima"] = False
            session["step"] = "nome"
            msg.body("Por favor, informe seu *nome completo*:")
        else:
            msg.body("⚠️ Opção inválida. Digite 1 para Anônima ou 2 para Identificada.")
    
    elif step == "nome":
        session["dados"]["nome"] = incoming_msg
        session["step"] = "email"
        msg.body("Agora, por favor, informe seu *e-mail*:")

    elif step == "email":
        session["dados"]["email"] = incoming_msg
        session["step"] = "denuncia"
        msg.body("✅ Obrigado! Agora, descreva sua denúncia com o máximo de detalhes:")

    elif step == "denuncia":
        session["dados"]["descricao"] = incoming_msg
        resumo = resumir_texto(incoming_msg)
        session["dados"]["resumo"] = resumo
        session["step"] = "confirmar"
        msg.body(f"📋 Aqui está o resumo da sua denúncia:\n\n{resumo}\n\nEstá correto?\n1️⃣ Sim\n2️⃣ Corrigir")

    elif step == "confirmar":
        if incoming_msg == "1":
            protocolo = str(uuid.uuid4())[:8].upper()
            session["dados"]["protocolo"] = protocolo
            session["step"] = "finalizado"

            # Salva no Supabase
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

            msg.body(f"✅ Sua denúncia foi registrada com sucesso!\n\n📌 Protocolo: *{protocolo}*\n\n"
                     "Guarde esse número para acompanhar o andamento. Basta enviá-lo aqui no chat para consultar.")
        elif incoming_msg == "2":
            session["step"] = "denuncia"
            msg.body("Ok, por favor, descreva novamente sua denúncia com as correções necessárias:")
        else:
            msg.body("⚠️ Resposta inválida. Digite 1 para Confirmar ou 2 para Corrigir.")

    elif step == "finalizado":
        # Consulta por protocolo
        if len(incoming_msg) == 8:  # supondo protocolo de 8 caracteres
            result = supabase.table("denuncias").select("*").eq("protocolo", incoming_msg).eq("telefone", from_number).execute()
            if result.data:
                denuncia = result.data[0]
                msg.body(f"📌 Detalhes da denúncia ({denuncia['protocolo']}):\n\n{denuncia['resumo']}")
            else:
                msg.body("❌ Protocolo não encontrado ou não pertence a este número de telefone.")
        else:
            msg.body("Sua denúncia já foi registrada. Caso queira consultar, informe seu número de protocolo.")

    else:
        msg.body("⚠️ Não entendi sua mensagem. Por favor, siga as instruções do fluxo.")

    return str(resp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)
