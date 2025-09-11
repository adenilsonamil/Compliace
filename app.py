import os
import logging
import random
import string
from datetime import datetime

from flask import Flask, request
from twilio.rest import Client
from supabase import create_client, Client as SupabaseClient
from werkzeug.security import generate_password_hash, check_password_hash
import openai

# Configurações principais
app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)

# Twilio
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP = os.getenv("TWILIO_WHATSAPP")  # Ex: +14155238886
client_twilio = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_KEY)

# OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")

# Estados da conversa
user_states = {}

# ------------------------------
# Funções auxiliares
# ------------------------------
def enviar_whatsapp(destino, mensagem):
    """Envia mensagem via WhatsApp API do Twilio"""
    numero_formatado = destino if destino.startswith("whatsapp:") else f"whatsapp:{destino}"
    logging.debug(f"Enviando para {numero_formatado}: {mensagem}")
    client_twilio.messages.create(
        from_=f"whatsapp:{TWILIO_WHATSAPP}",
        body=mensagem,
        to=numero_formatado,   # ✅ garante que sempre tenha prefixo whatsapp:
    )

def corrigir_texto(texto):
    """Usa OpenAI para corrigir ortografia e gramática"""
    try:
        resposta = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Você é um assistente de revisão de texto. Corrija apenas ortografia e gramática, sem mudar o sentido."},
                {"role": "user", "content": texto},
            ],
        )
        return resposta.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"Erro ao corrigir texto: {e}")
        return texto

def gerar_protocolo():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))

def gerar_senha():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=10))

# ------------------------------
# Fluxo inicial
# ------------------------------
def iniciar_atendimento(user_number):
    user_states[user_number] = {"step": "inicio", "dados": {}}
    msg = (
        "👋 Olá! Bem-vindo ao Canal de Denúncias de Compliance.\n\n"
        "Escolha uma opção:\n"
        "1️⃣ Fazer denúncia *anônima*\n"
        "2️⃣ Fazer denúncia *identificada*\n"
        "3️⃣ Consultar protocolo existente\n"
        "4️⃣ Encerrar atendimento"
    )
    enviar_whatsapp(user_number, msg)

# ------------------------------
# Webhook principal
# ------------------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    user_number = request.form.get("From").replace("whatsapp:", "")  # 🔹 mantemos só número aqui
    incoming_msg = request.form.get("Body").strip()
    estado = user_states.get(user_number, {"step": "inicio", "dados": {}})

    # Encerrar
    if incoming_msg == "4":
        enviar_whatsapp(user_number, "✅ Atendimento encerrado. Obrigado por utilizar nosso canal.")
        user_states.pop(user_number, None)
        return "OK", 200

    # Início
    if estado["step"] == "inicio":
        if incoming_msg == "1":
            estado["dados"]["anonimo"] = True
            estado["step"] = "descricao"
            enviar_whatsapp(user_number, "✍️ Por favor, descreva sua denúncia:")
        elif incoming_msg == "2":
            estado["dados"]["anonimo"] = False
            estado["step"] = "nome"
            enviar_whatsapp(user_number, "👤 Informe seu nome completo:")
        elif incoming_msg == "3":
            estado["step"] = "consulta_protocolo"
            enviar_whatsapp(user_number, "🔎 Digite o protocolo da sua denúncia:")
        else:
            enviar_whatsapp(user_number, "⚠️ Opção inválida. Digite 1, 2, 3 ou 4.")
        user_states[user_number] = estado
        return "OK", 200

    # ==============================
    # Consulta de protocolo + senha
    # ==============================
    if estado["step"] == "consulta_protocolo":
        estado["dados"]["protocolo"] = incoming_msg
        estado["step"] = "consulta_senha"
        enviar_whatsapp(user_number, "🔑 Digite a senha associada ao protocolo:")
        user_states[user_number] = estado
        return "OK", 200

    if estado["step"] == "consulta_senha":
        protocolo = estado["dados"]["protocolo"]
        senha_digitada = incoming_msg
        try:
            result = supabase.table("denuncias").select("*").eq("protocolo", protocolo).execute()
            if result.data:
                denuncia = result.data[0]
                senha_hash = denuncia.get("senha")
                if senha_hash and check_password_hash(senha_hash, senha_digitada):
                    resposta = (
                        f"📋 Consulta da denúncia:\n"
                        f"📌 Protocolo: {protocolo}\n"
                        f"📊 Status: {denuncia.get('status','Em análise')}\n"
                        f"📝 Descrição: {denuncia.get('descricao','')[:120]}..."
                    )
                else:
                    resposta = "❌ Protocolo ou senha inválidos."
            else:
                resposta = "❌ Nenhuma denúncia encontrada com esse protocolo."
        except Exception as e:
            resposta = f"⚠️ Erro ao consultar denúncia: {e}"

        enviar_whatsapp(user_number, resposta)
        user_states.pop(user_number, None)
        return "OK", 200

    # Nome
    if estado["step"] == "nome":
        estado["dados"]["nome"] = corrigir_texto(incoming_msg)
        estado["step"] = "email"
        enviar_whatsapp(user_number, "📧 Informe seu e-mail:")
        user_states[user_number] = estado
        return "OK", 200

    # Email
    if estado["step"] == "email":
        estado["dados"]["email"] = incoming_msg
        estado["step"] = "telefone"
        enviar_whatsapp(user_number, "📞 Informe seu telefone:")
        user_states[user_number] = estado
        return "OK", 200

    # Telefone
    if estado["step"] == "telefone":
        estado["dados"]["telefone"] = incoming_msg
        estado["step"] = "descricao"
        enviar_whatsapp(user_number, "✍️ Por favor, descreva sua denúncia:")
        user_states[user_number] = estado
        return "OK", 200

    # Descrição
    if estado["step"] == "descricao":
        estado["dados"]["descricao"] = corrigir_texto(incoming_msg)
        estado["step"] = "confirmar"
        protocolo = gerar_protocolo()
        senha = gerar_senha()
        senha_hash = generate_password_hash(senha)

        estado["dados"]["protocolo"] = protocolo
        estado["dados"]["senha"] = senha_hash
        estado["dados"]["status"] = "Recebida"

        resumo = (
            f"📋 Resumo da denúncia:\n\n"
            f"👤 Tipo: {'Anônima' if estado['dados'].get('anonimo') else 'Identificada'}\n"
            f"📝 Descrição: {estado['dados'].get('descricao')}\n"
            f"\n✅ Se estas informações estão corretas:\n"
            f"Digite 1️⃣ para confirmar e registrar sua denúncia\n"
            f"Digite 2️⃣ para corrigir alguma informação\n"
            f"Digite 3️⃣ para cancelar."
        )
        enviar_whatsapp(user_number, resumo)
        estado["senha_plana"] = senha
        user_states[user_number] = estado
        return "OK", 200

    # Confirmação
    if estado["step"] == "confirmar":
        if incoming_msg == "1":
            dados = estado["dados"]
            try:
                supabase.table("denuncias").insert(dados).execute()
                enviar_whatsapp(
                    user_number,
                    f"✅ Sua denúncia foi registrada.\n📌 Protocolo: {dados['protocolo']}\n🔑 Senha: {estado['senha_plana']}"
                )
            except Exception as e:
                enviar_whatsapp(user_number, f"⚠️ Erro ao registrar denúncia: {e}")
        elif incoming_msg == "2":
            enviar_whatsapp(user_number, "🔄 Recomeçando o cadastro da denúncia.")
            iniciar_atendimento(user_number)
        else:
            enviar_whatsapp(user_number, "❌ Denúncia cancelada.")
        user_states.pop(user_number, None)
        return "OK", 200

    return "OK", 200

# ------------------------------
# Rota de teste
# ------------------------------
@app.route("/", methods=["GET"])
def home():
    return "Canal de Denúncias de Compliance ativo."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
