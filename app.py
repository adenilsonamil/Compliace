from flask import Flask, request

app = Flask(__name__)

# Rota raiz para teste rápido no navegador/Render
@app.route("/")
def home():
    return "✅ Compliance Bot rodando no Render!"

# Rota Webhook que será chamada pelo Twilio
@app.route("/webhook", methods=["POST", "GET"])
def webhook():
    if request.method == "GET":
        return "Webhook ativo ✅", 200

    if request.method == "POST":
        data = request.form.to_dict()
        print("📩 Mensagem recebida:", data)
        # Aqui futuramente vamos processar a mensagem e salvar no Supabase
        return "Mensagem recebida pelo bot ✅", 200


if __name__ == "__main__":
    # Apenas para rodar localmente (Render usará gunicorn)
    app.run(host="0.0.0.0", port=5000, debug=True)
