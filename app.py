import os
import logging
import random
import string
from flask import Flask, request
from twilio.rest import Client
from supabase import create_client, Client as SupabaseClient
from openai import OpenAI

# Configurações iniciais
logging.basicConfig(level=logging.DEBUG)
app = Flask(__name__)

# Variáveis de ambiente
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = os.getenv("TWILIO_NUMBER")

# Clientes
openai_client = OpenAI(api_key=OPENAI_API_KEY)
supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_KEY)
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Sessões em memória
sessoes = {}

# Funções utilitárias
def gerar_protocolo():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))

def enviar_msg(telefone, texto):
    logging.debug(f"Enviando para {telefone}: {texto}")
    twilio_client.messages.create(
        from_=TWILIO_NUMBER,
        body=texto,
        to=telefone
    )

def reset_sessao(telefone):
    sessoes[telefone] = {"etapa": "inicio", "dados": {}}

# Função para correção ortográfica
def corrigir_texto(texto):
    try:
        resposta = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Você é um assistente de revisão de texto. Corrija apenas ortografia e gramática, sem mudar o sentido."},
                {"role": "user", "content": texto}
            ]
        )
        return resposta.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"Erro ao corrigir texto: {e}")
        return texto

# -------------------------
# Rota principal do bot
# -------------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    telefone = request.form.get("From")
    msg = request.form.get("Body").strip()
    logging.debug(f"Mensagem recebida de {telefone}: {msg}")

    if telefone not in sessoes:
        reset_sessao(telefone)

    etapa = sessoes[telefone]["etapa"]
    dados = sessoes[telefone]["dados"]

    # -------------------------
    # INÍCIO
    # -------------------------
    if etapa == "inicio":
        if msg == "1":
            dados["anonimo"] = True
            sessoes[telefone]["etapa"] = "descricao"
            enviar_msg(telefone, "Por favor, descreva sua denúncia:")
            return "OK", 200
        elif msg == "2":
            dados["anonimo"] = False
            sessoes[telefone]["etapa"] = "nome"
            enviar_msg(telefone, "👤 Informe seu nome completo:")
            return "OK", 200
        elif msg == "3":
            sessoes[telefone]["etapa"] = "consultar_protocolo"
            enviar_msg(telefone, "📄 Informe o número do protocolo que deseja consultar:")
            return "OK", 200
        elif msg == "4":
            enviar_msg(telefone, "✅ Atendimento encerrado. Digite qualquer mensagem para começar de novo.")
            reset_sessao(telefone)
            return "OK", 200
        else:
            enviar_msg(telefone, "👋 Olá! Bem-vindo ao Canal de Denúncias de Compliance.\n\n"
                                 "Escolha uma opção:\n"
                                 "1️⃣ Fazer denúncia *anônima*\n"
                                 "2️⃣ Fazer denúncia *identificada*\n"
                                 "3️⃣ Consultar protocolo existente\n"
                                 "4️⃣ Encerrar atendimento")
            return "OK", 200

    # -------------------------
    # CONSULTA DE PROTOCOLO
    # -------------------------
    if etapa == "consultar_protocolo":
        protocolo = msg.strip()
        result = supabase.table("denuncias").select("*").eq("protocolo", protocolo).eq("telefone", telefone).execute()

        if result.data:
            d = result.data[0]
            texto = (
                f"📌 Protocolo: {d.get('protocolo')}\n"
                f"👤 Tipo: {'Anônima' if d.get('anonimo') else 'Identificada'}\n"
            )

            if not d.get("anonimo"):
                texto += (
                    f"Nome: {d.get('nome','—')}\n"
                    f"E-mail: {d.get('email','—')}\n"
                    f"Telefone: {d.get('telefone','—')}\n"
                )

            texto += (
                f"\n📝 Descrição: {d.get('descricao','—')}\n"
                f"📄 Resumo: {d.get('resumo','—')}\n"
                f"🗂️ Categoria: {d.get('categoria','—')}\n\n"
                f"🗓️ Data do fato: {d.get('data_fato','—')}\n"
                f"📍 Local: {d.get('local','—')}\n"
                f"👥 Envolvidos: {d.get('envolvidos','—')}\n"
                f"👀 Testemunhas: {d.get('testemunhas','—')}\n"
                f"📎 Evidências: {d.get('evidencias','—')}\n"
                f"🔄 Frequência: {d.get('frequencia','—')}\n"
                f"⚖️ Impacto: {d.get('impacto','—')}"
            )

            enviar_msg(telefone, texto)
        else:
            enviar_msg(telefone, "⚠️ Nenhum protocolo encontrado para o seu número.")

        reset_sessao(telefone)
        return "OK", 200

    # -------------------------
    # DENÚNCIA IDENTIFICADA
    # -------------------------
    if etapa == "nome":
        dados["nome"] = corrigir_texto(msg)
        sessoes[telefone]["etapa"] = "email"
        enviar_msg(telefone, "📧 Informe seu e-mail:")
        return "OK", 200

    if etapa == "email":
        dados["email"] = msg
        sessoes[telefone]["etapa"] = "descricao"
        enviar_msg(telefone, "Por favor, descreva sua denúncia:")
        return "OK", 200

    # -------------------------
    # DESCRIÇÃO
    # -------------------------
    if etapa == "descricao":
        dados["descricao"] = corrigir_texto(msg)
        sessoes[telefone]["etapa"] = "confirmar"
        protocolo = gerar_protocolo()
        dados["protocolo"] = protocolo

        resumo = f"📋 Resumo da denúncia:\n\n"
        if not dados.get("anonimo"):
            resumo += f"👤 Nome: {dados.get('nome')}\n📧 E-mail: {dados.get('email')}\n📱 Telefone: {telefone}\n\n"
        resumo += f"📝 Descrição: {dados.get('descricao')}\n\n📌 Protocolo: {protocolo}\n\n"
        resumo += "Digite 1️⃣ para confirmar e registrar sua denúncia ou 2️⃣ para cancelar."

        enviar_msg(telefone, resumo)
        return "OK", 200

    # -------------------------
    # CONFIRMAÇÃO
    # -------------------------
    if etapa == "confirmar":
        if msg == "1":
            dados["telefone"] = telefone
            supabase.table("denuncias").insert(dados).execute()
            enviar_msg(telefone, f"✅ Sua denúncia foi registrada com sucesso!\n📌 Protocolo: {dados['protocolo']}")
        else:
            enviar_msg(telefone, "❌ Denúncia cancelada.")

        reset_sessao(telefone)
        return "OK", 200

    return "OK", 200

@app.route("/", methods=["GET"])
def home():
    return "Bot de Compliance rodando!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
