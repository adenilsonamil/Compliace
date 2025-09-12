import os
import logging
import secrets
import bcrypt
from flask import Flask, request
from twilio.rest import Client
from supabase import create_client, Client as SupabaseClient
from openai import OpenAI
from datetime import datetime

# ========================
# Configurações
# ========================
logging.basicConfig(level=logging.DEBUG)
app = Flask(__name__)

# Variáveis de ambiente
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")  # sem whatsapp: no .env
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Clientes
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Estados de conversa
conversas = {}

# ========================
# Funções auxiliares
# ========================
def send_message(to, body):
    """Enviar mensagem pelo WhatsApp via Twilio"""
    try:
        if not to.startswith("whatsapp:"):
            to = f"whatsapp:{to.replace('whatsapp:', '')}"

        from_number = TWILIO_PHONE_NUMBER
        if not from_number.startswith("whatsapp:"):
            from_number = f"whatsapp:{from_number.replace('whatsapp:', '')}"

        logging.debug(f"Enviando de {from_number} para {to}: {body}")
        twilio_client.messages.create(
            from_=from_number,
            to=to,
            body=body
        )
    except Exception as e:
        logging.error(f"Erro ao enviar mensagem WhatsApp: {e}")


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

    if sender not in conversas:
        conversas[sender] = {"dados": {}, "mensagens": []}
        send_message(
            sender,
            "👋 Olá! Bem-vindo ao *Canal de Denúncias de Compliance*.\n\n"
            "Você pode escrever livremente sua denúncia. Eu vou organizar as informações para você."
        )
        return "OK", 200

    conversa = conversas[sender]
    conversa["mensagens"].append({"role": "user", "content": body})

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Você é um atendente de ouvidoria de compliance, amigável e acolhedor.\n"
                        "Sua função é coletar informações de uma denúncia.\n"
                        "Pergunte de forma natural e humanizada, como se fosse um diálogo.\n\n"
                        "As informações que precisa coletar são:\n"
                        "- descricao\n- categoria\n- local\n- data_fato\n- envolvidos\n- testemunhas\n- impacto\n- evidencias\n\n"
                        "Regras:\n"
                        "- Corrija erros de português nas respostas do usuário.\n"
                        "- Pergunte apenas sobre o que ainda não foi respondido.\n"
                        "- Responda SEMPRE em JSON no formato:\n"
                        '{"mensagem": "texto amigável para o usuário", "campos": {...}}\n\n'
                        "No campo 'campos', devolva apenas o que conseguir extrair até agora."
                    ),
                }
            ]
            + conversa["mensagens"],
            max_tokens=400,
            response_format={"type": "json_object"},
        )

        resposta_json = response.choices[0].message.content
        logging.debug(f"Resposta IA: {resposta_json}")

        import json
        dados = json.loads(resposta_json)

        # Atualiza dados coletados
        if "campos" in dados:
            conversa["dados"].update(dados["campos"])

        # Responde ao usuário
        if "mensagem" in dados:
            send_message(sender, dados["mensagem"])

        # Se já temos os principais campos, salvar no Supabase
        campos_obrigatorios = ["descricao", "categoria", "local", "data_fato"]
        if all(k in conversa["dados"] for k in campos_obrigatorios):
            protocolo = gerar_protocolo()
            senha = gerar_senha()
            senha_hash = bcrypt.hashpw(senha.encode(), bcrypt.gensalt()).decode()

            conversa["dados"]["protocolo"] = protocolo
            conversa["dados"]["senha"] = senha_hash
            conversa["dados"]["status"] = "Recebida"
            conversa["dados"]["criado_em"] = datetime.utcnow().isoformat()

            try:
                supabase.table("denuncias").insert(conversa["dados"]).execute()
                resumo = (
                    "📋 Resumo da denúncia:\n\n"
                    f"📝 {conversa['dados'].get('descricao','')}\n"
                    f"📌 Categoria: {conversa['dados'].get('categoria','')}\n"
                    f"📍 Local: {conversa['dados'].get('local','')}\n"
                    f"🗓️ Data: {conversa['dados'].get('data_fato','')}\n\n"
                    f"✅ Sua denúncia foi registrada.\n"
                    f"📌 Protocolo: {protocolo}\n"
                    f"🔑 Senha: {senha}"
                )
                send_message(sender, resumo)
                del conversas[sender]
            except Exception as e:
                logging.error(f"Erro ao salvar denúncia: {e}")
                send_message(sender, "⚠️ Ocorreu um erro ao salvar sua denúncia. Tente novamente.")

    except Exception as e:
        logging.error(f"Erro IA: {e}")
        send_message(sender, "⚠️ Ocorreu um erro no atendimento. Tente novamente.")

    return "OK", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
