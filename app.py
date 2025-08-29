import os
import time
import random
import string
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from openai import OpenAI
from supabase import create_client, Client

# =========================
# CONFIGURAÇÕES
# =========================
app = Flask(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

openai = OpenAI(api_key=OPENAI_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Sessões de usuários
sessoes = {}
TEMPO_EXPIRACAO = 300  # 5 minutos


# =========================
# FUNÇÕES AUXILIARES
# =========================
def gerar_protocolo():
    return ''.join(random.choices(string.digits, k=8))


def resumo_denuncia(texto):
    try:
        resposta = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Resuma a denúncia em poucas linhas, de forma clara e objetiva."},
                {"role": "user", "content": texto}
            ]
        )
        return resposta.choices[0].message.content.strip()
    except Exception as e:
        return f"(Erro ao gerar resumo: {e})"


def salvar_denuncia(telefone, dados, resumo):
    protocolo = gerar_protocolo()
    supabase.table("denuncias").insert({
        "telefone": telefone,
        "nome": dados.get("nome"),
        "email": dados.get("email"),
        "denuncia": dados.get("denuncia"),
        "resumo": resumo,
        "protocolo": protocolo
    }).execute()
    return protocolo


def buscar_por_protocolo(telefone, protocolo):
    resultado = supabase.table("denuncias").select("*").eq("protocolo", protocolo).eq("telefone", telefone).execute()
    if resultado.data:
        return resultado.data[0]
    return None


def resetar_sessao(telefone):
    sessoes[telefone] = {"state": "inicio", "last_active": time.time()}


def sessao_expirada(sessao):
    return (time.time() - sessao.get("last_active", 0)) > TEMPO_EXPIRACAO


# =========================
# ROTA PRINCIPAL
# =========================
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    from_number = request.values.get("From", "").replace("whatsapp:", "")
    resp = MessagingResponse()

    # Carregar ou resetar sessão
    sessao = sessoes.get(from_number, {"state": "inicio", "last_active": time.time()})
    if sessao_expirada(sessao):
        resetar_sessao(from_number)
        sessao = sessoes[from_number]

    sessao["last_active"] = time.time()

    state = sessao["state"]

    # =========================
    # FLUXO DE CONVERSA
    # =========================

    # Início da conversa
    if state == "inicio":
        resp.message("👋 Olá! Bem-vindo ao Canal de Denúncias de Compliance.\n\n"
                     "Você gostaria de realizar sua denúncia:\n"
                     "1️⃣ De forma anônima\n"
                     "2️⃣ Se identificando")
        sessao["state"] = "escolha_tipo"

    # Escolha entre anônimo ou identificado
    elif state == "escolha_tipo":
        if incoming_msg == "1":
            sessao["anonimo"] = True
            resp.message("✅ Entendido. Sua denúncia será **anônima**.\n\nPor favor, descreva sua denúncia:")
            sessao["state"] = "coletando_denuncia"

        elif incoming_msg == "2":
            sessao["anonimo"] = False
            resp.message("✍️ Por favor, informe seu **nome completo**:")
            sessao["state"] = "coletando_nome"

        else:
            resp.message("❌ Opção inválida. Digite 1 para anônima ou 2 para identificada.")

    # Nome do denunciante
    elif state == "coletando_nome":
        sessao["nome"] = incoming_msg
        resp.message("📧 Agora, informe seu **e-mail**:")
        sessao["state"] = "coletando_email"

    # E-mail do denunciante
    elif state == "coletando_email":
        sessao["email"] = incoming_msg
        resp.message("✅ Obrigado. Agora, por favor descreva sua denúncia:")
        sessao["state"] = "coletando_denuncia"

    # Captura da denúncia
    elif state == "coletando_denuncia":
        sessao["denuncia"] = incoming_msg
        resumo = resumo_denuncia(incoming_msg)
        sessao["resumo"] = resumo
        resp.message(f"📋 Aqui está um resumo da sua denúncia:\n\n{resumo}\n\n"
                     "Confirma que as informações estão corretas?\n"
                     "1️⃣ Sim, está correto\n"
                     "2️⃣ Não, quero corrigir")
        sessao["state"] = "confirmando"

    # Confirmação final
    elif state == "confirmando":
        if incoming_msg == "1":
            protocolo = salvar_denuncia(from_number, sessao, sessao["resumo"])
            resp.message(f"✅ Sua denúncia foi registrada com sucesso!\n\n"
                         f"📋 Resumo: {sessao['resumo']}\n"
                         f"📌 Protocolo: {protocolo}\n\n"
                         "Guarde este número para futuras consultas.")
            resetar_sessao(from_number)

        elif incoming_msg == "2":
            resp.message("🔄 Ok, vamos corrigir sua denúncia. Por favor, descreva novamente o problema.")
            sessao["state"] = "coletando_denuncia"

        else:
            resp.message("❌ Resposta inválida. Digite 1 para confirmar ou 2 para corrigir.")

    # Consulta de protocolo
    elif incoming_msg.lower().startswith("protocolo"):
        partes = incoming_msg.split()
        if len(partes) >= 2:
            protocolo = partes[1]
            denuncia = buscar_por_protocolo(from_number, protocolo)
            if denuncia:
                resp.message(f"📌 Protocolo: {protocolo}\n"
                             f"📋 Resumo: {denuncia['resumo']}\n"
                             f"📅 Denúncia registrada com sucesso.")
            else:
                resp.message("❌ Nenhuma denúncia encontrada para este protocolo ou número de telefone.")
        else:
            resp.message("❌ Por favor, informe o número do protocolo. Exemplo: protocolo 12345678")

    else:
        resp.message("🤖 Não entendi sua mensagem. Por favor, siga as instruções ou digite 'protocolo XXXXXXXX' para consultar sua denúncia.")

    sessoes[from_number] = sessao
    return str(resp)


# =========================
# MAIN
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
