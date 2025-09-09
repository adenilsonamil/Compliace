import os
import uuid
import secrets
import string
import logging
from flask import Flask, request
from twilio.rest import Client
from supabase import create_client, Client as SupabaseClient

# Configurações de log
logging.basicConfig(level=logging.DEBUG)

# Inicialização
app = Flask(__name__)

# Variáveis de ambiente
TWILIO_NUMBER = f"whatsapp:{os.getenv('TWILIO_NUMBER')}"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

supabase: SupabaseClient = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

twilio_client = Client(
    os.getenv("TWILIO_ACCOUNT_SID"),
    os.getenv("TWILIO_AUTH_TOKEN")
)

# Estados da conversa
user_states = {}

# Função para enviar mensagens
def send_message(to, body):
    logging.debug(f"Enviando para {to}: {body}")
    twilio_client.messages.create(
        from_=TWILIO_NUMBER,
        to=to,
        body=body
    )

# Gerador de senha aleatória
def gerar_senha(tamanho=8):
    caracteres = string.ascii_letters + string.digits + "!@#$%&*"
    return ''.join(secrets.choice(caracteres) for _ in range(tamanho))

# Fluxo inicial
def menu_inicial(to):
    msg = (
        "👋 Olá! Bem-vindo ao Canal de Denúncias de Compliance.\n\n"
        "Escolha uma opção:\n"
        "1️⃣ Fazer denúncia *anônima*\n"
        "2️⃣ Fazer denúncia *identificada*\n"
        "3️⃣ Consultar protocolo existente\n"
        "4️⃣ Encerrar atendimento"
    )
    send_message(to, msg)
    user_states[to] = {"step": "menu"}

# Webhook do WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    from_number = request.form.get("From")
    body = request.form.get("Body", "").strip()
    logging.debug(f"Mensagem recebida de {from_number}: {body}")

    state = user_states.get(from_number, {"step": "menu"})

    # === Menu inicial ===
    if state["step"] == "menu":
        if body == "1":
            user_states[from_number] = {"step": "denuncia_anonima"}
            send_message(from_number, "📝 Por favor, descreva sua denúncia (anônima):")
        elif body == "2":
            user_states[from_number] = {"step": "denuncia_identificada", "dados": {}}
            send_message(from_number, "👤 Informe seu nome completo:")
        elif body == "3":
            user_states[from_number] = {"step": "consulta_protocolo"}
            send_message(from_number, "📄 Informe o número do protocolo que deseja consultar:")
        elif body == "4":
            send_message(from_number, "✅ Atendimento encerrado. Digite qualquer mensagem para começar de novo.")
            user_states[from_number] = {"step": "menu"}
        else:
            menu_inicial(from_number)

    # === Fluxo de denúncia anônima ===
    elif state["step"] == "denuncia_anonima":
        protocolo = str(uuid.uuid4())[:8]
        senha = gerar_senha()

        supabase.table("denuncias").insert({
            "protocolo": protocolo,
            "senha": senha,
            "descricao": body,
            "tipo": "anonima",
            "status": "Em análise"
        }).execute()

        send_message(from_number, (
            "📄 Sua denúncia anônima foi registrada com sucesso.\n\n"
            f"🔑 Protocolo: {protocolo}\n"
            f"🔐 Senha: {senha}\n\n"
            "Guarde essas informações para consultar o andamento."
        ))
        menu_inicial(from_number)

    # === Fluxo de denúncia identificada ===
    elif state["step"] == "denuncia_identificada":
        dados = state.get("dados", {})
        if "nome" not in dados:
            dados["nome"] = body
            state["dados"] = dados
            user_states[from_number] = state
            send_message(from_number, "📧 Informe seu e-mail de contato:")
        elif "email" not in dados:
            dados["email"] = body
            state["dados"] = dados
            user_states[from_number] = state
            send_message(from_number, "📝 Por favor, descreva sua denúncia:")
        else:
            protocolo = str(uuid.uuid4())[:8]
            senha = gerar_senha()

            supabase.table("denuncias").insert({
                "protocolo": protocolo,
                "senha": senha,
                "descricao": body,
                "tipo": "identificada",
                "status": "Em análise",
                "nome": dados["nome"],
                "email": dados["email"]
            }).execute()

            send_message(from_number, (
                "📄 Sua denúncia identificada foi registrada com sucesso.\n\n"
                f"🔑 Protocolo: {protocolo}\n"
                f"🔐 Senha: {senha}\n\n"
                "Guarde essas informações para consultar o andamento."
            ))
            menu_inicial(from_number)

    # === Consulta de protocolo ===
    elif state["step"] == "consulta_protocolo":
        state["protocolo"] = body
        user_states[from_number] = {"step": "consulta_senha", "protocolo": body}
        send_message(from_number, "🔐 Informe a senha do protocolo:")

    elif state["step"] == "consulta_senha":
        protocolo = state.get("protocolo")
        senha = body

        result = supabase.table("denuncias").select("*").eq("protocolo", protocolo).eq("senha", senha).execute()

        if result.data:
            denuncia = result.data[0]
            send_message(from_number, (
                f"📄 Protocolo: {denuncia['protocolo']}\n"
                f"🔐 Senha: {denuncia['senha']}\n"
                f"📌 Status: {denuncia['status']}\n"
                f"📝 Denúncia: {denuncia['descricao']}"
            ))
        else:
            send_message(from_number, "⚠️ Nenhum protocolo encontrado com essas credenciais.")

        menu_inicial(from_number)

    else:
        menu_inicial(from_number)

    return "OK", 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
