import os
import random
import string
import logging
from flask import Flask, request
from twilio.rest import Client
from supabase import create_client, Client as SupabaseClient
from openai import OpenAI

# Configurações de logging
logging.basicConfig(level=logging.DEBUG)
app = Flask(__name__)

# Variáveis de ambiente
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

# Clientes externos
twilio_client = Client(TWILIO_SID, TWILIO_AUTH)
supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_KEY)
openai_client = OpenAI(api_key=OPENAI_KEY)

# Sessões de usuários
sessoes = {}

def enviar_msg(para, texto):
    """Envia mensagem via WhatsApp (Twilio)."""
    logging.debug(f"Enviando para {para}: {texto}")
    twilio_client.messages.create(
        from_=f"whatsapp:{TWILIO_NUMBER}",
        to=para,
        body=texto
    )

def gerar_protocolo():
    """Gera código aleatório de protocolo."""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=7))

def menu_principal(telefone):
    """Mostra o menu principal."""
    enviar_msg(telefone,
               "👋 Olá! Bem-vindo ao Canal de Denúncias de Compliance.\n\n"
               "Escolha uma opção:\n"
               "1️⃣ Fazer denúncia *anônima*\n"
               "2️⃣ Fazer denúncia *identificada*\n"
               "3️⃣ Consultar protocolo existente\n"
               "4️⃣ Encerrar atendimento")

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        telefone = request.form.get("From")
        msg = request.form.get("Body", "").strip()
        logging.debug(f"Mensagem recebida de {telefone}: {msg}")

        if telefone not in sessoes:
            sessoes[telefone] = {"estado": "menu", "dados": {}}

        estado = sessoes[telefone]["estado"]
        dados = sessoes[telefone]["dados"]

        # --- MENU PRINCIPAL ---
        if estado == "menu":
            if msg == "1":
                sessoes[telefone] = {"estado": "aguardando_descricao", "dados": {"tipo": "anonimo"}}
                enviar_msg(telefone, "✍️ Por favor, descreva sua denúncia:")
            elif msg == "2":
                sessoes[telefone] = {"estado": "aguardando_nome", "dados": {"tipo": "identificado"}}
                enviar_msg(telefone, "👤 Por favor, informe seu nome:")
            elif msg == "3":
                sessoes[telefone]["estado"] = "consultando"
                enviar_msg(telefone, "🔎 Digite o número do protocolo que deseja consultar:")
            elif msg == "4":
                sessoes.pop(telefone, None)  # Apaga a sessão
                enviar_msg(telefone, "✅ Atendimento encerrado. Se precisar, basta mandar uma mensagem novamente.")
            else:
                menu_principal(telefone)

        # --- CAPTURA DE NOME ---
        elif estado == "aguardando_nome":
            dados["nome"] = msg
            sessoes[telefone]["estado"] = "aguardando_descricao"
            enviar_msg(telefone, "✍️ Agora descreva sua denúncia:")

        # --- CAPTURA DE DESCRIÇÃO ---
        elif estado == "aguardando_descricao":
            dados["descricao"] = msg

            # Resumir denúncia com GPT
            resposta = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Resuma a denúncia em até 3 linhas de forma clara e objetiva."},
                    {"role": "user", "content": msg}
                ]
            )
            resumo = resposta.choices[0].message.content.strip()
            dados["resumo"] = resumo
            sessoes[telefone]["estado"] = "aguardando_confirmacao"

            enviar_msg(telefone,
                       f"📋 Aqui está o resumo da sua denúncia:\n\n{resumo}\n\n"
                       "Digite 1️⃣ para confirmar ou 2️⃣ para corrigir.")

        # --- CONFIRMAÇÃO ---
        elif estado == "aguardando_confirmacao":
            if msg == "1":
                protocolo = gerar_protocolo()
                dados["protocolo"] = protocolo
                dados["telefone"] = telefone

                # Salvar denúncia no Supabase
                supabase.table("denuncias").insert({
                    "protocolo": protocolo,
                    "tipo": dados.get("tipo"),
                    "nome": dados.get("nome"),
                    "descricao": dados.get("descricao"),
                    "telefone": telefone
                }).execute()

                enviar_msg(telefone, f"✅ Sua denúncia foi registrada com sucesso!\n📌 Protocolo: *{protocolo}*")

                # Reseta para menu
                sessoes[telefone] = {"estado": "menu", "dados": {}}
                menu_principal(telefone)

            elif msg == "2":
                sessoes[telefone]["estado"] = "aguardando_descricao"
                enviar_msg(telefone, "✍️ Por favor, digite novamente a sua denúncia:")
            else:
                enviar_msg(telefone, "⚠️ Responda apenas com 1 para confirmar ou 2 para corrigir.")

        # --- CONSULTA DE PROTOCOLO ---
        elif estado == "consultando":
            result = supabase.table("denuncias").select("*").eq("protocolo", msg).execute()
            if result.data:
                denuncia = result.data[0]
                enviar_msg(telefone,
                           f"📄 Denúncia encontrada:\n"
                           f"Tipo: {denuncia['tipo']}\n"
                           f"Descrição: {denuncia['descricao']}\n"
                           f"📌 Protocolo: {denuncia['protocolo']}")
            else:
                enviar_msg(telefone, "❌ Protocolo não encontrado.")

            sessoes[telefone] = {"estado": "menu", "dados": {}}
            menu_principal(telefone)

        return "OK", 200

    except Exception:
        logging.error("Erro no webhook", exc_info=True)
        return "Erro interno", 500

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
