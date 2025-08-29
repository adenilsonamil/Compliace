# Whistlebot (WhatsApp Compliance Channel)

Canal de ouvidoria/denúncia via WhatsApp usando **Twilio + Flask** e deploy no **Render**. 
Suporta denúncias **anônimas** ou **identificadas**, fluxo interativo, protocolo de acompanhamento, 
anexos (imagem/áudio/documento) e envio opcional de e-mail à equipe de Compliance.

## Arquitetura
- **Flask** recebe o webhook do Twilio (`/whatsapp`).
- **State machine** conversa com o usuário (anônimo ou identificado).
- **SQLite/Postgres** via SQLAlchemy para persistência.
- **Assinatura Twilio** validada (segurança).
- **Envio de e-mail** opcional (SMTP Office365, configurável).
- **Render** para hospedagem (ver `render.yaml`).

## Rotas
- `POST /whatsapp` — Webhook do Twilio (WhatsApp).
- `GET /health` — Healthcheck.
- `GET /admin/reports` — JSON de denúncias (provisorio, com Basic Auth).

## Comandos rápidos no WhatsApp
- `menu` — reexibe o menu.
- `cancelar` — encerra a sessão atual.
- `status ABC12345` — consulta status pelo protocolo.

## Como rodar localmente
1. Python 3.11+
2. `python -m venv .venv && source .venv/bin/activate` (Linux/macOS) ou `.\.venv\Scripts\activate` (Windows)
3. `pip install -r requirements.txt`
4. Copie `.env.example` para `.env` e preencha variáveis.
5. `python app/app.py`
6. Use ngrok para expor localmente (opcional): `ngrok http 5000` e configure o webhook no Twilio.

## Deploy no Render (via GitHub)
1. Suba este repositório para o GitHub.
2. Abra `render.com`, crie um novo **Web Service** a partir do seu repositório.
3. Configure as variáveis de ambiente (iguais às do `.env.example`).
4. Start command: `gunicorn app.app:app --workers=2 --threads=4 --timeout=60`
5. Atualize no **Twilio Console** o **Webhook** para o endpoint público `/whatsapp`.

## Banco de dados
- Local: SQLite (arquivo `data.db`).
- Produção: use Postgres no Render (ajuste `DATABASE_URL`).

## Avisos LGPD/Compliance
- Para denúncias **anônimas**, o sistema **não armazena** telefone/identidade.
- Para **identificadas**, os dados só são armazenados se houver **consentimento** explícito.
- O número do remetente é **hasheado** (`SHA-256` + salt) para deduplicação sem expor o telefone.
- Defina política de retenção e acesso a dados.


## Teste rápido no Twilio Sandbox
- Ative o **Sandbox WhatsApp** no Twilio Console e siga as instruções de "join".
- Defina a URL do webhook de **mensagens recebidas** para `https://SEU_HOST/whatsapp`.
- Envie `oi` para iniciar.

---

> Segurança: valide a assinatura `X-Twilio-Signature` (já implementado) e **use HTTPS** sempre.
