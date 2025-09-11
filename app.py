import os
import logging
import random
import string
from flask import Flask, request
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from supabase import create_client, Client as SupabaseClient
from openai import OpenAI

# --------------------------------------------------------
# Configurações
# --------------------------------------------------------
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)

# Twilio
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_KEY)

# OpenAI
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Memória simples em memória RAM
sessions = {}

# --------------------------------------------------------
# Funções auxiliares
# --------------------------------------------------------
def gerar_protocolo():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def gerar_senha():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=6))

def enviar_whatsapp(to, body):
    """Envia mensagem WhatsApp via Twilio"""
    try:
        twilio_client.messages.create(
            from_=f"whatsapp:{TWILIO_PHONE_NUMBER}",
            to=f"whatsapp:{to}",
            body=body
        )
        logging.debug(f"Enviando para whatsapp:{to}: {body}")
    except Exception as e:
        logging.error(f"Erro ao enviar mensagem WhatsApp: {e}")

def interpretar_resposta(user_id, texto):
    """Envia texto do usuário para a IA e interpreta em JSON"""
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Você é um assistente de compliance acolhedor. "
                        "Corrija erros de português e extraia insights da denúncia. "
                        "Responda em JSON estruturado com campos: descricao, categoria, local, "
                        "data_fato, envolvidos, testemunhas, impacto, evidencias."
                    )
                },
                {"role": "user", "content": texto}
            ],
            max_tokens=400,
            response_format={"type": "json_object"}
        )
        return response.choices[0].message.content
    except Exception as e:
        logging.error(f"Erro interpretar_resposta: {e}")
        return None

def salvar_denuncia(dados, anonimo=True):
    """Salva a denúncia no Supabase"""
    protocolo = gerar_protocolo()
    senha = gerar_senha()

    try:
        supabase.table("denuncias").insert({
            "anonimo": anonimo,
            "descricao": dados.get("descricao"),
            "categoria": dados.get("categoria"),
            "local": dados.get("local"),
            "data_fato": dados.get("data_fato"),
            "envolvidos": ', '.join(dados.get("envolvidos", [])) if isinstance(dados.get("envolvidos"), list) else dados.get("envolvidos"),
            "testemunhas": ', '.join(dados.get("testemunhas", [])) if isinstance(dados.get("testemunhas"), list) else dados.get("testemunhas"),
            "impacto": dados.get("impacto"),
            "evidencias": dados.get("evidencias", []),
            "protocolo": protocolo,
            "senha": senha,
            "resumo": (
                f"Descrição: {dados.get('descricao')}\n"
                f"Categoria: {dados.get('categoria')}\n"
                f"Local: {dados.get('local')}\n"
                f"Data: {dados.get('data_fato')}\n"
                f"Envolvidos: {dados.get('envolvidos')}\n"
                f"Testemunhas: {dados.get('testemunhas')}\n"
                f"Impacto: {dados.get('impacto')}\n"
            )
        }).execute()

        return protocolo, senha
    except Exception as e:
        logging.error(f"Erro ao salvar denúncia: {e}")
        return None, None

# --------------------------------------------------------
# Webhook WhatsApp
# --------------------------------------------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    sender = request.form.get("From", "").replace("whatsapp:", "")
    body = request.form.get("Body", "").strip()
    resp = MessagingResponse()

    # Se é novo usuário
    if sender not in sessions:
        sessions[sender] = {"step": "inicio", "dados": {}}
        msg = (
            "👋 Olá! Bem-vindo ao *Canal de Denúncias de Compliance*.\n\n"
            "Você pode escrever livremente sua denúncia. Eu vou organizar as informações para você."
        )
        enviar_whatsapp(sender, msg)
        return str(resp)

    session = sessions[sender]

    # Interpretação pela IA
    interpretado = interpretar_resposta(sender, body)
    if interpretado:
        import json
        try:
            dados = json.loads(interpretado)
            session["dados"].update(dados)

            # Se já temos info suficiente
            if all(k in session["dados"] for k in ["descricao", "categoria", "local", "data_fato"]):
                protocolo, senha = salvar_denuncia(session["dados"], anonimo=True)
                if protocolo:
                    resumo = (
                        "✅ Sua denúncia foi registrada com sucesso.\n\n"
                        f"📋 Resumo:\n"
                        f"- Descrição: {session['dados'].get('descricao')}\n"
                        f"- Categoria: {session['dados'].get('categoria')}\n"
                        f"- Local: {session['dados'].get('local')}\n"
                        f"- Data: {session['dados'].get('data_fato')}\n"
                        f"- Envolvidos: {session['dados'].get('envolvidos')}\n"
                        f"- Testemunhas: {session['dados'].get('testemunhas')}\n"
                        f"- Impacto: {session['dados'].get('impacto')}\n\n"
                        f"🔐 Protocolo: {protocolo}\n"
                        f"🔑 Senha: {senha}\n\n"
                        "📌 Consulte o andamento em: https://ouvidoria.portocentrooeste.com.br"
                    )
                    enviar_whatsapp(sender, resumo)
                    sessions.pop(sender, None)  # finaliza sessão
                else:
                    enviar_whatsapp(sender, "⚠️ Ocorreu um erro ao salvar sua denúncia. Tente novamente.")
            else:
                # IA pede mais detalhes se algo estiver faltando
                if not session["dados"].get("data_fato"):
                    enviar_whatsapp(sender, "🗓️ Você poderia me dizer quando isso aconteceu?")
                elif not session["dados"].get("local"):
                    enviar_whatsapp(sender, "📍 Pode me informar onde ocorreu?")
                else:
                    enviar_whatsapp(sender, "✍️ Continue, pode me contar mais detalhes.")
        except Exception as e:
            logging.error(f"Erro processando JSON: {e}")
            enviar_whatsapp(sender, "⚠️ Não consegui entender bem. Pode reformular sua mensagem?")
    else:
        enviar_whatsapp(sender, "⚠️ Não consegui processar sua resposta. Pode repetir?")

    return str(resp)

# --------------------------------------------------------
# Start
# --------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
