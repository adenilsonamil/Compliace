import os
import uuid
import logging
from datetime import datetime, timedelta
from flask import Flask, request
from twilio.rest import Client
from supabase import create_client, Client as SupabaseClient
import openai
from cryptography.fernet import Fernet
import requests

# Configurações
app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)

# ==============================
# 🔐 Variáveis de ambiente
# ==============================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "denuncias-evidencias")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = os.getenv("TWILIO_NUMBER")
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

# Validação obrigatória
REQUIRED_ENV_VARS = {
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_KEY": SUPABASE_KEY,
    "OPENAI_API_KEY": OPENAI_API_KEY,
    "TWILIO_ACCOUNT_SID": TWILIO_ACCOUNT_SID,
    "TWILIO_AUTH_TOKEN": TWILIO_AUTH_TOKEN,
    "TWILIO_NUMBER": TWILIO_NUMBER,
    "ENCRYPTION_KEY": ENCRYPTION_KEY,
}
for var, value in REQUIRED_ENV_VARS.items():
    if not value:
        raise ValueError(f"❌ Variável de ambiente obrigatória não definida: {var}")

if not TWILIO_NUMBER.startswith("whatsapp:"):
    TWILIO_NUMBER = f"whatsapp:{TWILIO_NUMBER}"

# Inicializa clientes
supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_KEY)
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
openai.api_key = OPENAI_API_KEY
fernet = Fernet(ENCRYPTION_KEY.encode())

sessoes = {}
TIMEOUT = timedelta(minutes=5)

# ==============================
# Funções Auxiliares
# ==============================
def reset_sessao(telefone):
    if telefone in sessoes:
        del sessoes[telefone]

def mascarar_telefone(tel):
    return tel[-4:].rjust(len(tel), "*")

def criptografar(dado: str) -> bytes:
    return fernet.encrypt(dado.encode())

def enviar_msg(para, texto):
    tel_mask = mascarar_telefone(para)
    logging.debug(f"Enviando para {tel_mask}: {texto[:60]}...")
    twilio_client.messages.create(from_=TWILIO_NUMBER, to=para, body=texto)

def corrigir_texto(texto: str) -> str:
    try:
        resposta = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": (
                    "Você é um assistente de revisão de texto. "
                    "Corrija o texto do usuário apenas em ortografia e gramática, "
                    "sem mudar o sentido ou acrescentar informações."
                )},
                {"role": "user", "content": texto}
            ]
        )
        return resposta.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"Erro na correção do texto: {e}")
        return texto

def salvar_midias(request, dados):
    """Baixa mídias do Twilio e armazena no Supabase Storage"""
    num_media = int(request.form.get("NumMedia", 0))
    midias = []
    if num_media > 0:
        for i in range(num_media):
            media_url = request.form.get(f"MediaUrl{i}")
            media_type = request.form.get(f"MediaContentType{i}")
            nome_arquivo = f"{uuid.uuid4().hex}_{i}.{media_type.split('/')[-1]}"
            resposta = requests.get(media_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
            if resposta.status_code == 200:
                supabase.storage.from_(SUPABASE_BUCKET).upload(
                    file=resposta.content,
                    path=nome_arquivo,
                    file_options={"content-type": media_type}
                )
                midias.append({"url": nome_arquivo, "tipo": media_type})
    if midias:
        dados["midias"] = midias

def montar_resumo(dados):
    midias = dados.get("midias", [])
    evidencias = "\n".join([f"{m['tipo']}: {m['url']}" for m in midias]) if midias else dados.get("evidencias", "—")
    return (
        "📋 Resumo da sua denúncia:\n\n"
        f"👤 Tipo: {'Anônima' if dados.get('anonimo') else 'Identificada'}\n"
        f"📝 Descrição: {dados.get('descricao', '—')}\n"
        f"📄 Resumo (IA): {dados.get('resumo', '—')}\n"
        f"🗂️ Categoria: {dados.get('categoria', '—')}\n\n"
        f"🗓️ Data do fato: {dados.get('data_fato', '—')}\n"
        f"📍 Local: {dados.get('local', '—')}\n"
        f"👥 Envolvidos: {dados.get('envolvidos', '—')}\n"
        f"👀 Testemunhas: {dados.get('testemunhas', '—')}\n"
        f"📎 Evidências: {evidencias}\n"
        f"🔄 Frequência: {dados.get('frequencia', '—')}\n"
        f"⚖️ Impacto: {dados.get('impacto', '—')}\n\n"
        "✅ Se estas informações estão corretas:\n"
        "Digite 1️⃣ para confirmar e registrar sua denúncia\n"
        "Digite 2️⃣ para corrigir alguma informação\n"
        "Digite 3️⃣ para cancelar."
    )

# ==============================
# Webhooks principais
# ==============================
@app.route("/webhook", methods=["POST"])
def webhook():
    telefone = request.form.get("From")
    msg = request.form.get("Body").strip() if request.form.get("Body") else ""
    agora = datetime.now()

    # Cria sessão
    if telefone not in sessoes or agora - sessoes[telefone]["ultima_interacao"] > TIMEOUT:
        sessoes[telefone] = {"etapa": "inicio", "dados": {}, "ultima_interacao": agora}
        enviar_msg(telefone, "👋 Bem-vindo ao Canal de Denúncias.\n\n1️⃣ Anônima\n2️⃣ Identificada")
        return "OK", 200

    sessoes[telefone]["ultima_interacao"] = agora
    etapa = sessoes[telefone]["etapa"]
    dados = sessoes[telefone]["dados"]

    salvar_midias(request, dados)

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

    if etapa == "coletar_descricao":
        dados["descricao"] = corrigir_texto(msg)
        sessoes[telefone]["etapa"] = "coletar_data"
        enviar_msg(telefone, "🗓️ Quando ocorreu o fato?")
        return "OK", 200

    # ... (demais etapas iguais ao seu fluxo original)

    if etapa == "coletar_impacto":
        dados["impacto"] = corrigir_texto(msg)
        sessoes[telefone]["etapa"] = "confirmar_final"
        enviar_msg(telefone, montar_resumo(dados))
        return "OK", 200

    if etapa == "confirmar_final":
        if msg == "1":
            protocolo = str(uuid.uuid4())[:8]
            dados["protocolo"] = protocolo

            # Salva denúncia (sem dados pessoais)
            denuncia_data = {k: v for k, v in dados.items() if k not in ["nome", "email"]}
            supabase.table("denuncias").insert(denuncia_data).execute()

            # Salva denunciante (se não for anônimo)
            if not dados.get("anonimo"):
                denunciante_data = {
                    "protocolo": protocolo,
                    "telefone": criptografar(telefone),
                    "nome": criptografar(dados.get("nome", "")),
                    "email": criptografar(dados.get("email", ""))
                }
                supabase.table("denunciantes").insert(denunciante_data).execute()

            enviar_msg(telefone, f"✅ Denúncia registrada!\n📌 Protocolo: {protocolo}")
            reset_sessao(telefone)
        return "OK", 200

    return "OK", 200

@app.route("/", methods=["GET"])
def home():
    return "✅ Compliance Bot está rodando!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
