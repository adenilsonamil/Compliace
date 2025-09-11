import os
import json
import logging
from flask import Flask, request
from twilio.rest import Client
from openai import OpenAI

# Configuração básica de logs
logging.basicConfig(level=logging.DEBUG)

# Inicialização do Flask
app = Flask(__name__)

# Configuração Twilio e OpenAI
twilio_sid = os.getenv("TWILIO_ACCOUNT_SID")
twilio_auth = os.getenv("TWILIO_AUTH_TOKEN")
twilio_number = f"whatsapp:{os.getenv('TWILIO_PHONE_NUMBER')}"
openai_api_key = os.getenv("OPENAI_API_KEY")

twilio_client = Client(twilio_sid, twilio_auth)
client = OpenAI(api_key=openai_api_key)

# Estado das conversas em memória
conversas = {}

# Função para enviar mensagens via WhatsApp
def enviar_mensagem(para, corpo):
    try:
        logging.debug(f"Enviando para {para}: {corpo}")
        twilio_client.messages.create(
            from_=twilio_number,
            body=corpo,
            to=para
        )
    except Exception as e:
        logging.error(f"Erro ao enviar mensagem WhatsApp: {e}")

# Função para interpretar respostas usando OpenAI
def interpretar_resposta(pergunta, resposta):
    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Você é um assistente de compliance acolhedor. "
                        "Corrija erros de português e extraia insights (categoria, gravidade, envolvidos, local). "
                        "Responda em JSON."
                    )
                },
                {"role": "user", "content": f"Pergunta: {pergunta}\nResposta: {resposta}"}
            ],
            max_tokens=200,
            response_format={"type": "json_object"}  # ✅ correção aplicada
        )
        return json.loads(completion.choices[0].message.content)
    except Exception as e:
        logging.error(f"Erro interpretar_resposta: {e}")
        return {}

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.form
    sender = data.get("From")
    message = data.get("Body", "").strip()
    midia_url = data.get("MediaUrl0")

    if not sender:
        return "OK", 200

    if sender not in conversas:
        conversas[sender] = {"etapa": "inicio", "dados": {}, "midias": []}

    conversa = conversas[sender]

    # ✅ Correção: tratar mídia e avançar no fluxo
    if midia_url:
        conversa["midias"].append(midia_url)
        enviar_mensagem(sender, "📎 Evidência recebida com sucesso.")
        
        if conversa["etapa"] == "receber_midias":
            enviar_mensagem(sender, "⚖️ Como você descreveria a gravidade do ocorrido? (leve, moderada, grave)")
            conversa["etapa"] = "impacto"
        return "OK", 200

    etapa = conversa["etapa"]

    # Fluxo inicial
    if etapa == "inicio":
        menu = (
            "👋 Olá! Bem-vindo ao *Canal de Denúncias de Compliance*.\n\n"
            "Escolha uma opção:\n"
            "1️⃣ Fazer denúncia *anônima*\n"
            "2️⃣ Fazer denúncia *identificada*\n"
            "3️⃣ Consultar protocolo existente\n"
            "4️⃣ Encerrar atendimento"
        )
        enviar_mensagem(sender, menu)
        conversa["etapa"] = "menu"

    elif etapa == "menu":
        if message == "1":
            conversa["dados"]["tipo"] = "anônima"
            enviar_mensagem(sender, "✍️ Pode me contar com suas palavras o que aconteceu?")
            conversa["etapa"] = "descricao"
        elif message == "2":
            conversa["dados"]["tipo"] = "identificada"
            enviar_mensagem(sender, "Por favor, informe seu nome completo:")
            conversa["etapa"] = "nome"
        elif message == "3":
            enviar_mensagem(sender, "🔎 Informe o número do protocolo:")
            conversa["etapa"] = "consulta_protocolo"
        elif message == "4":
            enviar_mensagem(sender, "✅ Atendimento encerrado. Obrigado.")
            conversa["etapa"] = "fim"
        else:
            enviar_mensagem(sender, "❌ Opção inválida. Escolha 1, 2, 3 ou 4.")

    elif etapa == "nome":
        conversa["dados"]["nome"] = message
        enviar_mensagem(sender, "📧 Agora, informe seu e-mail para contato:")
        conversa["etapa"] = "email"

    elif etapa == "email":
        conversa["dados"]["email"] = message
        enviar_mensagem(sender, "✍️ Pode me contar com suas palavras o que aconteceu?")
        conversa["etapa"] = "descricao"

    elif etapa == "descricao":
        conversa["dados"]["descricao"] = message
        interpretar_resposta("Descrição da denúncia", message)
        enviar_mensagem(sender, "🗓️ Quando o fato ocorreu?")
        conversa["etapa"] = "data"

    elif etapa == "data":
        conversa["dados"]["data"] = message
        interpretar_resposta("Data do fato", message)
        enviar_mensagem(sender, "📍 Onde aconteceu?")
        conversa["etapa"] = "local"

    elif etapa == "local":
        conversa["dados"]["local"] = message
        interpretar_resposta("Local do fato", message)
        enviar_mensagem(sender, "👥 Quem estava envolvido?")
        conversa["etapa"] = "envolvidos"

    elif etapa == "envolvidos":
        conversa["dados"]["envolvidos"] = message
        interpretar_resposta("Envolvidos", message)
        enviar_mensagem(sender, "👀 Alguém presenciou o ocorrido?")
        conversa["etapa"] = "testemunhas"

    elif etapa == "testemunhas":
        conversa["dados"]["testemunhas"] = message
        interpretar_resposta("Testemunhas", message)
        enviar_mensagem(sender, "📎 Você possui evidências? Digite 'sim' ou 'não'.")
        conversa["etapa"] = "possui_midias"

    elif etapa == "possui_midias":
        if message.lower() in ["sim", "s", "yes"]:
            enviar_mensagem(sender, "📤 Pode enviar as evidências (fotos, vídeos ou documentos).")
            conversa["etapa"] = "receber_midias"
        else:
            enviar_mensagem(sender, "⚖️ Como você descreveria a gravidade do ocorrido? (leve, moderada, grave)")
            conversa["etapa"] = "impacto"

    elif etapa == "impacto":
        conversa["dados"]["impacto"] = message
        interpretar_resposta("Impacto", message)
        resumo = (
            "📋 *Resumo da Denúncia Coletada:*\n\n"
            f"👤 Tipo: {conversa['dados'].get('tipo')}\n"
            f"📝 Descrição: {conversa['dados'].get('descricao')}\n"
            f"📅 Data: {conversa['dados'].get('data')}\n"
            f"📍 Local: {conversa['dados'].get('local')}\n"
            f"👥 Envolvidos: {conversa['dados'].get('envolvidos')}\n"
            f"👀 Testemunhas: {conversa['dados'].get('testemunhas')}\n"
            f"⚖️ Impacto: {conversa['dados'].get('impacto')}\n"
            f"📎 Evidências: {len(conversa['midias'])} arquivo(s) recebido(s)"
        )
        enviar_mensagem(sender, resumo)
        enviar_mensagem(sender, "✅ Sua denúncia foi registrada com sucesso. Obrigado pela confiança.")
        conversa["etapa"] = "fim"

    elif etapa == "consulta_protocolo":
        enviar_mensagem(sender, f"🔎 Protocolo {message} não encontrado no momento.")
        conversa["etapa"] = "fim"

    return "OK", 200

# Executar no modo local
if __name__ == "__main__":
    app.run(port=5000, debug=True)
