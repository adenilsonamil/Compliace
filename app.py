import os
import uuid
from datetime import datetime, timedelta
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from supabase import create_client, Client
from openai import OpenAI

# 🔹 Configurações de ambiente
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

TWILIO_NUMBER = os.environ.get("TWILIO_NUMBER")

# 🔹 Inicializa clientes
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
openai = OpenAI(api_key=OPENAI_API_KEY)

app = Flask(__name__)

# Sessões por usuário
sessoes = {}
TEMPO_EXPIRACAO = timedelta(minutes=5)


# ------------------ Funções Auxiliares ------------------

def gerar_protocolo():
    return str(uuid.uuid4())[:8].upper()


def limpar_sessao(telefone):
    if telefone in sessoes:
        del sessoes[telefone]


def salvar_denuncia(telefone, dados, resumo):
    protocolo = gerar_protocolo()
    try:
        supabase.table("denuncias").insert({
            "telefone": telefone,
            "nome": dados.get("nome") if not dados.get("anonimo") else None,
            "descricao": dados.get("denuncia"),   # mapeado para coluna descricao
            "protocolo": protocolo,
            "tipo": "Anônimo" if dados.get("anonimo") else "Identificado",
            "created_at": datetime.utcnow().isoformat()
        }).execute()
    except Exception as e:
        print(f"⚠️ Erro ao salvar no Supabase: {e}")
    return protocolo


def resumir_texto(texto):
    try:
        resposta = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Resuma a denúncia abaixo de forma clara e objetiva."},
                {"role": "user", "content": texto}
            ]
        )
        return resposta.choices[0].message.content.strip()
    except Exception as e:
        print(f"⚠️ Erro ao resumir denúncia: {e}")
        return texto  # fallback: retorna o próprio texto


# ------------------ Fluxo Principal ------------------

@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    telefone = request.form.get("From", "").replace("whatsapp:", "")
    mensagem = request.form.get("Body", "").strip()
    resp = MessagingResponse()
    resposta = resp.message()

    # Verifica expiração da sessão
    if telefone in sessoes:
        ultima_interacao = sessoes[telefone].get("ultima_interacao")
        if datetime.utcnow() - ultima_interacao > TEMPO_EXPIRACAO:
            limpar_sessao(telefone)
            resposta.body("⚠️ Sessão expirada. Envie sua denúncia novamente.")
            return str(resp)

    # Nova denúncia
    if telefone not in sessoes:
        sessoes[telefone] = {"fase": "denuncia", "ultima_interacao": datetime.utcnow()}
        resposta.body("📢 Bem-vindo ao Canal de Compliance.\n\nPor favor, descreva sua denúncia:")
        return str(resp)

    fase = sessoes[telefone]["fase"]

    # 1️⃣ Receber a denúncia
    if fase == "denuncia":
        sessoes[telefone]["denuncia"] = mensagem
        sessoes[telefone]["fase"] = "resumo"
        sessoes[telefone]["ultima_interacao"] = datetime.utcnow()

        resumo = resumir_texto(mensagem)
        sessoes[telefone]["resumo"] = resumo

        resposta.body(
            f"📝 Aqui está o resumo da sua denúncia:\n\n{resumo}\n\nConfirma que está correto?\n1️⃣ Confirmar\n2️⃣ Corrigir"
        )
        return str(resp)

    # 2️⃣ Correção do texto
    elif fase == "resumo":
        if mensagem == "1":  # Confirmar
            protocolo = salvar_denuncia(telefone, sessoes[telefone], sessoes[telefone]["resumo"])
            limpar_sessao(telefone)
            resposta.body(
                f"✅ Sua denúncia foi registrada com sucesso!\n\n📌 Protocolo: *{protocolo}*\n\n"
                "Guarde este número para acompanhar sua denúncia futuramente."
            )
        elif mensagem == "2":  # Corrigir
            sessoes[telefone]["fase"] = "denuncia"
            resposta.body("✍️ Ok, por favor reescreva sua denúncia:")
        else:
            resposta.body("❌ Opção inválida. Responda com:\n1️⃣ Confirmar\n2️⃣ Corrigir")
        return str(resp)

    return str(resp)


# ------------------ Início ------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
