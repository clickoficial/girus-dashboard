"""
server.py — Girus Dashboard Server
"""

import os
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

DADOS_BASE = {
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


def classificar(nome):
    n = nome.upper()
    if "GIRUS" in n or "INDUSMOV" in n:
        return "fabrica"
    if "ARTFIX" in n:
        return "quimica"
    return "atacado"


def montar_dados(fat, fonte="base"):
    hoje      = datetime.now()
    dias_mes  = 30
    dia_atual = hoje.day
    prog_mes  = round((dia_atual / dias_mes) * 100, 1)
    fat_total = fat["fabrica"] + fat["quimica"] + fat["atacado"]
    mes       = hoje.strftime("%m/%Y")
    return {
        "atualizado_em": datetime.now().isoformat(),
        "mes":           mes,
        "dia_atual":     dia_atual,
        "dias_mes":      dias_mes,
        "prog_mes":      prog_mes,
        "fonte":         fonte,
        "faturamento": {
            "fabrica": fat["fabrica"],
            "quimica": fat["quimica"],
            "atacado": fat["atacado"],
            "total":   fat_total,
        },
        "despesas_real": {
            "colaboradores": None,
            "fixas":         None,
            "impostos":      None,
        },
        "previsao": PREVISAO,
        "metas":    METAS,
    }


def atualizar_cache():
    global cache
    fat = dict(DADOS_BASE)
    fonte = "base"
    if APP_KEY and APP_SECRET:
        try:
            mes = datetime.now().strftime("%m/%Y")
            totais = {"fabrica": 0.0, "quimica": 0.0, "atacado": 0.0}
            pagina = 1
            while True:
                payload = {
                    "call": "ListarNF",
                    "app_key": APP_KEY,
                    "app_secret": APP_SECRET,
                    "param": [{
                        "pagina": pagina,
                        "registros_por_pagina": 100,
                        "dDtEmi_De":  f"01/{mes}",
                        "dDtEmi_Ate": f"31/{mes}",
                    }]
                }
                r = requests.post(f"{BASE_URL}/produtos/nfconsultar/", headers=HEADERS, json=payload, timeout=15)
                r.raise_for_status()
                resp = r.json()
                nfs = resp.get("nfCadastro", [])
                if not nfs:
                    break
                for nf in nfs:
                    nome  = nf.get("ide", {}).get("cNome", "") or ""
                    valor = float(nf.get("total", {}).get("vNF", 0))
                    totais[classificar(nome)] += valor
                if pagina >= resp.get("total_de_paginas", 1):
                    break
                pagina += 1
            if sum(totais.values()) > 0:
                fat = totais
                fonte = "omie"
        except Exception as e:
            print(f"Omie indisponível: {e}")
    cache["dados"] = montar_dados(fat, fonte)
    cache["atualizado_em"] = datetime.now().isoformat()
    cache["erro"] = None


def loop_atualizacao():
    while True:
        try:
            atualizar_cache()
        except Exception as e:
            print(f"Erro: {e}")
            if cache["dados"] is None:
                cache["dados"] = montar_dados(dict(DADOS_BASE), "base")
        time.sleep(3600)


@app.route("/")
@requer_auth
def index():
    return send_file("index.html")


@app.route("/api/dados")
@requer_auth
def api_dados():
    if cache["dados"] is None:
        return jsonify({"status": "ok", "dados": montar_dados(dict(DADOS_BASE), "base")})
    return jsonify({"status": "ok", "dados": cache["dados"]})


@app.route("/api/status")
@requer_auth
def api_status():
    return jsonify({"online": True, "atualizado_em": cache["atualizado_em"], "erro": cache["erro"]})


if __name__ == "__main__":
    t = threading.Thread(target=loop_atualizacao, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
