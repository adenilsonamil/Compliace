import os
import logging
import secrets
import bcrypt
import json
from flask import Flask, request
from twilio.rest import Client
from supabase import create_client, Client as SupabaseClient
from datetime import datetime
import openai

# ========================
# Configurações
# ========================
logging.basicConfig(level=logging.DEBUG)
app = Flask(__name__)

# Variáveis de ambiente obrigatórias
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")  # já no formato +1415...
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER,
            SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, OPENAI_API_KEY]):
    raise ValueError("❌ Variáveis de ambiente não configuradas corretamente.")

# Clientes externos
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
openai.api_key = OPENAI_API_KEY

# Estados de conversa
conversas = {}

# ========================
# Funções auxiliares
# ========================
def enviar_mensagem(to, body):
    try:
        logging.debug(f"Enviando para whatsapp:{to}: {body}")
        twilio_client.messages.create(
            from_=f"whatsapp:{TWILIO_PHONE_NUMBER}",
            to=to,
            body=body
        )
    except Exception as e:
        logging.error(f"Erro ao enviar mensagem WhatsApp: {e}")

def interpretar_resposta(pergunta: str, resposta: str) -> dict:
    """
    Usa IA para corrigir e interpretar a resposta do usuário.
    Retorna texto corrigido + insights (categoria, gravidade, envolvidos, etc.).
    """
    try:
        resp = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Você é um assistente de compliance acolhedor. Corrija erros de português e extraia insights (categoria, gravidade, envolvidos, local). Responda em JSON."},
                {"role": "user", "content": f"Pergunta: {pergunta}\nResposta: {resposta}"}
            ],
            max_tokens=200,
            response_format="json"
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        logging.error(f"Erro interpretar_resposta: {e}")
        return {"texto_corrigido": resposta}

def gerar_protocolo():
    return secrets.token_hex(4)

def gerar_senha():
    return secrets.token_urlsafe(6)

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

    # Tratamento de mídia
    if midia_url:
        conversa["midias"].append(midia_url)
        enviar_mensagem(sender, "📎 Evidência recebida com sucesso.")
        return "OK", 200

    # ======================
    # MENU INICIAL
    # ======================
    if conversa["etapa"] == "menu":
        msg = (
            "👋 Olá! Bem-vindo ao *Canal de Denúncias de Compliance*.\n\n"
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
    # OPÇÃO DENÚNCIA
    # ======================
    if conversa["etapa"] == "escolha" and body in ["1", "2"]:
        conversa["dados"]["anonimo"] = (body == "1")
        enviar_mensagem(sender, "✍️ Pode me contar com suas palavras o que aconteceu?")
        conversa["etapa"] = "denuncia"
        return "OK", 200

    if conversa["etapa"] == "denuncia":
        result = interpretar_resposta("Descrição da denúncia", body)
        conversa["dados"]["denuncia"] = result.get("texto_corrigido", body)
        conversa["dados"]["categoria"] = result.get("categoria")
        enviar_mensagem(sender, "🗓️ Quando o fato ocorreu?")
        conversa["etapa"] = "data_fato"
        return "OK", 200

    if conversa["etapa"] == "data_fato":
        result = interpretar_resposta("Data do fato", body)
        conversa["dados"]["data_fato"] = result.get("texto_corrigido", body)
        enviar_mensagem(sender, "📍 Onde aconteceu?")
        conversa["etapa"] = "local"
        return "OK", 200

    if conversa["etapa"] == "local":
        result = interpretar_resposta("Local do fato", body)
        conversa["dados"]["local"] = result.get("texto_corrigido", body)
        enviar_mensagem(sender, "👥 Quem estava envolvido?")
        conversa["etapa"] = "envolvidos"
        return "OK", 200

    if conversa["etapa"] == "envolvidos":
        result = interpretar_resposta("Envolvidos", body)
        conversa["dados"]["envolvidos"] = result.get("texto_corrigido", body)
        enviar_mensagem(sender, "👀 Alguém presenciou o ocorrido?")
        conversa["etapa"] = "testemunhas"
        return "OK", 200

    if conversa["etapa"] == "testemunhas":
        result = interpretar_resposta("Testemunhas", body)
        conversa["dados"]["testemunhas"] = result.get("texto_corrigido", body)
        enviar_mensagem(sender, "📎 Você possui evidências? Digite 'sim' ou 'não'.")
        conversa["etapa"] = "evidencias"
        return "OK", 200

    if conversa["etapa"] == "evidencias":
        if body.lower() in ["sim", "s"]:
            enviar_mensagem(sender, "📤 Pode enviar as evidências (fotos, vídeos ou documentos).")
            conversa["etapa"] = "receber_midias"
        else:
            enviar_mensagem(sender, "⚖️ Como você descreveria a gravidade do ocorrido? (leve, moderada, grave)")
            conversa["etapa"] = "impacto"
        return "OK", 200

    if conversa["etapa"] == "receber_midias":
        enviar_mensagem(sender, "✅ Evidências anexadas.\n⚖️ Como você descreveria a gravidade do ocorrido?")
        conversa["etapa"] = "impacto"
        return "OK", 200

    if conversa["etapa"] == "impacto":
        result = interpretar_resposta("Impacto ou gravidade", body)
        conversa["dados"]["impacto"] = result.get("texto_corrigido", body)

        # gerar credenciais
        protocolo = gerar_protocolo()
        senha = gerar_senha()
        senha_hash = bcrypt.hashpw(senha.encode(), bcrypt.gensalt()).decode()

        conversa["dados"]["protocolo"] = protocolo
        conversa["dados"]["senha"] = senha_hash
        conversa["dados"]["status"] = "Recebida"
        conversa["dados"]["midias"] = conversa["midias"]

        # salvar no supabase
        try:
            supabase.table("denuncias").insert(conversa["dados"]).execute()
        except Exception as e:
            logging.error(f"Erro salvar denuncia: {e}")

        resumo = (
            f"📋 Obrigado por confiar em nosso canal.\n\n"
            f"👤 Tipo: {'Anônima' if conversa['dados']['anonimo'] else 'Identificada'}\n"
            f"📂 Categoria interpretada: {conversa['dados'].get('categoria','Não definida')}\n"
            f"📝 Relato: {conversa['dados']['denuncia']}\n"
            f"🗓️ Data: {conversa['dados']['data_fato']}\n"
            f"📍 Local: {conversa['dados']['local']}\n"
            f"👥 Envolvidos: {conversa['dados']['envolvidos']}\n"
            f"👀 Testemunhas: {conversa['dados']['testemunhas']}\n"
            f"📎 Evidências: {'Sim' if conversa['midias'] else 'Não'}\n"
            f"⚖️ Gravidade: {conversa['dados']['impacto']}\n\n"
            f"✅ Sua denúncia foi registrada.\n"
            f"📌 Protocolo: {protocolo}\n"
            f"🔑 Senha: {senha}\n\n"
            f"🚨 Nossa equipe de compliance irá analisar com cuidado."
        )
        enviar_mensagem(sender, resumo)
        conversa["etapa"] = "menu"
        return "OK", 200

    # ENCERRAR
    if conversa["etapa"] == "escolha" and body == "4":
        enviar_mensagem(sender, "👋 Atendimento encerrado. Obrigado.")
        del conversas[sender]
        return "OK", 200

    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
