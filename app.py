import os
import random
import string
import logging
from datetime import datetime
from flask import Flask, request, Response
from twilio.rest import Client
from supabase import create_client, Client as SupabaseClient

# Configuração de logging
logging.basicConfig(level=logging.DEBUG)

# Inicialização do Flask
app = Flask(__name__)

# ========================
# Variáveis de ambiente
# ========================
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP = os.getenv("TWILIO_PHONE_NUMBER")  # deve ser no formato: whatsapp:+14155238886

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# Verificação das variáveis
obrigatorias = {
    "TWILIO_ACCOUNT_SID": TWILIO_SID,
    "TWILIO_AUTH_TOKEN": TWILIO_AUTH,
    "TWILIO_PHONE_NUMBER": TWILIO_WHATSAPP,
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_SERVICE_ROLE_KEY": SUPABASE_KEY
}
for var, valor in obrigatorias.items():
    if not valor:
        raise ValueError(f"❌ Variável de ambiente obrigatória não definida: {var}")

# ========================
# Clientes externos
# ========================
client_twilio = Client(TWILIO_SID, TWILIO_AUTH)
supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_KEY)

# Estados dos usuários
estados = {}

# ========================
# Funções auxiliares
# ========================
def enviar_whatsapp(destino: str, mensagem: str):
    """Envia mensagens pelo WhatsApp via Twilio"""
    try:
        numero_formatado = destino
        if not numero_formatado.startswith("whatsapp:"):
            numero_formatado = f"whatsapp:{numero_formatado}"
        logging.debug(f"Enviando para {numero_formatado}: {mensagem}")
        client_twilio.messages.create(
            from_=TWILIO_WHATSAPP,
            body=mensagem,
            to=numero_formatado
        )
    except Exception as e:
        logging.error(f"Erro ao enviar mensagem WhatsApp: {e}")

def gerar_protocolo():
    """Gera um protocolo único"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def gerar_senha():
    """Gera uma senha simples"""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=6))

# ========================
# Rota principal (webhook)
# ========================
@app.route("/webhook", methods=["POST"])
def webhook():
    dados = request.form
    user_number = dados.get("From", "").replace("whatsapp:", "")
    user_message = dados.get("Body", "").strip()

    if not user_number:
        return Response(status=400)

    estado = estados.get(user_number, {"etapa": "inicio", "dados": {}})

    etapa = estado["etapa"]
    dados = estado["dados"]

    # Fluxo inicial
    if etapa == "inicio":
        enviar_whatsapp(user_number, "👋 Olá! Você deseja registrar uma denúncia de forma:\n1️⃣ Anônima\n2️⃣ Identificada")
        estado["etapa"] = "tipo"
        estados[user_number] = estado
        return Response(status=200)

    # Escolha do tipo
    if etapa == "tipo":
        if user_message == "1":
            dados["anonimo"] = True
            dados["tipo"] = "Anônima"
            enviar_whatsapp(user_number, "✍️ Por favor, descreva sua denúncia.")
            estado["etapa"] = "descricao"
        elif user_message == "2":
            dados["anonimo"] = False
            dados["tipo"] = "Identificada"
            enviar_whatsapp(user_number, "👤 Informe seu nome:")
            estado["etapa"] = "nome"
        else:
            enviar_whatsapp(user_number, "⚠️ Escolha inválida. Digite 1 para Anônima ou 2 para Identificada.")
        estados[user_number] = estado
        return Response(status=200)

    # Nome
    if etapa == "nome":
        dados["nome"] = user_message
        enviar_whatsapp(user_number, "📧 Informe seu e-mail:")
        estado["etapa"] = "email"
        estados[user_number] = estado
        return Response(status=200)

    # E-mail
    if etapa == "email":
        dados["email"] = user_message
        enviar_whatsapp(user_number, "📱 Informe seu telefone:")
        estado["etapa"] = "telefone"
        estados[user_number] = estado
        return Response(status=200)

    # Telefone
    if etapa == "telefone":
        dados["telefone"] = user_message
        enviar_whatsapp(user_number, "✍️ Agora descreva sua denúncia:")
        estado["etapa"] = "descricao"
        estados[user_number] = estado
        return Response(status=200)

    # Descrição
    if etapa == "descricao":
        dados["descricao"] = user_message
        enviar_whatsapp(user_number, "📅 Quando ocorreu o fato?")
        estado["etapa"] = "data_fato"
        estados[user_number] = estado
        return Response(status=200)

    if etapa == "data_fato":
        dados["data_fato"] = user_message
        enviar_whatsapp(user_number, "📍 Onde ocorreu o fato?")
        estado["etapa"] = "local"
        estados[user_number] = estado
        return Response(status=200)

    if etapa == "local":
        dados["local"] = user_message
        enviar_whatsapp(user_number, "👥 Quem esteve envolvido?")
        estado["etapa"] = "envolvidos"
        estados[user_number] = estado
        return Response(status=200)

    if etapa == "envolvidos":
        dados["envolvidos"] = user_message
        enviar_whatsapp(user_number, "👀 Houve testemunhas? Se sim, informe.")
        estado["etapa"] = "testemunhas"
        estados[user_number] = estado
        return Response(status=200)

    if etapa == "testemunhas":
        dados["testemunhas"] = user_message
        enviar_whatsapp(user_number, "📎 Você possui documentos, fotos, vídeos ou outras evidências que possam ajudar? (Sim/Não)")
        estado["etapa"] = "evidencias"
        estados[user_number] = estado
        return Response(status=200)

    if etapa == "evidencias":
        if user_message.lower() in ["sim", "s"]:
            dados["evidencias"] = "Sim"
            enviar_whatsapp(user_number, "📤 Deseja anexar as evidências agora?\n1️⃣ Sim\n2️⃣ Não")
            estado["etapa"] = "anexo"
        else:
            dados["evidencias"] = "Não"
            estado["etapa"] = "resumo"
        estados[user_number] = estado
        return Response(status=200)

    if etapa == "anexo":
        if user_message == "1":
            dados["midias"] = "Usuário optou por enviar anexos posteriormente"
        else:
            dados["midias"] = None
        estado["etapa"] = "resumo"
        estados[user_number] = estado
        # não retorna aqui, deixa cair no resumo

    if etapa == "resumo":
        resumo = f"📋 Resumo da denúncia:\n\n"
        resumo += f"👤 Tipo: {dados.get('tipo', 'N/A')}\n"
        if not dados.get("anonimo"):
            resumo += f"👤 Nome: {dados.get('nome', 'N/A')}\n"
            resumo += f"📧 E-mail: {dados.get('email', 'N/A')}\n"
            resumo += f"📱 Telefone: {dados.get('telefone', 'N/A')}\n"
        resumo += f"📝 Descrição: {dados.get('descricao', 'N/A')}\n"
        resumo += f"📅 Data do Fato: {dados.get('data_fato', 'N/A')}\n"
        resumo += f"📍 Local: {dados.get('local', 'N/A')}\n"
        resumo += f"👥 Envolvidos: {dados.get('envolvidos', 'N/A')}\n"
        resumo += f"👀 Testemunhas: {dados.get('testemunhas', 'N/A')}\n"
        resumo += f"📎 Evidências: {dados.get('evidencias', 'N/A')}\n"

        enviar_whatsapp(user_number, resumo + "\n✅ Se estas informações estão corretas:\nDigite 1️⃣ para confirmar e registrar sua denúncia\nDigite 2️⃣ para corrigir alguma informação\nDigite 3️⃣ para cancelar.")
        estado["etapa"] = "confirmacao"
        estados[user_number] = estado
        return Response(status=200)

    if etapa == "confirmacao":
        if user_message == "1":
            protocolo = gerar_protocolo()
            senha = gerar_senha()
            dados["protocolo"] = protocolo
            dados["senha"] = senha
            dados["criado_em"] = datetime.utcnow().isoformat()

            supabase.table("denuncias").insert(dados).execute()

            enviar_whatsapp(user_number, f"✅ Denúncia registrada com sucesso!\n📑 Protocolo: {protocolo}\n🔑 Senha: {senha}")
            estados.pop(user_number, None)  # limpa estado
        elif user_message == "2":
            enviar_whatsapp(user_number, "✍️ Vamos corrigir. Por favor, descreva novamente sua denúncia:")
            estado["etapa"] = "descricao"
            estados[user_number] = estado
        elif user_message == "3":
            enviar_whatsapp(user_number, "❌ Denúncia cancelada.")
            estados.pop(user_number, None)  # ✅ limpa estado no cancelamento
        else:
            enviar_whatsapp(user_number, "⚠️ Opção inválida. Digite 1, 2 ou 3.")
        return Response(status=200)

    # Se cair aqui, reinicia fluxo
    estados.pop(user_number, None)
    enviar_whatsapp(user_number, "⚠️ Não entendi. Vamos começar novamente.\nDigite qualquer coisa para iniciar.")
    return Response(status=200)

@app.route("/", methods=["GET"])
def index():
    return "✅ API de Compliance rodando!", 200
