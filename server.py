"""
server.py — Girus Dashboard Server
"""

import os
import json
import time
import threading
import requests
from datetime import datetime
from functools import wraps
from flask import Flask, jsonify, request, Response, send_file

app = Flask(__name__)

APP_KEY    = os.environ.get("OMIE_APP_KEY", "")
APP_SECRET = os.environ.get("OMIE_APP_SECRET", "")
DASH_USER  = os.environ.get("DASH_USER", "girus")
DASH_PASS  = os.environ.get("DASH_PASS", "")

PREVISAO = {
    "colaboradores": 1572000.00,
    "fixas":         1610000.00,
    "impostos":      455939.78,
    "faturamento":   6079197.02,
}

METAS = {
    "fabrica": 3703866.22,
    "quimica":  265949.40,
    "atacado": 2109381.40,
}

cache = {"dados": None, "atualizado_em": None, "erro": None}

BASE_URL = "https://app.omie.com.br/api/v1"
HEADERS  = {"Content-Type": "application/json"}


def requer_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or auth.username != DASH_USER or auth.password != DASH_PASS:
            return Response(
                "Acesso restrito.",
                401,
                {"WWW-Authenticate": 'Basic realm="Girus Dashboard"'}
            )
        return f(*args, **kwargs)
    return decorated


def omie_post(endpoint, call, params):
    payload = {
        "call": call,
        "app_key": APP_KEY,
        "app_secret": APP_SECRET,
        "param": [params]
    }
    r = requests.post(f"{BASE_URL}/{endpoint}/", headers=HEADERS, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def mes_atual():
    return datetime.now().strftime("%m/%Y")


def classificar(nome):
    n = nome.upper()
    if "GIRUS" in n or "INDUSMOV" in n:
        return "fabrica"
    if "ARTFIX" in n:
        return "quimica"
    return "atacado"


def atualizar_cache():
    global cache
    try:
        print(f"[{datetime.now():%H:%M:%S}] Atualizando dados do Omie...")
        mes = mes_atual()
        hoje = datetime.now()
        dias_mes = 30
        dia_atual = hoje.day
        prog_mes = round((dia_atual / dias_mes) * 100, 1)

        # Tenta buscar do Omie; se falhar usa dados base
        fat = {"fabrica": 3703866.22, "quimica": 265949.40, "atacado": 2109381.40}
        desp = {"colaboradores": None, "fixas": None, "impostos": None}

        if APP_KEY and APP_SECRET:
            try:
                # Busca NFs
                totais = {"fabrica": 0.0, "quimica": 0.0, "atacado": 0.0}
                pagina = 1
                while True:
                    resp = omie_post("produtos/nfconsultar", "ListarNF", {
                        "pagina": pagina,
                        "registros_por_pagina": 100,
                        "dDtEmi_De": f"01/{mes}",
                        "dDtEmi_Ate": f"31/{mes}",
                    })
                    nfs = resp.get("nfCadastro", [])
                    if not nfs:
                        break
                    for nf in nfs:
                        nome = nf.get("ide", {}).get("cNome", "") or ""
                        valor = float(nf.get("total", {}).get("vNF", 0))
                        totais[classificar(nome)] += valor
                    if pagina >= resp.get("total_de_paginas", 1):
                        break
                    pagina += 1
                fat = totais
            except Exception as e:
                print(f"  Aviso Omie NF: {e}")

        fat_total = fat["fabrica"] + fat["quimica"] + fat["atacado"]

        cache["dados"] = {
            "atualizado_em": datetime.now().isoformat(),
            "mes": mes,
            "dia_atual": dia_atual,
            "dias_mes": dias_mes,
            "prog_mes": prog_mes,
            "faturamento": {**fat, "total": fat_total},
            "despesas_real": desp,
            "previsao": PREVISAO,
            "metas": METAS,
        }
        cache["atualizado_em"] = datetime.now().isoformat()
        cache["erro"] = None
        print(f"  ✓ Fat total: R$ {fat_total:,.2f}")

    except Exception as e:
        cache["erro"] = str(e)
        print(f"  ✗ Erro: {e}")


def loop_atualizacao():
    while True:
        atualizar_cache()
        time.sleep(3600)


@app.route("/")
@requer_auth
def index():
    return send_file("index.html")


@app.route("/api/dados")
@requer_auth
def api_dados():
    if cache["dados"] is None:
        return jsonify({"status": "carregando", "erro": cache["erro"]}), 202
    return jsonify({"status": "ok", "dados": cache["dados"]})


@app.route("/api/status")
@requer_auth
def api_status():
    return jsonify({
        "online": True,
        "atualizado_em": cache["atualizado_em"],
        "erro": cache["erro"],
    })


if __name__ == "__main__":
    t = threading.Thread(target=loop_atualizacao, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
