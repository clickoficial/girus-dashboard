"""
server.py — Girus Dashboard Server
Dados reais de Junho/2026 da Click Forte
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

# Metas mensais por segmento
METAS = {
    "fabrica": 3703866.22,
    "quimica":  265949.40,
    "atacado": 2109381.40,
}

# Dados reais de Junho/2026 (fonte: Omie Click Forte por marca)
DADOS_JUNHO = {
    "fabrica": 4732976.72,   # GIRUS INDUSTRIA E COMERCIO DE MOVEIS
    "quimica":  300215.60,   # ARTFIX
    "atacado": 2504858.65,   # Demais marcas/fornecedores
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


def classificar_marca(marca):
    m = (marca or "").upper().strip()
    if "GIRUS" in m:
        return "fabrica"
    if "ARTFIX" in m:
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


def buscar_faturamento_por_marca():
    """
    Busca pedidos de venda autorizados no mês atual.
    Agrupa por marca do produto (GIRUS / ARTFIX / outros).
    """
    mes = datetime.now()
    data_de  = f"01/{mes.strftime('%m/%Y')}"
    data_ate = f"30/{mes.strftime('%m/%Y')}"

    totais = {"fabrica": 0.0, "quimica": 0.0, "atacado": 0.0}
    total_geral = 0.0
    pagina = 1

    while True:
        try:
            resp = omie_post("produtos/pedido", "ListarPedidos", {
                "pagina": pagina,
                "registros_por_pagina": 50,
                "filtrar_por_data_de":  data_de,
                "filtrar_por_data_ate": data_ate,
                "apenas_importado_api": "N",
            })
        except Exception as e:
            print(f"  Erro pedidos pág {pagina}: {e}")
            break

        pedidos = resp.get("pedido_venda_produto", [])
        if not pedidos:
            break

        for pedido in pedidos:
            itens = pedido.get("det", [])
            for item in itens:
                prod  = item.get("produto", {})
                marca = prod.get("marca", "") or ""
                valor = float(prod.get("valor_mercadoria", 0) or
                              prod.get("valor_total", 0) or 0)
                seg = classificar_marca(marca)
                totais[seg] += valor
                total_geral += valor

        total_pag = resp.get("total_de_paginas", 1)
        print(f"  Pedidos pág {pagina}/{total_pag} — R$ {total_geral:,.0f}")
        if pagina >= total_pag:
            break
        pagina += 1

    return totais, total_geral


def montar_dados(fat, fonte="manual"):
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
    mes_atual = datetime.now().strftime("%m/%Y")
    print(f"[{datetime.now():%H:%M:%S}] Atualizando — {mes_atual}")

    fat   = dict(DADOS_JUNHO)
    fonte = "omie-manual"

    # Tenta buscar dados reais via API
    if APP_KEY and APP_SECRET:
        try:
            totais, total = buscar_faturamento_por_marca()
            if total > 0:
                fat   = totais
                fonte = "omie"
                print(f"  ✓ API OK — Fábrica: R${fat['fabrica']:,.0f} | Química: R${fat['quimica']:,.0f} | Atacado: R${fat['atacado']:,.0f}")
            else:
                print(f"  ! API retornou zero — usando dados manuais de Junho")
        except Exception as e:
            print(f"  ✗ Erro API: {e} — usando dados manuais")

    cache["dados"]         = montar_dados(fat, fonte)
    cache["atualizado_em"] = datetime.now().isoformat()
    cache["erro"]          = None
    total = fat["fabrica"] + fat["quimica"] + fat["atacado"]
    print(f"  Total: R$ {total:,.2f} | Fonte: {fonte}")


def loop_atualizacao():
    while True:
        try:
            atualizar_cache()
        except Exception as e:
            print(f"Erro loop: {e}")
            if cache["dados"] is None:
                cache["dados"] = montar_dados(dict(DADOS_JUNHO))
        time.sleep(3600)


@app.route("/")
@requer_auth
def index():
    return send_file("index.html")


@app.route("/api/dados")
@requer_auth
def api_dados():
    if cache["dados"] is None:
        return jsonify({"status": "ok", "dados": montar_dados(dict(DADOS_JUNHO))})
    return jsonify({"status": "ok", "dados": cache["dados"]})


@app.route("/api/status")
@requer_auth
def api_status():
    return jsonify({
        "online":        True,
        "atualizado_em": cache["atualizado_em"],
        "erro":          cache["erro"],
        "fonte":         cache["dados"]["fonte"] if cache["dados"] else "manual",
    })


if __name__ == "__main__":
    t = threading.Thread(target=loop_atualizacao, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
