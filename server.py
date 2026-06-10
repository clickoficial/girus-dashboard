"""
server.py — Girus Dashboard Server v3
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
    n = (nome or "").upper()
    if "GIRUS" in n or "INDUSMOV" in n:
        return "fabrica"
    if "ARTFIX" in n:
        return "quimica"
    return "atacado"


def omie_post(endpoint, call, params):
    payload = {
        "call": call,
        "app_key": APP_KEY,
        "app_secret": APP_SECRET,
        "param": [params]
    }
    r = requests.post(
        f"{BASE_URL}/{endpoint}/",
        headers=HEADERS, json=payload, timeout=20
    )
    r.raise_for_status()
    return r.json()


def buscar_faturamento_omie():
    """Busca NFs de saída pelo módulo de Faturamento."""
    mes = datetime.now().strftime("%m/%Y")
    totais = {"fabrica": 0.0, "quimica": 0.0, "atacado": 0.0}
    total_valor = 0.0
    pagina = 1

    while True:
        resp = omie_post("produtos/nfconsultar", "ListarNF", {
            "pagina": pagina,
            "registros_por_pagina": 50,
            "dDtEmi_De":  f"01/{mes}",
            "dDtEmi_Ate": f"31/{mes}",
            "tpNF": "1",  # 1 = Saída
        })

        registros = resp.get("nfCadastro", [])
        if not registros:
            break

        for nf in registros:
            # Tenta diferentes campos de nome/cliente
            nome = (
                nf.get("dest", {}).get("cRazaoSocial", "") or
                nf.get("ide", {}).get("cNome", "") or
                nf.get("emit", {}).get("cRazaoSocial", "") or ""
            )
            valor = float(nf.get("total", {}).get("vNF", 0))
            total_valor += valor
            seg = classificar(nome)
            totais[seg] += valor

        total_pag = resp.get("total_de_paginas", 1)
        print(f"  NF pág {pagina}/{total_pag}: {len(registros)} registros, total R$ {total_valor:,.0f}")
        if pagina >= total_pag:
            break
        pagina += 1

    return totais, total_valor


def montar_dados(fat, fonte="base", total_omie=0):
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
        "total_omie_raw": total_omie,
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
    print(f"[{datetime.now():%H:%M:%S}] Buscando dados do Omie...")

    fat = dict(DADOS_BASE)
    fonte = "base"
    total_omie = 0

    if APP_KEY and APP_SECRET:
        try:
            totais, total_omie = buscar_faturamento_omie()
            if total_omie > 0:
                fat = totais
                fonte = "omie"
                print(f"  ✓ Omie OK — Total: R$ {total_omie:,.2f}")
            else:
                print("  ! Omie retornou zero — usando dados base")
        except Exception as e:
            print(f"  ✗ Erro Omie: {e}")

    cache["dados"]         = montar_dados(fat, fonte, total_omie)
    cache["atualizado_em"] = datetime.now().isoformat()
    cache["erro"]          = None


def loop_atualizacao():
    while True:
        try:
            atualizar_cache()
        except Exception as e:
            print(f"Erro loop: {e}")
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
    return jsonify({
        "online":        True,
        "atualizado_em": cache["atualizado_em"],
        "erro":          cache["erro"],
        "fonte":         cache["dados"]["fonte"] if cache["dados"] else "base",
    })


if __name__ == "__main__":
    t = threading.Thread(target=loop_atualizacao, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
