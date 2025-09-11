from flask import Flask, request, jsonify
from supabase import create_client
import os

app = Flask(__name__)

supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

@app.route("/consulta", methods=["POST"])
def consulta():
    data = request.json
    protocolo = data.get("protocolo")
    senha = data.get("senha")

    result = supabase.table("denuncias").select("*").eq("protocolo", protocolo).eq("senha", senha).execute()

    if result.data:
        return jsonify({"status": "ok", "denuncia": result.data[0]})
    else:
        return jsonify({"status": "erro", "mensagem": "Protocolo ou senha inválidos"}), 404
