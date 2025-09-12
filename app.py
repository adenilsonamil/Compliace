import os
import logging
import uuid
import json
from flask import Flask, request
from twilio.rest import Client
from openai import OpenAI
from supabase import create_client, Client as SupabaseClient

# ---------------------------
# Configurações
# ---------------------------
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)

# Twilio
twilio_sid = os.getenv("TWILIO_ACCOUNT_SID")
twilio_auth = os.getenv("TWILIO_AUTH_TOKEN")
twilio_phone = os.getenv("TWILIO_PHONE_NUMBER")  # já vem no formato "whatsapp:+1415..."
twilio_client = Client(twilio_sid, twilio_auth)

# OpenAI
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Supabase
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase: SupabaseClient = create_client(supabase_url, supabase_key)

# Sessões de conversa em memória
sessions = {}

# Prompt humanizado
SYSTEM_PROMPT = """
Você é um atendente de ouvidoria de compliance, acolhedor, educado e humanizado.  
Converse como se fosse um atendente no WhatsApp, usando frases curtas, tom amigável e alguns emojis.

Objetivo: coletar informações da denúncia.

Campos a coletar:
- descricao
- categoria
- local
- data_fato
- envolvidos
- testemunhas
- impacto
- evidencias

Regras:
- Corrija erros de português sem chamar atenção para isso.
- Pergunte apenas sobre os campos que ainda não foram respondidos.
- Quando receber uma resposta, organize em JSON.

Responda SEMPRE no formato:
{
  "mensagem": "texto amigável para o usuário (com tom humano e emojis)",
  "campos": {
    "descricao": "...",
    "categoria": "...",
    "local": "...",
    "data_fato": "...",
    "envolvidos": "...",
    "testemunhas": "...",
    "impacto": "...",
    "evidencias": "..."
  }
}

Dicas de tom:
- Use acolhimento: "Entendi 👍", "Pode me contar um pouco mais?", "Obrigada pela confiança 🙏"
- Evite ser muito robótico.
"""

# ---------------------------
# Funções auxiliares
# ---------------------------

def send_message(to, body):
    """Enviar mensagem pelo WhatsApp via Twilio"""
    try:
        logging.debug(f"Enviando para {to}: {body}")
        twilio_client.messages.create(
            from_=twilio_phone,
            to=to,
            body=body
        )
    except Exception as e:
        logging.error(f"Erro ao enviar mensagem WhatsApp: {e}")


def ask_openai(session_id, user_input):
    """Enviar mensagem para a IA e retornar resposta estruturada"""
    messages = sessions[session_id]["messages"]
    messages.append({"role": "user", "content": user_input})

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=400,
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content
        logging.debug(f"Resposta IA: {content}")
        data = json.loads(content)
        return data
    except Exception as e:
        logging.error(f"Erro IA: {e}")
        return {"mensagem": "⚠️ Não consegui entender bem. Pode repetir?", "campos": {}}


def salvar_denuncia(campos):
    """Salvar denúncia no Supabase"""
    try:
        protocolo = str(uuid.uuid4())[:8].upper()
        senha = str(uuid.uuid4())[:6]

        data = {
            "protocolo": protocolo,
            "senha": senha,
            "descricao": campos.get("descricao"),
            "categoria": campos.get("categoria"),
            "local": campos.get("local"),
            "data_fato": campos.get("data_fato"),
            "envolvidos": campos.get("envolvidos"),
            "testemunhas": campos.get("testemunhas"),
            "impacto": campos.get("impacto"),
            "evidencias": campos.get("evidencias"),
        }

        supabase.table("denuncias").insert(data).execute()
        return protocolo, senha
    except Exception as e:
        logging.error(f"Erro ao salvar denúncia: {e}")
        return None, None


# ---------------------------
# Webhook do WhatsApp
# ---------------------------

@app.route("/webhook", methods=["POST"])
def webhook():
    from_number = request.form.get("From")
    user_input = request.form.get("Body")

    if from_number not in sessions:
        # Nova sessão
        sessions[from_number] = {
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}],
            "campos": {}
        }
        send_message(from_number, "👋 Olá! Bem-vindo ao *Canal de Denúncias de Compliance*.\n\nVocê pode escrever livremente sua denúncia. Eu vou organizar as informações para você 📋.")
        return "OK", 200

    session = sessions[from_number]

    # Processar resposta do usuário
    ia_response = ask_openai(from_number, f"Resposta do usuário: {user_input}")
    mensagem = ia_response.get("mensagem", "")
    novos_campos = ia_response.get("campos", {})

    # Atualizar campos coletados
    session["campos"].update({k: v for k, v in novos_campos.items() if v})

    # Verificar se todos os campos obrigatórios foram preenchidos
    obrigatorios = ["descricao", "categoria", "local", "data_fato", "envolvidos"]
    faltando = [c for c in obrigatorios if not session["campos"].get(c)]

    if not faltando:
        # Finalizar denúncia
        protocolo, senha = salvar_denuncia(session["campos"])
        if protocolo:
            resumo = "\n".join([f"• {k.capitalize()}: {v}" for k, v in session["campos"].items() if v])
            msg_final = f"""✅ Sua denúncia foi registrada com sucesso!

📌 *Protocolo:* {protocolo}  
🔑 *Senha:* {senha}  

📝 *Resumo:*  
{resumo}

🔍 Você pode consultar em: https://ouvidoria.portocentroooeste.com.br  

🙏 Obrigado pela confiança. Sua mensagem é muito importante!
"""
            send_message(from_number, msg_final)
            del sessions[from_number]
            return "OK", 200
        else:
            send_message(from_number, "⚠️ Ocorreu um erro ao salvar sua denúncia. Tente novamente.")
            return "OK", 200

    # Continuar conversa
    send_message(from_number, mensagem)
    return "OK", 200


# ---------------------------
# Início
# ---------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
