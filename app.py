import os
import uuid
import logging
from datetime import datetime, timedelta
from flask import Flask, request
from twilio.rest import Client
from supabase import create_client, Client as SupabaseClient
import openai

# Configurações
app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)

# ==============================
# 🔐 Carregamento das variáveis
# ==============================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = os.getenv("TWILIO_NUMBER")

# Validação obrigatória
for var, value in {
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_KEY": SUPABASE_KEY,
    "OPENAI_API_KEY": OPENAI_API_KEY,
    "TWILIO_ACCOUNT_SID": TWILIO_ACCOUNT_SID,
    "TWILIO_AUTH_TOKEN": TWILIO_AUTH_TOKEN,
    "TWILIO_NUMBER": TWILIO_NUMBER,
}.items():
    if not value:
        raise ValueError(f"❌ Variável de ambiente não definida: {var}")

if not TWILIO_NUMBER.startswith("whatsapp:"):
    TWILIO_NUMBER = f"whatsapp:{TWILIO_NUMBER}"

logging.debug(f"✅ TWILIO_NUMBER carregado: {TWILIO_NUMBER}")

# Inicializa clientes
supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_KEY)
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
openai.api_key = OPENAI_API_KEY

# Sessões temporárias
sessoes = {}
TIMEOUT = timedelta(minutes=5)


def reset_sessao(telefone):
    if telefone in sessoes:
        del sessoes[telefone]


def enviar_msg(para, texto):
    """Envia mensagem pelo WhatsApp"""
    logging.debug(f"Enviando para {para}: {texto}")
    twilio_client.messages.create(from_=TWILIO_NUMBER, to=para, body=texto)


def corrigir_texto(texto: str) -> str:
    """Corrige ortografia e gramática com IA"""
    try:
        resposta = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": (
                    "Você é um assistente de revisão de texto. "
                    "Corrija apenas ortografia e gramática, sem mudar o sentido."
                )},
                {"role": "user", "content": texto}
            ]
        )
        return resposta.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"Erro na correção: {e}")
        return texto


def montar_resumo(dados, telefone):
    """Monta o resumo detalhado da denúncia"""
    telefone_str = telefone if not dados.get("anonimo") else "—"
    nome_str = dados.get("nome", "—") if not dados.get("anonimo") else "—"
    email_str = dados.get("email", "—") if not dados.get("anonimo") else "—"

    return (
        "📋 Resumo da sua denúncia:\n\n"
        f"👤 Tipo: {'Anônima' if dados.get('anonimo') else 'Identificada'}\n"
        f"Nome: {nome_str}\n"
        f"E-mail: {email_str}\n"
        f"Telefone: {telefone_str}\n\n"
        f"📝 Descrição: {dados.get('descricao', '—')}\n"
        f"📄 Resumo (IA): {dados.get('resumo', '—')}\n"
        f"🗂️ Categoria: {dados.get('categoria', '—')}\n\n"
        f"🗓️ Data do fato: {dados.get('data_fato', '—')}\n"
        f"📍 Local: {dados.get('local', '—')}\n"
        f"👥 Envolvidos: {dados.get('envolvidos', '—')}\n"
        f"👀 Testemunhas: {dados.get('testemunhas', '—')}\n"
        f"📎 Evidências: {dados.get('evidencias', '—')}\n"
        f"🔄 Frequência: {dados.get('frequencia', '—')}\n"
        f"⚖️ Impacto: {dados.get('impacto', '—')}\n\n"
        "✅ Se está tudo correto:\n"
        "1️⃣ Confirmar e registrar\n"
        "2️⃣ Cancelar\n"
        "3️⃣ Corrigir alguma informação"
    )


@app.route("/webhook", methods=["POST"])
def webhook():
    telefone = request.form.get("From")
    msg = request.form.get("Body").strip() if request.form.get("Body") else ""
    agora = datetime.now()

    if telefone not in sessoes or agora - sessoes[telefone]["ultima_interacao"] > TIMEOUT:
        sessoes[telefone] = {"etapa": "inicio", "dados": {}, "ultima_interacao": agora}
        enviar_msg(telefone, "👋 Bem-vindo ao Canal de Compliance.\n\n"
                             "1️⃣ Denúncia *anônima*\n"
                             "2️⃣ Denúncia *identificada*\n"
                             "3️⃣ Consultar protocolo\n"
                             "4️⃣ Encerrar")
        return "OK", 200

    sessoes[telefone]["ultima_interacao"] = agora
    etapa = sessoes[telefone]["etapa"]
    dados = sessoes[telefone]["dados"]

    # Encerrar
    if msg == "4":
        reset_sessao(telefone)
        enviar_msg(telefone, "✅ Atendimento encerrado.")
        return "OK", 200

    # Fluxo inicial
    if etapa == "inicio":
        if msg == "1":
            dados["anonimo"] = True
            sessoes[telefone]["etapa"] = "coletar_descricao"
            enviar_msg(telefone, "✍️ Descreva sua denúncia:")
        elif msg == "2":
            dados["anonimo"] = False
            sessoes[telefone]["etapa"] = "coletar_nome"
            enviar_msg(telefone, "👤 Informe seu nome:")
        return "OK", 200

    # Identificada
    if etapa == "coletar_nome":
        dados["nome"] = corrigir_texto(msg)
        sessoes[telefone]["etapa"] = "coletar_email"
        enviar_msg(telefone, "📧 Informe seu e-mail:")
        return "OK", 200

    if etapa == "coletar_email":
        dados["email"] = corrigir_texto(msg)
        sessoes[telefone]["etapa"] = "coletar_descricao"
        enviar_msg(telefone, "✍️ Descreva sua denúncia:")
        return "OK", 200

    # Descrição
    if etapa == "coletar_descricao":
        dados["descricao"] = corrigir_texto(msg)
        sessoes[telefone]["etapa"] = "coletar_data"
        enviar_msg(telefone, "🗓️ Quando ocorreu o fato?")
        return "OK", 200

    # Perguntas adicionais
    if etapa == "coletar_data":
        dados["data_fato"] = corrigir_texto(msg)
        sessoes[telefone]["etapa"] = "coletar_local"
        enviar_msg(telefone, "📍 Onde ocorreu o fato?")
        return "OK", 200

    if etapa == "coletar_local":
        dados["local"] = corrigir_texto(msg)
        sessoes[telefone]["etapa"] = "coletar_envolvidos"
        enviar_msg(telefone, "👥 Quem estava envolvido?")
        return "OK", 200

    if etapa == "coletar_envolvidos":
        dados["envolvidos"] = corrigir_texto(msg)
        sessoes[telefone]["etapa"] = "coletar_testemunhas"
        enviar_msg(telefone, "👀 Houve testemunhas?")
        return "OK", 200

    if etapa == "coletar_testemunhas":
        dados["testemunhas"] = corrigir_texto(msg)
        sessoes[telefone]["etapa"] = "coletar_evidencias"
        enviar_msg(telefone, "📎 Há evidências (fotos, docs, etc.)?")
        return "OK", 200

    if etapa == "coletar_evidencias":
        dados["evidencias"] = corrigir_texto(msg)
        sessoes[telefone]["etapa"] = "coletar_frequencia"
        enviar_msg(telefone, "🔄 Foi um caso único ou recorrente?")
        return "OK", 200

    if etapa == "coletar_frequencia":
        dados["frequencia"] = corrigir_texto(msg)
        sessoes[telefone]["etapa"] = "coletar_impacto"
        enviar_msg(telefone, "⚖️ Qual o impacto?")
        return "OK", 200

    if etapa == "coletar_impacto":
        dados["impacto"] = corrigir_texto(msg)
        sessoes[telefone]["etapa"] = "confirmar_final"
        enviar_msg(telefone, montar_resumo(dados, telefone))
        return "OK", 200

    # Confirmação
    if etapa == "confirmar_final":
        if msg == "1":
            protocolo = str(uuid.uuid4())[:8]
            dados["protocolo"] = protocolo
            dados["telefone"] = telefone
            supabase.table("denuncias").insert(dados).execute()
            enviar_msg(telefone, f"✅ Denúncia registrada!\n📌 Protocolo: {protocolo}")
            reset_sessao(telefone)
        elif msg == "2":
            reset_sessao(telefone)
            enviar_msg(telefone, "❌ Registro cancelado.")
        elif msg == "3":
            sessoes[telefone]["etapa"] = "corrigir_campo"
            enviar_msg(telefone, "✏️ Qual campo deseja corrigir?\n"
                                 "(Ex: Nome, E-mail, Local, Data do fato, Envolvidos, Impacto, etc.)")
        else:
            enviar_msg(telefone, "⚠️ Digite 1️⃣, 2️⃣ ou 3️⃣.")
        return "OK", 200

    if etapa == "corrigir_campo":
        sessoes[telefone]["campo_corrigir"] = msg.lower()
        sessoes[telefone]["etapa"] = "corrigir_valor"
        enviar_msg(telefone, f"✏️ Digite o novo valor para '{msg}':")
        return "OK", 200

    if etapa == "corrigir_valor":
        campo = sessoes[telefone].get("campo_corrigir")
        if campo:
            dados[campo] = corrigir_texto(msg)
            sessoes[telefone]["etapa"] = "confirmar_final"
            enviar_msg(telefone, "✅ Informação atualizada!\n\n" +
                       montar_resumo(dados, telefone))
        return "OK", 200

    return "OK", 200


@app.route("/", methods=["GET"])
def home():
    return "✅ Compliance Bot rodando!", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
