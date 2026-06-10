"""
server.py — Girus Dashboard Server
────────────────────────────────────
Servidor Flask que:
- Busca dados do Omie a cada 1 hora
- Serve o dashboard com proteção por senha
- Mantém as credenciais Omie APENAS no servidor (nunca expostas)
"""

import os
import json
import time
import threading
import requests
from datetime import datetime
from functools import wraps
from flask import Flask, jsonify, request, Response, send_from_directory

app = Flask(__name__, static_folder="static")

# ── CREDENCIAIS (ficam só no Railway via variáveis de ambiente) ──
APP_KEY      = os.environ.get("OMIE_APP_KEY", "")
APP_SECRET   = os.environ.get("OMIE_APP_SECRET", "")
DASH_USER    = os.environ.get("DASH_USER", "girus")
DASH_PASS    = os.environ.get("DASH_PASS", "")  # você define no Railway

# ── PREVISÃO MENSAL FIXA (Relatório Geral) ──────────────────────
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

# Cache em memória (não precisa de banco de dados)
cache = {
    "dados":         None,
    "atualizado_em": None,
    "erro":          None,
}

BASE_URL = "https://app.omie.com.br/api/v1"
HEADERS  = {"Content-Type": "application/json"}


# ── AUTENTICAÇÃO BÁSICA ─────────────────────────────────────────
def requer_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or auth.username != DASH_USER or auth.password != DASH_PASS:
            return Response(
                "Acesso restrito. Informe usuário e senha.",
                401,
                {"WWW-Authenticate": 'Basic realm="Girus Dashboard"'}
            )
        return f(*args, **kwargs)
    return decorated


# ── FUNÇÕES OMIE ────────────────────────────────────────────────
def omie_post(endpoint: str, call: str, params: dict) -> dict:
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


def classificar(nome: str) -> str:
    n = nome.upper()
    if "GIRUS" in n or "INDUSMOV" in n:
        return "fabrica"
    if "ARTFIX" in n:
        return "quimica"
    return "atacado"


def buscar_faturamento_omie() -> dict:
    """Busca NFs emitidas no mês atual e agrupa por segmento."""
    mes = mes_atual()
    totais = {"fabrica": 0.0, "quimica": 0.0, "atacado": 0.0}
    pagina = 1

    while True:
        resp = omie_post("produtos/nfconsultar", "ListarNF", {
            "pagina": pagina,
            "registros_por_pagina": 100,
            "dDtEmi_De":  f"01/{mes}",
            "dDtEmi_Ate": f"31/{mes}",
        })

        nfs = resp.get("nfCadastro", [])
        if not nfs:
            break

        for nf in nfs:
            cliente = nf.get("compl", {}).get("nNF", "")
            # Tenta pegar nome do emitente/destinatário para classificar
            nome = nf.get("ide", {}).get("cNome", "") or ""
            valor = float(nf.get("total", {}).get("vNF", 0))
            segmento = classificar(nome)
            totais[segmento] += valor

        total_pag = resp.get("total_de_paginas", 1)
        if pagina >= total_pag:
            break
        pagina += 1

    return totais


def buscar_despesas_omie() -> dict:
    """Busca contas a pagar pagas no mês atual."""
    mes = mes_atual()
    desp = {"fixas": 0.0, "impostos": 0.0, "colaboradores": 0.0}
    pagina = 1

    while True:
        resp = omie_post("financas/contapagar", "ListarContasPagar", {
            "pagina": pagina,
            "registros_por_pagina": 100,
            "filtrar_por_status":   "LIQUIDADO",
            "filtrar_por_data_de":  f"01/{mes}",
            "filtrar_por_data_ate": f"31/{mes}",
        })

        contas = resp.get("conta_pagar_cadastro", [])
        if not contas:
            break

        for c in contas:
            categoria = (c.get("descricao_categoria") or "").upper()
            valor     = float(c.get("valor_documento", 0))

            if any(x in categoria for x in ["SALARIO", "FOLHA", "COLABORADOR", "RH"]):
                desp["colaboradores"] += valor
            elif any(x in categoria for x in ["IMPOSTO", "TRIBUTO", "ICMS", "PIS", "COFINS", "ISS"]):
                desp["impostos"] += valor
            else:
                desp["fixas"] += valor

        total_pag = resp.get("total_de_paginas", 1)
        if pagina >= total_pag:
            break
        pagina += 1

    return desp


def atualizar_cache():
    """Busca todos os dados do Omie e atualiza o cache."""
    global cache
    try:
        print(f"[{datetime.now():%H:%M:%S}] Atualizando dados do Omie...")

        fat   = buscar_faturamento_omie()
        desp  = buscar_despesas_omie()

        fat_total = fat["fabrica"] + fat["quimica"] + fat["atacado"]

        # Dias do mês
        hoje      = datetime.now()
        dias_mes  = 30
        dia_atual = hoje.day
        prog_mes  = dia_atual / dias_mes

        cache["dados"] = {
            "atualizado_em": datetime.now().isoformat(),
            "mes":           mes_atual(),
            "dia_atual":     dia_atual,
            "dias_mes":      dias_mes,
            "prog_mes":      round(prog_mes * 100, 1),

            "faturamento": {
                "fabrica": fat["fabrica"],
                "quimica": fat["quimica"],
                "atacado": fat["atacado"],
                "total":   fat_total,
            },

            "despesas_real": {
                "colaboradores": desp["colaboradores"] or None,
                "fixas":         desp["fixas"]         or None,
                "impostos":      desp["impostos"]      or None,
            },

            "previsao":  PREVISAO,
            "metas":     METAS,
        }
        cache["atualizado_em"] = datetime.now().isoformat()
        cache["erro"]          = None
        print(f"  ✓ Faturamento total: R$ {fat_total:,.2f}")

    except Exception as e:
        cache["erro"] = str(e)
        print(f"  ✗ Erro: {e}")


def loop_atualizacao():
    """Roda em background, atualiza a cada 1 hora."""
    while True:
        atualizar_cache()
        time.sleep(3600)  # 1 hora


# ── ROTAS ───────────────────────────────────────────────────────
@app.route("/")
@requer_auth
def index():
    return send_from_directory("static", "index.html")


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
        "online":        True,
        "atualizado_em": cache["atualizado_em"],
        "erro":          cache["erro"],
        "proximo_em":    "em até 1 hora",
    })


# ── INICIALIZAÇÃO ───────────────────────────────────────────────
if __name__ == "__main__":
    # Primeira busca ao iniciar
    t = threading.Thread(target=loop_atualizacao, daemon=True)
    t.start()

    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
