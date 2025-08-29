import os
import time
import random
import string
import logging
from flask import Flask, request
from twilio.rest import Client
from supabase import create_client, Client as SupabaseClient
import openai

# Configurações de log
logging.basicConfig(level=logging.DEBUG)

# Variáveis de ambiente
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = os.getenv("TWILIO_NUMBER")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Inicializar serviços
supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_KEY)
client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
openai.api_key = OPENAI_API_KEY

# App Flask
app = Flask(__name__)

# Sessões de usuários
sessoes = {}
TEMPO_LIMITE = 300  # 5 minutos de inatividade

# Funções auxiliares
def gerar_protocolo():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def resumo_ia(descricao):
    try:
        resposta = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Você é um assistente que resume denúncias de compliance de forma clara e objetiva."},
                {"role": "user", "content": descricao}
            ],
            max_tokens=120
        )
        return resposta.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"Erro ao resumir denúncia: {e}")
        return descricao

def resetar_sessao(telefone):
    if telefone in sessoes:
        del sessoes[telefone]

# Rota principal
@app.route("/webhook", methods=["POST"])
def webhook():
    telefone = request.form.get("From")
    body = request.form.get("Body").strip()
    logging.debug(f"Mensagem recebida de {telefone}: {body}")

    # Resetar sessão por inatividade
    if telefone in sessoes:
        ultima = sessoes[telefone].get("ultima_interacao", time.time())
        if time.time() - ultima > TEMPO_LIMITE:
            resetar_sessao(telefone)

    if telefone not in sessoes:
        sessoes[telefone] = {"etapa": "menu", "ultima_interacao": time.time()}
        resposta = (
            "👋 Olá, bem-vindo ao Canal de Denúncias de Compliance.\n\n"
            "Escolha uma opção:\n"
            "1️⃣ - Fazer denúncia anônima\n"
            "2️⃣ - Fazer denúncia identificada\n"
            "3️⃣ - Consultar protocolo\n"
            "4️⃣ - Encerrar atendimento"
        )
        client.messages.create(from_=TWILIO_NUMBER, to=telefone, body=resposta)
        return "OK", 200

    sessao = sessoes[telefone]
    sessao["ultima_interacao"] = time.time()

    etapa = sessao.get("etapa")

    # Menu inicial
    if etapa == "menu":
        if body == "1":
            sessao["etapa"] = "denuncia"
            sessao["anonimo"] = True
            resposta = "📝 Por favor, descreva sua denúncia:"
        elif body == "2":
            sessao["etapa"] = "nome"
            sessao["anonimo"] = False
            resposta = "📛 Por favor, informe seu nome completo:"
        elif body == "3":
            sessao["etapa"] = "consultar_protocolo"
            resposta = "🔎 Digite o número do protocolo que deseja consultar:"
        elif body == "4":
            resetar_sessao(telefone)
            resposta = (
                "✅ Atendimento encerrado.\n\n"
                "Se precisar novamente, digite qualquer mensagem para recomeçar."
            )
        else:
            resposta = (
                "⚠️ Opção inválida.\n\nEscolha uma opção:\n"
                "1️⃣ - Fazer denúncia anônima\n"
                "2️⃣ - Fazer denúncia identificada\n"
                "3️⃣ - Consultar protocolo\n"
                "4️⃣ - Encerrar atendimento"
            )
        client.messages.create(from_=TWILIO_NUMBER, to=telefone, body=resposta)
        return "OK", 200

    # Etapas de denúncia identificada
    if etapa == "nome":
        sessao["nome"] = body
        sessao["etapa"] = "email"
        resposta = "📧 Agora, por favor, informe seu e-mail:"
        client.messages.create(from_=TWILIO_NUMBER, to=telefone, body=resposta)
        return "OK", 200

    if etapa == "email":
        sessao["email"] = body
        sessao["etapa"] = "denuncia"
        resposta = "📝 Por favor, descreva sua denúncia:"
        client.messages.create(from_=TWILIO_NUMBER, to=telefone, body=resposta)
        return "OK", 200

    # Etapa de descrição da denúncia
    if etapa == "denuncia":
        sessao["descricao"] = body
        resumo = resumo_ia(body)
        sessao["resumo"] = resumo
        sessao["etapa"] = "confirmar"
        resposta = (
            f"📋 Resumo da sua denúncia:\n{resumo}\n\n"
            "Digite:\n1️⃣ - Confirmar\n2️⃣ - Corrigir"
        )
        client.messages.create(from_=TWILIO_NUMBER, to=telefone, body=resposta)
        return "OK", 200

    # Confirmação
    if etapa == "confirmar":
        if body == "1":
            protocolo = gerar_protocolo()
            sessao["protocolo"] = protocolo

            # Salvar no Supabase
            dados = {
                "telefone": telefone,
                "protocolo": protocolo,
                "descricao": sessao.get("descricao"),
                "resumo": sessao.get("resumo"),
                "anonimo": sessao.get("anonimo", True),
                "nome": sessao.get("nome"),
                "email": sessao.get("email"),
            }
            try:
                supabase.table("denuncias").insert(dados).execute()
                resposta = f"✅ Sua denúncia foi registrada com sucesso!\n📌 Protocolo: {protocolo}\n\nUse a opção 3 do menu para consultar."
            except Exception as e:
                resposta = f"⚠️ Erro ao salvar denúncia: {e}"

            resetar_sessao(telefone)
        elif body == "2":
            sessao["etapa"] = "denuncia"
            resposta = "✏️ Ok, descreva novamente sua denúncia:"
        else:
            resposta = "⚠️ Opção inválida. Digite 1 para confirmar ou 2 para corrigir."

        client.messages.create(from_=TWILIO_NUMBER, to=telefone, body=resposta)
        return "OK", 200

    # Consulta de protocolo
    if etapa == "consultar_protocolo":
        protocolo = body.strip()
        resultado = supabase.table("denuncias").select("*").eq("protocolo", protocolo).eq("telefone", telefone).execute()
        if resultado.data:
            denuncia = resultado.data[0]
            resposta = (
                f"📌 Protocolo: {protocolo}\n"
                f"Resumo: {denuncia['resumo']}\n"
                f"Data: {denuncia.get('created_at', 'N/A')}"
            )
        else:
            resposta = "⚠️ Nenhuma denúncia encontrada para este protocolo."
        client.messages.create(from_=TWILIO_NUMBER, to=telefone, body=resposta)
        resetar_sessao(telefone)
        return "OK", 200

    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
