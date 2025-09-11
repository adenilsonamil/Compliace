import os
import logging
import secrets
import bcrypt
from flask import Flask, request
from twilio.rest import Client
from supabase import create_client, Client as SupabaseClient
import openai
from datetime import datetime

# ========================
# Configurações
# ========================
logging.basicConfig(level=logging.DEBUG)
app = Flask(__name__)

# Variáveis de ambiente
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Clientes
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
openai.api_key = OPENAI_API_KEY

# Estados de conversa
conversas = {}

# ========================
# Funções auxiliares
# ========================
def enviar_mensagem(to, body):
    logging.debug(f"Enviando para {to}: {body}")
    twilio_client.messages.create(
        from_=f"whatsapp:{TWILIO_WHATSAPP_NUMBER}",
        to=to,
        body=body
    )

def corrigir_texto(texto: str) -> str:
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Você é um assistente de revisão de texto. Corrija apenas ortografia e gramática, sem mudar o sentido."},
                {"role": "user", "content": texto}
            ]
        )
        return response.choices[0].message["content"].strip()
    except Exception as e:
        logging.error(f"Erro ao corrigir texto: {e}")
        return texto

def gerar_protocolo():
    return secrets.token_hex(4)  # Ex: a1b2c3d4

def gerar_senha():
    return secrets.token_urlsafe(6)  # Ex: F9dX2L

# ========================
# Fluxo principal
# ========================
@app.route("/webhook", methods=["POST"])
def webhook():
    sender = request.form.get("From")
    body = request.form.get("Body", "").strip()
    midia_url = request.form.get("MediaUrl0")

    if sender not in conversas:
        conversas[sender] = {"etapa": "menu", "dados": {}, "midias": []}

    conversa = conversas[sender]

    # Se receber mídia
    if midia_url:
        conversa["midias"].append(midia_url)
        enviar_mensagem(sender, "✅ Evidência recebida.")
        return "OK", 200

    # Fluxo de etapas
    if conversa["etapa"] == "menu":
        msg = (
            "👋 Olá! Bem-vindo ao Canal de Denúncias de Compliance.\n\n"
            "Escolha uma opção:\n"
            "1️⃣ Fazer denúncia *anônima*\n"
            "2️⃣ Fazer denúncia *identificada*\n"
            "3️⃣ Consultar protocolo existente\n"
            "4️⃣ Encerrar atendimento"
        )
        enviar_mensagem(sender, msg)
        conversa["etapa"] = "escolha"
        return "OK", 200

    # ======================
    # CONSULTA DE PROTOCOLO
    # ======================
    if conversa["etapa"] == "escolha" and body == "3":
        enviar_mensagem(sender, "🔎 Digite seu protocolo:")
        conversa["etapa"] = "consulta_protocolo"
        return "OK", 200

    if conversa["etapa"] == "consulta_protocolo":
        conversa["dados"]["protocolo"] = body
        enviar_mensagem(sender, "🔑 Agora digite sua senha:")
        conversa["etapa"] = "consulta_senha"
        return "OK", 200

    if conversa["etapa"] == "consulta_senha":
        protocolo = conversa["dados"]["protocolo"]
        senha = body
        try:
            result = supabase.table("denuncias").select("*").eq("protocolo", protocolo).execute()
            if result.data:
                denuncia = result.data[0]
                senha_hash = denuncia.get("senha")
                if senha_hash and bcrypt.checkpw(senha.encode(), senha_hash.encode()):
                    resumo = (
                        f"📌 Protocolo: {protocolo}\n"
                        f"📊 Status: {denuncia.get('status','Não informado')}\n"
                        f"📝 Denúncia: {denuncia.get('denuncia','')[:100]}..."
                    )
                    enviar_mensagem(sender, resumo)
                else:
                    enviar_mensagem(sender, "❌ Protocolo ou senha inválidos.")
            else:
                enviar_mensagem(sender, "❌ Protocolo não encontrado.")
        except Exception as e:
            logging.error(f"Erro consulta protocolo: {e}")
            enviar_mensagem(sender, "⚠️ Erro ao consultar protocolo.")
        conversa["etapa"] = "menu"
        return "OK", 200

    # ======================
    # OPÇÃO ANÔNIMA/IDENTIFICADA
    # ======================
    if conversa["etapa"] == "escolha" and body in ["1", "2"]:
        conversa["dados"]["anonimo"] = (body == "1")
        enviar_mensagem(sender, "✍️ Por favor, descreva sua denúncia:")
        conversa["etapa"] = "denuncia"
        return "OK", 200

    if conversa["etapa"] == "denuncia":
        conversa["dados"]["denuncia"] = corrigir_texto(body)
        enviar_mensagem(sender, "🗓️ Quando o fato ocorreu?")
        conversa["etapa"] = "data_fato"
        return "OK", 200

    if conversa["etapa"] == "data_fato":
        conversa["dados"]["data_fato"] = corrigir_texto(body)
        enviar_mensagem(sender, "📍 Onde aconteceu o fato?")
        conversa["etapa"] = "local"
        return "OK", 200

    if conversa["etapa"] == "local":
        conversa["dados"]["local"] = corrigir_texto(body)
        enviar_mensagem(sender, "👥 Quem estava envolvido?")
        conversa["etapa"] = "envolvidos"
        return "OK", 200

    if conversa["etapa"] == "envolvidos":
        conversa["dados"]["envolvidos"] = corrigir_texto(body)
        enviar_mensagem(sender, "👀 Havia testemunhas?")
        conversa["etapa"] = "testemunhas"
        return "OK", 200

    if conversa["etapa"] == "testemunhas":
        conversa["dados"]["testemunhas"] = corrigir_texto(body)
        enviar_mensagem(sender, "📎 Você possui evidências? (Digite 'sim' ou 'não')")
        conversa["etapa"] = "evidencias"
        return "OK", 200

    if conversa["etapa"] == "evidencias":
        if body.lower() in ["sim", "s"]:
            enviar_mensagem(sender, "Deseja anexar agora?\nDigite 1️⃣ para enviar\nDigite 2️⃣ para prosseguir sem anexar")
            conversa["etapa"] = "anexar_evidencias"
        else:
            enviar_mensagem(sender, "🔄 Esse fato ocorreu apenas uma vez ou é recorrente?")
            conversa["etapa"] = "frequencia"
        return "OK", 200

    if conversa["etapa"] == "anexar_evidencias":
        if body == "1":
            enviar_mensagem(sender, "📤 Envie os arquivos (fotos, vídeos ou documentos).")
            conversa["etapa"] = "receber_midias"
        else:
            enviar_mensagem(sender, "🔄 Esse fato ocorreu apenas uma vez ou é recorrente?")
            conversa["etapa"] = "frequencia"
        return "OK", 200

    if conversa["etapa"] == "receber_midias":
        enviar_mensagem(sender, "✅ Evidências anexadas.\n🔄 Esse fato ocorreu apenas uma vez ou é recorrente?")
        conversa["etapa"] = "frequencia"
        return "OK", 200

    if conversa["etapa"] == "frequencia":
        conversa["dados"]["frequencia"] = corrigir_texto(body)
        enviar_mensagem(sender, "⚖️ Qual o impacto ou gravidade do ocorrido?")
        conversa["etapa"] = "impacto"
        return "OK", 200

    if conversa["etapa"] == "impacto":
        conversa["dados"]["impacto"] = corrigir_texto(body)

        protocolo = gerar_protocolo()
        senha = gerar_senha()
        senha_hash = bcrypt.hashpw(senha.encode(), bcrypt.gensalt()).decode()

        conversa["dados"]["protocolo"] = protocolo
        conversa["dados"]["senha"] = senha_hash
        conversa["dados"]["status"] = "Recebida"
        conversa["dados"]["midias"] = conversa["midias"]

        # Salvar no Supabase
        try:
            supabase.table("denuncias").insert(conversa["dados"]).execute()
        except Exception as e:
            logging.error(f"Erro ao salvar no Supabase: {e}")

        resumo = (
            "📋 Resumo da denúncia:\n\n"
            f"👤 Tipo: {'Anônima' if conversa['dados']['anonimo'] else 'Identificada'}\n"
            f"📝 Descrição: {conversa['dados']['denuncia']}\n"
            f"🗓️ Data: {conversa['dados']['data_fato']}\n"
            f"📍 Local: {conversa['dados']['local']}\n"
            f"👥 Envolvidos: {conversa['dados']['envolvidos']}\n"
            f"👀 Testemunhas: {conversa['dados']['testemunhas']}\n"
            f"📎 Evidências: {'Anexadas' if conversa['midias'] else 'Não'}\n"
            f"🔄 Frequência: {conversa['dados']['frequencia']}\n"
            f"⚖️ Impacto: {conversa['dados']['impacto']}\n\n"
            f"✅ Sua denúncia foi registrada.\n"
            f"📌 Protocolo: {protocolo}\n"
            f"🔑 Senha: {senha}"
        )
        enviar_mensagem(sender, resumo)
        conversa["etapa"] = "menu"
        return "OK", 200

    # ======================
    # ENCERRAR
    # ======================
    if conversa["etapa"] == "escolha" and body == "4":
        enviar_mensagem(sender, "👋 Atendimento encerrado. Obrigado.")
        del conversas[sender]
        return "OK", 200

    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
