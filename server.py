"""
server.py — Girus Dashboard Server (Click Forte)
Classifica por marca do produto no Omie
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

# Classificação por marca do produto no Omie
MARCAS_FABRICA = {"GIRUS", "GIRUS INDUSTRIA E COMERCIO DE MOVEIS E DECORACOES LTDA"}
MARCAS_QUIMICA = {"ARTFIX"}
# Todas as outras marcas = ATACADO

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
    if any(f in m for f in ["GIRUS"]):
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


def buscar_pedidos_omie():
    """Busca pedidos de venda autorizados no mês atual agrupados por marca."""
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
                "etapa": "70",  # Faturado
            })
        except Exception:
            break

        pedidos = resp.get("pedido_venda_produto", [])
        if not pedidos:
            break

        for pedido in pedidos:
            cabecalho = pedido.get("cabecalho", {})
            det = pedido.get("det", [])
            for item in det:
                produto = item.get("produto", {})
                marca   = produto.get("marca", "") or ""
                valor   = float(item.get("inf_adic", {}).get("valor_total", 0) or
                                produto.get("valor_total", 0) or 0)
                seg = classificar_marca(marca)
                totais[seg] += valor
                total_geral += valor

        total_pag = resp.get("total_de_paginas", 1)
        print(f"  Pedidos pág {pagina}/{total_pag}: total R$ {total_geral:,.0f}")
        if pagina >= total_pag:
            break
        pagina += 1

    return totais, total_geral


def buscar_nf_omie():
    """Busca NFs emitidas no mês atual agrupadas por marca do produto."""
    mes = datetime.now()
    data_de  = f"01/{mes.strftime('%m/%Y')}"
    data_ate = f"30/{mes.strftime('%m/%Y')}"

    totais = {"fabrica": 0.0, "quimica": 0.0, "atacado": 0.0}
    total_geral = 0.0
    pagina = 1

    while True:
        try:
            resp = omie_post("produtos/nfconsultar", "ListarNF", {
                "pagina": pagina,
                "registros_por_pagina": 50,
                "dDtEmi_De":  data_de,
                "dDtEmi_Ate": data_ate,
                "tpNF": "1",
            })
        except Exception:
            break

        nfs = resp.get("nfCadastro", [])
        if not nfs:
            break

        for nf in nfs:
            itens = nf.get("det", [])
            if itens:
                for item in itens:
                    prod  = item.get("prod", {})
                    marca = prod.get("cMarca", "") or ""
                    valor = float(prod.get("vProd", 0) or 0)
                    seg   = classificar_marca(marca)
                    totais[seg] += valor
                    total_geral += valor
            else:
                # Fallback: usa valor total da NF como atacado
                valor = float(nf.get("total", {}).get("vNF", 0) or 0)
                totais["atacado"] += valor
                total_geral += valor

        total_pag = resp.get("total_de_paginas", 1)
        print(f"  NF pág {pagina}/{total_pag}: total R$ {total_geral:,.0f}")
        if pagina >= total_pag:
            break
        pagina += 1

    return totais, total_geral


def montar_dados(fat, fonte="base", total_omie=0):
    hoje      = datetime.now()
    dias_mes  = 30
    dia_atual = hoje.day
    prog_mes  = round((dia_atual / dias_mes) * 100, 1)
    fat_total = fat["fabrica"] + fat["quimica"] + fat["atacado"]
    mes       = hoje.strftime("%m/%Y")
    return {
        "atualizado_em":  datetime.now().isoformat(),
        "mes":            mes,
        "dia_atual":      dia_atual,
        "dias_mes":       dias_mes,
        "prog_mes":       prog_mes,
        "fonte":          fonte,
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
    print(f"[{datetime.now():%H:%M:%S}] Buscando dados do Omie (Click Forte)...")

    fat = dict(DADOS_BASE)
    fonte = "base"
    total_omie = 0

    if APP_KEY and APP_SECRET:
        # Tenta NFs primeiro
        try:
            totais_nf, total_nf = buscar_nf_omie()
            if total_nf > 0:
                fat = totais_nf
                total_omie = total_nf
                fonte = "omie"
                print(f"  ✓ NFs OK — Fábrica: R${fat['fabrica']:,.0f} | Química: R${fat['quimica']:,.0f} | Atacado: R${fat['atacado']:,.0f}")
            else:
                # Tenta pedidos como fallback
                totais_ped, total_ped = buscar_pedidos_omie()
                if total_ped > 0:
                    fat = totais_ped
                    total_omie = total_ped
                    fonte = "omie-pedidos"
                    print(f"  ✓ Pedidos OK — Total: R${total_ped:,.0f}")
                else:
                    print("  ! Zero registros — usando dados base")
        except Exception as e:
            print(f"  ✗ Erro: {e}")

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
