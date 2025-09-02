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

# Validação obrigatória das env vars
REQUIRED_ENV_VARS = {
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_KEY": SUPABASE_KEY,
    "OPENAI_API_KEY": OPENAI_API_KEY,
    "TWILIO_ACCOUNT_SID": TWILIO_ACCOUNT_SID,
    "TWILIO_AUTH_TOKEN": TWILIO_AUTH_TOKEN,
    "TWILIO_NUMBER": TWILIO_NUMBER,
}

for var, value in REQUIRED_ENV_VARS.items():
    if not value:
        raise ValueError(f"❌ Variável de ambiente obrigatória não definida: {var}")

# Ajusta número para formato whatsapp:+...
if not TWILIO_NUMBER.startswith("whatsapp:"):
    TWILIO_NUMBER = f"whatsapp:{TWILIO_NUMBER}"

logging.debug(f"✅ TWILIO_NUMBER carregado: {TWILIO_NUMBER}")

# Inicializa clientes
supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_KEY)
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
openai.api_key = OPENAI_API_KEY

# Sessões temporárias na memória
sessoes = {}
TIMEOUT = timedelta(minutes=5)


def reset_sessao(telefone):
    if telefone in sessoes:
        del sessoes[telefone]


def enviar_msg(para, texto):
    """Envia mensagem pelo WhatsApp"""
    logging.debug(f"Enviando para {para}: {texto}")
    twilio_client.messages.create(
        from_=TWILIO_NUMBER,
        to=para,
        body=texto
    )


def corrigir_texto(texto: str) -> str:
    """Usa a IA para corrigir ortografia e gramática"""
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


def montar_resumo(dados, telefone):
    """Monta o resumo final com base nos dados coletados"""
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
        "✅ Se estas informações estão corretas:\n"
        "Digite 1️⃣ para confirmar e registrar sua denúncia\n"
        "Digite 2️⃣ para corrigir alguma informação\n"
        "Digite 3️⃣ para cancelar."
    )


@app.route("/webhook", methods=["POST"])
def webhook():
    telefone = request.form.get("From")
    msg = request.form.get("Body").strip() if request.form.get("Body") else ""
    logging.debug(f"Mensagem recebida de {telefone}: {msg}")

    agora = datetime.now()

    # Cria sessão se não existir ou se expirou
    if telefone not in sessoes or agora - sessoes[telefone]["ultima_interacao"] > TIMEOUT:
        sessoes[telefone] = {"etapa": "inicio", "dados": {}, "ultima_interacao": agora}
        enviar_msg(telefone, "👋 Olá! Bem-vindo ao Canal de Denúncias de Compliance.\n\n"
                             "Escolha uma opção:\n"
                             "1️⃣ Fazer denúncia *anônima*\n"
                             "2️⃣ Fazer denúncia *identificada*\n"
                             "3️⃣ Consultar protocolo existente\n"
                             "4️⃣ Encerrar atendimento")
        return "OK", 200

    # Atualiza timestamp da sessão
    sessoes[telefone]["ultima_interacao"] = agora
    etapa = sessoes[telefone]["etapa"]
    dados = sessoes[telefone]["dados"]

    # Encerrar atendimento
    if msg == "4":
        reset_sessao(telefone)
        enviar_msg(telefone, "✅ Atendimento encerrado. Digite qualquer mensagem para começar de novo.")
        return "OK", 200

    # Consultar protocolo
    if msg == "3":
        sessoes[telefone]["etapa"] = "consultar_protocolo"
        enviar_msg(telefone, "📄 Informe o número do protocolo que deseja consultar:")
        return "OK", 200

    if etapa == "consultar_protocolo":
        protocolo = corrigir_texto(msg)
        result = supabase.table("denuncias").select("*").eq("protocolo", protocolo).eq("telefone", telefone).execute()
        if result.data:
            denuncia = result.data[0]
            enviar_msg(telefone, f"📌 Protocolo {protocolo} encontrado:\n\n"
                                 f"Resumo: {denuncia.get('resumo', 'Sem resumo')}\n"
                                 f"Categoria: {denuncia.get('categoria', 'Não classificada')}")
        else:
            enviar_msg(telefone, "⚠️ Nenhum protocolo encontrado para o seu número.")
        reset_sessao(telefone)
        return "OK", 200

    # Início do fluxo
    if etapa == "inicio":
        if msg == "1":
            sessoes[telefone]["etapa"] = "coletar_descricao"
            sessoes[telefone]["dados"]["anonimo"] = True
            sessoes[telefone]["dados"]["tipo"] = "anonimo"
            enviar_msg(telefone, "✍️ Por favor, descreva sua denúncia:")
        elif msg == "2":
            sessoes[telefone]["etapa"] = "coletar_nome"
            sessoes[telefone]["dados"]["anonimo"] = False
            sessoes[telefone]["dados"]["tipo"] = "identificado"
            enviar_msg(telefone, "👤 Informe seu nome completo:")
        elif msg not in ["1", "2", "3", "4"]:
            enviar_msg(telefone, "⚠️ Opção inválida. Escolha:\n1️⃣ Anônima\n2️⃣ Identificada\n3️⃣ Consultar\n4️⃣ Encerrar")
        return "OK", 200

    # Fluxo denúncia identificada
    if etapa == "coletar_nome":
        dados["nome"] = corrigir_texto(msg)
        sessoes[telefone]["etapa"] = "coletar_email"
        enviar_msg(telefone, "📧 Agora, informe seu e-mail:")
        return "OK", 200

    if etapa == "coletar_email":
        dados["email"] = corrigir_texto(msg)
        sessoes[telefone]["etapa"] = "coletar_descricao"
        enviar_msg(telefone, "✍️ Por favor, descreva sua denúncia:")
        return "OK", 200

    # Coleta da denúncia
    if etapa == "coletar_descricao":
        dados["descricao"] = corrigir_texto(msg)

        # 🔎 Validação da IA: é denúncia de compliance ou não?
        resposta_validacao = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": (
                    "Você é um analista de compliance. "
                    "Classifique o texto do usuário como:\n"
                    "- 'denuncia' → se for um caso de compliance (assédio, corrupção, fraude, discriminação, conflito de interesses etc.)\n"
                    "- 'nao_denuncia' → se for apenas reclamação, sugestão, elogio ou outro assunto que não é de compliance."
                )},
                {"role": "user", "content": dados["descricao"]}
            ]
        ).choices[0].message.content.strip().lower()

        if "nao_denuncia" in resposta_validacao:
            sessoes[telefone]["etapa"] = "confirmar_denuncia"
            enviar_msg(telefone, "⚠️ Sua mensagem parece ser uma *reclamação, elogio ou sugestão*.\n\n"
                                 "👉 Estes casos devem ser tratados pelo canal adequado: ouvidoria@portocentrooeste.com.br\n\n"
                                 "❓ Deseja realmente registrar como denúncia de compliance? (sim/não)")
            return "OK", 200

        # Se for denúncia válida, segue com IA para resumo + categoria
        resposta = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": (
                    "Você é um assistente de compliance. "
                    "Sua tarefa é: "
                    "1. Resumir a denúncia em até 3 linhas de forma clara e objetiva. "
                    "2. Classificar a denúncia em UMA categoria da lista abaixo:\n"
                    "- Assédio moral\n"
                    "- Assédio sexual\n"
                    "- Discriminação\n"
                    "- Corrupção / Suborno\n"
                    "- Fraude\n"
                    "- Conflito de interesses\n"
                    "- Outro"
                )},
                {"role": "user", "content": dados["descricao"]}
            ]
        ).choices[0].message.content

        resumo, categoria = "", "Outro"
        if "Categoria:" in resposta:
            partes = resposta.split("Categoria:")
            resumo = corrigir_texto(partes[0].replace("Resumo:", "").strip())
            categoria = corrigir_texto(partes[1].strip())
        else:
            resumo = corrigir_texto(resposta.strip())

        dados["resumo"] = resumo
        dados["categoria"] = categoria
        sessoes[telefone]["etapa"] = "coletar_data"

        enviar_msg(telefone, f"📋 Resumo da denúncia:\n\n{resumo}\n\n"
                             f"🗂️ Categoria sugerida: {categoria}\n\n"
                             "Agora precisamos de mais informações.\n"
                             "🗓️ Quando o fato ocorreu (data e horário aproximados)?")
        return "OK", 200

    # Caso IA tenha dito que não é denúncia
    if etapa == "confirmar_denuncia":
        if msg.lower() == "sim":
            sessoes[telefone]["etapa"] = "coletar_descricao"
            enviar_msg(telefone, "✍️ Por favor, descreva sua denúncia:")
        else:
            reset_sessao(telefone)
            enviar_msg(telefone, "✅ Atendimento encerrado. Obrigado por utilizar o canal.")
        return "OK", 200

    # Perguntas complementares
    if etapa == "coletar_data":
        dados["data_fato"] = corrigir_texto(msg)
        sessoes[telefone]["etapa"] = "coletar_local"
        enviar_msg(telefone, "📍 Onde aconteceu o fato (setor, filial, área, etc.)?")
        return "OK", 200

    if etapa == "coletar_local":
        dados["local"] = corrigir_texto(msg)
        sessoes[telefone]["etapa"] = "coletar_envolvidos"
        enviar_msg(telefone, "👥 Quem estava envolvido? (pode informar cargos ou funções caso não saiba os nomes)")
        return "OK", 200

    if etapa == "coletar_envolvidos":
        dados["envolvidos"] = corrigir_texto(msg)
        sessoes[telefone]["etapa"] = "coletar_testemunhas"
        enviar_msg(telefone, "👀 Havia outras pessoas que presenciaram o fato?")
        return "OK", 200

    if etapa == "coletar_testemunhas":
        dados["testemunhas"] = corrigir_texto(msg)
        sessoes[telefone]["etapa"] = "coletar_evidencias"
        enviar_msg(telefone, "📎 Você possui documentos, fotos, vídeos ou outras evidências que possam ajudar?")
        return "OK", 200

    if etapa == "coletar_evidencias":
        dados["evidencias"] = corrigir_texto(msg)
        sessoes[telefone]["etapa"] = "coletar_frequencia"
        enviar_msg(telefone, "🔄 Esse fato ocorreu apenas uma vez ou é recorrente?")
        return "OK", 200

    if etapa == "coletar_frequencia":
        dados["frequencia"] = corrigir_texto(msg)
        sessoes[telefone]["etapa"] = "coletar_impacto"
        enviar_msg(telefone, "⚖️ Na sua visão, qual o impacto ou gravidade desse ocorrido?")
        return "OK", 200

    if etapa == "coletar_impacto":
        dados["impacto"] = corrigir_texto(msg)
        sessoes[telefone]["etapa"] = "confirmar_final"

        resumo_detalhado = montar_resumo(dados, telefone)
        enviar_msg(telefone, resumo_detalhado)
        return "OK", 200

    # Confirmação final com opção de corrigir
    if etapa == "confirmar_final":
        if msg == "1":
            protocolo = str(uuid.uuid4())[:8]
            dados["protocolo"] = protocolo
            dados["telefone"] = telefone

            supabase.table("denuncias").insert(dados).execute()

            enviar_msg(telefone, f"✅ Sua denúncia foi registrada com sucesso!\n"
                                 f"📌 Número de protocolo: {protocolo}\n\n"
                                 f"Guarde este número para futuras consultas.")
            reset_sessao(telefone)

        elif msg == "2":
            sessoes[telefone]["etapa"] = "corrigir_campo"
            enviar_msg(telefone, "Qual informação você deseja corrigir?\n"
                                 "1️⃣ Nome\n2️⃣ E-mail\n3️⃣ Descrição\n4️⃣ Data\n5️⃣ Local\n"
                                 "6️⃣ Envolvidos\n7️⃣ Testemunhas\n8️⃣ Evidências\n9️⃣ Frequência\n🔟 Impacto")

        elif msg == "3":
            reset_sessao(telefone)
            enviar_msg(telefone, "❌ Registro cancelado. Digite qualquer mensagem para começar de novo.")
        else:
            enviar_msg(telefone, "⚠️ Resposta inválida. Digite 1️⃣ Confirmar, 2️⃣ Corrigir ou 3️⃣ Cancelar.")
        return "OK", 200

    # Correção de campos específicos
    if etapa == "corrigir_campo":
        mapa = {
            "1": "nome",
            "2": "email",
            "3": "descricao",
            "4": "data_fato",
            "5": "local",
            "6": "envolvidos",
            "7": "testemunhas",
            "8": "evidencias",
            "9": "frequencia",
            "10": "impacto"
        }
        if msg in mapa:
            sessoes[telefone]["campo_corrigir"] = mapa[msg]
            sessoes[telefone]["etapa"] = "corrigir_valor"
            enviar_msg(telefone, f"✍️ Informe o novo valor para {mapa[msg]}:")
        else:
            enviar_msg(telefone, "⚠️ Opção inválida. Escolha um número de 1 a 10.")
        return "OK", 200

    if etapa == "corrigir_valor":
        campo = sessoes[telefone].get("campo_corrigir")
        if campo:
            dados[campo] = corrigir_texto(msg)
        sessoes[telefone]["etapa"] = "confirmar_final"
        resumo_detalhado = montar_resumo(dados, telefone)
        enviar_msg(telefone, resumo_detalhado)
        return "OK", 200

    return "OK", 200


@app.route("/", methods=["GET"])
def home():
    return "✅ Compliance Bot está rodando!", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
