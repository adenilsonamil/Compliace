import os
import uuid
import datetime
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from supabase import create_client, Client
from openai import OpenAI

# Configurações
app = Flask(__name__)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Sessões em memória
sessions = {}
TIMEOUT_MINUTES = 5

def reset_session(user):
    if user in sessions:
        del sessions[user]

def generate_protocol():
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S-") + str(uuid.uuid4())[:6]

def summarize_text(text):
    try:
        resp = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Resuma a denúncia de forma clara e coerente."},
                {"role": "user", "content": text}
            ]
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"Erro ao resumir: {e}")
        return text

@app.route("/webhook", methods=["POST"])
def webhook():
    sender = request.form.get("From", "")
    user = sender.replace("whatsapp:", "")
    msg = request.form.get("Body", "").strip()
    resp = MessagingResponse()

    print(f"[DEBUG] Mensagem recebida de {user}: {msg}")

    # Início da sessão ou timeout
    if user not in sessions or (
        datetime.datetime.now() - sessions[user].get("last_active", datetime.datetime.now())
    ).seconds > TIMEOUT_MINUTES * 60:
        reset_session(user)
        sessions[user] = {"stage": "menu", "last_active": datetime.datetime.now()}
        resp.message(
            "👋 Olá! Bem-vindo ao Canal de Compliance.\n\n"
            "Escolha uma opção:\n"
            "1️⃣ Denúncia anônima\n"
            "2️⃣ Denúncia identificada\n"
            "3️⃣ Consultar protocolo\n"
            "4️⃣ Encerrar atendimento"
        )
        return str(resp)

    stage = sessions[user]["stage"]
    sessions[user]["last_active"] = datetime.datetime.now()

    # Fluxo de menu principal
    if stage == "menu":
        if msg == "1":
            sessions[user]["stage"] = "denuncia_anonima"
            resp.message("📝 Digite sua denúncia anônima:")
        elif msg == "2":
            sessions[user]["stage"] = "identificacao_nome"
            resp.message("👤 Digite seu nome completo:")
        elif msg == "3":
            sessions[user]["stage"] = "consulta_protocolo"
            resp.message("🔎 Informe o número do protocolo que deseja consultar:")
        elif msg == "4":
            reset_session(user)
            resp.message("✅ Atendimento encerrado. Envie qualquer mensagem para começar novamente.")
        else:
            resp.message("❌ Opção inválida. Escolha:\n1️⃣ Denúncia anônima\n2️⃣ Denúncia identificada\n3️⃣ Consultar protocolo\n4️⃣ Encerrar atendimento")
        return str(resp)

    # Fluxo de denúncia anônima
    if stage == "denuncia_anonima":
        denuncia = msg
        resumo = summarize_text(denuncia)
        protocolo = generate_protocol()

        try:
            supabase.table("denuncias").insert({
                "telefone": user,
                "tipo": "anonima",
                "denuncia": denuncia,
                "resumo": resumo,
                "protocolo": protocolo,
                "created_at": datetime.datetime.utcnow().isoformat()
            }).execute()
            resp.message(f"✅ Sua denúncia foi registrada!\n📄 Protocolo: {protocolo}\nResumo: {resumo}")
        except Exception as e:
            print(f"Erro ao salvar denúncia: {e}")
            resp.message("❌ Ocorreu um erro ao registrar sua denúncia. Tente novamente mais tarde.")

        reset_session(user)
        return str(resp)

    # Fluxo de denúncia identificada
    if stage == "identificacao_nome":
        sessions[user]["nome"] = msg
        sessions[user]["stage"] = "identificacao_email"
        resp.message("📧 Digite seu e-mail:")
        return str(resp)

    if stage == "identificacao_email":
        sessions[user]["email"] = msg
        sessions[user]["stage"] = "denuncia_identificada"
        resp.message("📝 Agora digite sua denúncia:")
        return str(resp)

    if stage == "denuncia_identificada":
        denuncia = msg
        resumo = summarize_text(denuncia)
        protocolo = generate_protocol()

        try:
            supabase.table("denuncias").insert({
                "telefone": user,
                "tipo": "identificada",
                "nome": sessions[user].get("nome"),
                "email": sessions[user].get("email"),
                "denuncia": denuncia,
                "resumo": resumo,
                "protocolo": protocolo,
                "created_at": datetime.datetime.utcnow().isoformat()
            }).execute()
            resp.message(f"✅ Sua denúncia foi registrada!\n📄 Protocolo: {protocolo}\nResumo: {resumo}")
        except Exception as e:
            print(f"Erro ao salvar denúncia identificada: {e}")
            resp.message("❌ Ocorreu um erro ao registrar sua denúncia. Tente novamente mais tarde.")

        reset_session(user)
        return str(resp)

    # Fluxo de consulta de protocolo
    if stage == "consulta_protocolo":
        try:
            data = supabase.table("denuncias").select("*").eq("protocolo", msg).execute()
            if data.data:
                d = data.data[0]
                resp.message(
                    f"📄 Detalhes da denúncia:\n"
                    f"Protocolo: {d['protocolo']}\n"
                    f"Tipo: {d['tipo']}\n"
                    f"Resumo: {d['resumo']}"
                )
            else:
                resp.message("⚠️ Nenhuma denúncia encontrada com esse protocolo.")
        except Exception as e:
            print(f"Erro ao consultar protocolo: {e}")
            resp.message("❌ Erro ao consultar o protocolo.")

        reset_session(user)
        return str(resp)

    # Fallback
    resp.message("⚠️ Não entendi sua resposta. Digite uma opção válida do menu.")
    return str(resp)


@app.route("/", methods=["GET"])
def home():
    return "✅ Compliance Bot rodando no Render!", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
