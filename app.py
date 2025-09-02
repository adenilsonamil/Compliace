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
# 🔐 Variáveis de ambiente
# ==============================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = os.getenv("TWILIO_NUMBER")

# Validação
for var, value in {
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_KEY": SUPABASE_KEY,
    "OPENAI_API_KEY": OPENAI_API_KEY,
    "TWILIO_ACCOUNT_SID": TWILIO_ACCOUNT_SID,
    "TWILIO_AUTH_TOKEN": TWILIO_AUTH_TOKEN,
    "TWILIO_NUMBER": TWILIO_NUMBER,
}.items():
    if not value:
        raise ValueError(f"❌ Variável obrigatória não definida: {var}")

# Ajusta Twilio para WhatsApp
if not TWILIO_NUMBER.startswith("whatsapp:"):
    TWILIO_NUMBER = f"whatsapp:{TWILIO_NUMBER}"

logging.debug(f"✅ TWILIO_NUMBER carregado: {TWILIO_NUMBER}")

# Inicializa clientes
supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_KEY)
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
openai.api_key = OPENAI_API_KEY

# Sessões em memória
sessoes = {}
TIMEOUT = timedelta(minutes=5)

# ======================================
# 🔧 Funções
# ======================================
def reset_sessao(telefone):
    if telefone in sessoes:
        del sessoes[telefone]

def enviar_msg(para, texto):
    """Envia mensagem WhatsApp"""
    logging.debug(f"Enviando para {para}: {texto}")
    twilio_client.messages.create(from_=TWILIO_NUMBER, to=para, body=texto)

def corrigir_texto(texto: str) -> str:
    """Corrige ortografia/gramática sem mudar sentido"""
    try:
        resp = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Corrija ortografia e gramática sem mudar o sentido do texto."},
                {"role": "user", "content": texto}
            ]
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"Erro na correção: {e}")
        return texto

# ======================================
# 🔔 Webhook
# ======================================
@app.route("/webhook", methods=["POST"])
def webhook():
    telefone = request.form.get("From")
    msg = (request.form.get("Body") or "").strip()
    logging.debug(f"Mensagem recebida de {telefone}: {msg}")

    agora = datetime.now()
    if telefone not in sessoes or agora - sessoes[telefone]["ultima_interacao"] > TIMEOUT:
        sessoes[telefone] = {"etapa": "inicio", "dados": {}, "ultima_interacao": agora}
        enviar_msg(telefone,
            "👋 Olá! Bem-vindo ao Canal de Denúncias de Compliance.\n\n"
            "Escolha:\n"
            "1️⃣ Fazer denúncia *anônima*\n"
            "2️⃣ Fazer denúncia *identificada*\n"
            "3️⃣ Consultar protocolo\n"
            "4️⃣ Encerrar atendimento"
        )
        return "OK", 200

    sessoes[telefone]["ultima_interacao"] = agora
    etapa = sessoes[telefone]["etapa"]
    dados = sessoes[telefone]["dados"]

    # Encerrar
    if msg == "4":
        reset_sessao(telefone)
        enviar_msg(telefone, "✅ Atendimento encerrado.")
        return "OK", 200

    # Consultar protocolo
    if msg == "3":
        sessoes[telefone]["etapa"] = "consultar_protocolo"
        enviar_msg(telefone, "📄 Informe o número do protocolo:")
        return "OK", 200

    if etapa == "consultar_protocolo":
        protocolo = corrigir_texto(msg)
        result = supabase.table("denuncias").select("*").eq("protocolo", protocolo).eq("telefone", telefone).execute()
        if result.data:
            d = result.data[0]
            enviar_msg(telefone, f"📌 Protocolo {protocolo}:\nResumo: {d.get('resumo','—')}\nCategoria: {d.get('categoria','—')}")
        else:
            enviar_msg(telefone, "⚠️ Nenhum protocolo encontrado.")
        reset_sessao(telefone)
        return "OK", 200

    # Fluxo inicial
    if etapa == "inicio":
        if msg == "1":
            dados["anonimo"] = True
            sessoes[telefone]["etapa"] = "coletar_descricao"
            enviar_msg(telefone, "✍️ Por favor, descreva sua denúncia com o máximo de detalhes possíveis:")
        elif msg == "2":
            dados["anonimo"] = False
            sessoes[telefone]["etapa"] = "coletar_nome"
            enviar_msg(telefone, "👤 Informe seu nome completo:")
        else:
            enviar_msg(telefone, "⚠️ Escolha uma opção válida (1 a 4).")
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
        enviar_msg(telefone, "✍️ Agora descreva sua denúncia com todos os detalhes relevantes:")
        return "OK", 200

    # Descrição
    if etapa == "coletar_descricao":
        dados["descricao"] = corrigir_texto(msg)
        # IA resume e categoriza
        resposta = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role":"system","content":"Resuma em até 3 linhas e classifique em uma categoria."},
                {"role":"user","content":dados["descricao"]}
            ]
        ).choices[0].message.content
        resumo, categoria = resposta, "Outro"
        if "Categoria:" in resposta:
            partes = resposta.split("Categoria:")
            resumo = corrigir_texto(partes[0].replace("Resumo:","").strip())
            categoria = corrigir_texto(partes[1].strip())
        dados["resumo"] = resumo
        dados["categoria"] = categoria
        sessoes[telefone]["etapa"] = "coletar_data"
        enviar_msg(telefone, f"📋 Resumo: {resumo}\nCategoria: {categoria}\n\n🗓️ Quando ocorreu o fato (data e horário aproximados)?")
        return "OK", 200

    # Perguntas detalhadas
    perguntas = {
        "coletar_data":("data_fato","📍 Onde aconteceu o fato (setor, filial, local etc.)?"),
        "coletar_local":("local","👥 Quem estava envolvido (nomes, cargos ou funções)?"),
        "coletar_envolvidos":("envolvidos","👀 Houve testemunhas? Quem?"),
        "coletar_testemunhas":("testemunhas","📎 Existem evidências (documentos, fotos, vídeos etc.)?"),
        "coletar_evidencias":("evidencias","🔄 Esse fato ocorreu apenas uma vez ou é recorrente?"),
        "coletar_frequencia":("frequencia","⚖️ Qual o impacto ou gravidade na sua visão?"),
        "coletar_impacto":("impacto","FINAL"),
    }

    if etapa in perguntas:
        campo, prox = perguntas[etapa]
        dados[campo] = corrigir_texto(msg)
        if prox == "FINAL":
            sessoes[telefone]["etapa"] = "confirmar_final"
            telefone_str = telefone if not dados.get("anonimo") else "—"
            nome_str = dados.get("nome","—") if not dados.get("anonimo") else "—"
            email_str = dados.get("email","—") if not dados.get("anonimo") else "—"
            resumo = (
                f"📋 Resumo final:\n\n"
                f"👤 Tipo: {'Anônima' if dados.get('anonimo') else 'Identificada'}\n"
                f"Nome: {nome_str}\nE-mail: {email_str}\nTelefone: {telefone_str}\n\n"
                f"📝 Descrição: {dados.get('descricao')}\n"
                f"📄 Resumo IA: {dados.get('resumo')}\n"
                f"🗂️ Categoria: {dados.get('categoria')}\n\n"
                f"🗓️ Data: {dados.get('data_fato')}\n"
                f"📍 Local: {dados.get('local')}\n"
                f"👥 Envolvidos: {dados.get('envolvidos')}\n"
                f"👀 Testemunhas: {dados.get('testemunhas')}\n"
                f"📎 Evidências: {dados.get('evidencias')}\n"
                f"🔄 Frequência: {dados.get('frequencia')}\n"
                f"⚖️ Impacto: {dados.get('impacto')}\n\n"
                "✅ Digite 1️⃣ para confirmar\n"
                "✏️ Digite 2️⃣ para corrigir informações\n"
                "❌ Digite 3️⃣ para cancelar"
            )
            enviar_msg(telefone,resumo)
        else:
            sessoes[telefone]["etapa"] = [k for k,v in perguntas.items() if v[0]==prox][0]
            enviar_msg(telefone, prox)
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
            sessoes[telefone]["etapa"] = "corrigir_campo"
            enviar_msg(telefone,"Qual campo deseja corrigir?\n"
                                "1️⃣ Nome\n2️⃣ E-mail\n3️⃣ Data\n4️⃣ Local\n"
                                "5️⃣ Envolvidos\n6️⃣ Testemunhas\n7️⃣ Evidências\n"
                                "8️⃣ Frequência\n9️⃣ Impacto\n🔟 Descrição")
        elif msg == "3":
            reset_sessao(telefone)
            enviar_msg(telefone,"❌ Denúncia cancelada.")
        else:
            enviar_msg(telefone,"⚠️ Escolha válida: 1, 2 ou 3.")
        return "OK",200

    if etapa == "corrigir_campo":
        campos = {
            "1":"nome","2":"email","3":"data_fato","4":"local","5":"envolvidos",
            "6":"testemunhas","7":"evidencias","8":"frequencia","9":"impacto","10":"descricao"
        }
        if msg not in campos:
            enviar_msg(telefone,"⚠️ Opção inválida (1-10).")
            return "OK",200
        sessoes[telefone]["campo_corrigir"] = campos[msg]
        sessoes[telefone]["etapa"] = "corrigir_valor"
        enviar_msg(telefone,f"✏️ Digite o novo valor para {campos[msg]}:")
        return "OK",200

    if etapa == "corrigir_valor":
        campo = sessoes[telefone]["campo_corrigir"]
        dados[campo] = corrigir_texto(msg)
        sessoes[telefone]["etapa"] = "confirmar_final"
        enviar_msg(telefone,"✅ Informação atualizada. Veja o resumo novamente digitando qualquer tecla.")
        return "OK",200

    return "OK",200

@app.route("/", methods=["GET"])
def home():
    return "✅ Compliance Bot rodando!", 200

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",10000)))
