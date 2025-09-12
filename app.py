import os
import logging
import random
import string
from datetime import datetime

from flask import Flask, request
from twilio.rest import Client
from supabase import create_client, Client as SupabaseClient
from openai import OpenAI

# Configuração de logs
logging.basicConfig(level=logging.DEBUG)

# Configurações de ambiente
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")  # já vem com whatsapp:
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# Inicializações
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

app = Flask(__name__)

# Função para gerar protocolo e senha
def gerar_protocolo():
    return "DNC-" + datetime.now().strftime("%Y%m%d-%H%M%S")

def gerar_senha(tamanho=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=tamanho))

# Função para enviar mensagem pelo WhatsApp
def enviar_whatsapp(to, body):
    try:
        logging.debug(f"Enviando de {TWILIO_PHONE_NUMBER} para {to}: {body}")
        message = twilio_client.messages.create(
            from_=f"whatsapp:{TWILIO_PHONE_NUMBER}",
            to=f"whatsapp:{to}",
            body=body
        )
        return message.sid
    except Exception as e:
        logging.error(f"Erro ao enviar mensagem WhatsApp: {e}")

# Função para salvar/atualizar denúncia
def salvar_denuncia(telefone, campos):
    try:
        denuncia_existente = supabase.table("denuncias").select("*").eq("telefone", telefone).eq("status", "rascunho").execute()
        if denuncia_existente.data:
            denuncia_id = denuncia_existente.data[0]["id"]
            supabase.table("denuncias").update(campos).eq("id", denuncia_id).execute()
            return denuncia_id
        else:
            protocolo = gerar_protocolo()
            senha = gerar_senha()
            campos.update({
                "telefone": telefone,
                "status": "rascunho",
                "protocolo": protocolo,
                "senha": senha
            })
            result = supabase.table("denuncias").insert(campos).execute()
            return result.data[0]["id"]
    except Exception as e:
        logging.error(f"Erro ao salvar denúncia: {e}")
        return None

# Função para finalizar denúncia
def finalizar_denuncia(telefone, campos):
    try:
        denuncia_existente = supabase.table("denuncias").select("*").eq("telefone", telefone).eq("status", "rascunho").execute()
        if denuncia_existente.data:
            denuncia_id = denuncia_existente.data[0]["id"]
            protocolo = denuncia_existente.data[0]["protocolo"]
            senha = denuncia_existente.data[0]["senha"]

            supabase.table("denuncias").update({
                **campos,
                "status": "finalizado"
            }).eq("id", denuncia_id).execute()

            return protocolo, senha
        return None, None
    except Exception as e:
        logging.error(f"Erro ao finalizar denúncia: {e}")
        return None, None

# Função para processar mensagem com IA
def processar_mensagem(msg_usuario, contexto):
    try:
        resposta = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": """
                Você é um atendente de ouvidoria de compliance, amigável e acolhedor.
                Sua função é coletar informações de uma denúncia, em diálogo humanizado.

                Informações necessárias:
                - descricao
                - categoria
                - local
                - data_fato
                - envolvidos
                - testemunhas
                - impacto
                - evidencias

                Regras:
                - Corrija erros de português.
                - Pergunte apenas o que ainda não foi informado.
                - Responda SEMPRE em JSON no formato:
                {"mensagem": "texto amigável para o usuário", "campos": {...}}
                - No campo "campos", devolva apenas os dados extraídos até agora.
                """},
                {"role": "user", "content": msg_usuario},
                {"role": "assistant", "content": contexto}
            ],
            max_tokens=400,
            response_format={"type": "json_object"}
        )
        return resposta.choices[0].message.content
    except Exception as e:
        logging.error(f"Erro ao processar mensagem IA: {e}")
        return '{"mensagem": "Desculpe, ocorreu um erro ao processar sua mensagem.", "campos": {}}'

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        from_number = request.values.get("From", "").replace("whatsapp:", "")
        body = request.values.get("Body", "")

        logging.debug(f"Mensagem recebida de {from_number}: {body}")

        # Contexto anterior (recuperar últimos campos)
        denuncia_existente = supabase.table("denuncias").select("*").eq("telefone", from_number).eq("status", "rascunho").execute()
        contexto = "" if not denuncia_existente.data else str(denuncia_existente.data[0])

        resposta_ia = processar_mensagem(body, contexto)

        import json
        dados = json.loads(resposta_ia)
        mensagem = dados.get("mensagem", "Erro ao gerar resposta")
        campos = dados.get("campos", {})

        # Salva parcial
        salvar_denuncia(from_number, campos)

        # Verifica se todos os campos mínimos foram coletados
        obrigatorios = ["descricao", "categoria", "local", "data_fato"]
        if all(campo in campos and campos[campo] for campo in obrigatorios):
            protocolo, senha = finalizar_denuncia(from_number, campos)
            if protocolo and senha:
                resumo = f"""
✅ Sua denúncia foi registrada!

📌 Protocolo: {protocolo}
🔑 Senha: {senha}

Resumo:
- Descrição: {campos.get('descricao', '')}
- Categoria: {campos.get('categoria', '')}
- Local: {campos.get('local', '')}
- Data do fato: {campos.get('data_fato', '')}
- Envolvidos: {campos.get('envolvidos', 'Não informado')}
- Testemunhas: {campos.get('testemunhas', 'Não informado')}
- Impacto: {campos.get('impacto', 'Não informado')}
- Evidências: {campos.get('evidencias', 'Não informado')}

Você pode acompanhar sua denúncia em:
🌐 https://ouvidoria.portocentrooeste.com.br
"""
                enviar_whatsapp(from_number, resumo)
                return "OK", 200

        # Continua o diálogo
        enviar_whatsapp(from_number, mensagem)
        return "OK", 200
    except Exception as e:
        logging.error(f"Erro no webhook: {e}")
        return "Erro", 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
