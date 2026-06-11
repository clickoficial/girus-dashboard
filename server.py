"""
server.py — Dashboard de Custos · Click Forte
v3 (06/2026)

Fonte de faturamento: Pedidos de Venda do Omie (ListarPedidos),
alinhado ao relatorio "Andy — Faturamento por Produto" (situacao Autorizado).

Mudancas v3:
- Metas em rampa mensal Jun-Dez/2026 (R$ 20M -> R$ 30M)
- Artfix com rampa propria (R$ 0,8M -> R$ 3,0M)
- Imposto = 10% sobre o faturamento (dinamico), nao mais valor fixo
- Folha com crescimento de 5% ao mes a partir de Jul/2026; fixas congeladas
- Resultado previsto considera margem bruta por segmento
- Exclui pedidos cancelados; usa o numero correto de dias do mes
- Fuso horario de Sao Paulo para a virada de dia/mes
"""

import os
import sys

# Logs sem buffer (gunicorn/Railway)
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass
import time
import calendar
import threading
import requests
from datetime import datetime
from functools import wraps
from flask import Flask, jsonify, request, Response, send_file

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("America/Sao_Paulo")
except Exception:
    TZ = None


def agora():
    return datetime.now(TZ) if TZ else datetime.now()


app = Flask(__name__)

APP_KEY = os.environ.get("OMIE_APP_KEY", "")
APP_SECRET = os.environ.get("OMIE_APP_SECRET", "")
DASH_USER = os.environ.get("DASH_USER", "girus")
DASH_PASS = os.environ.get("DASH_PASS", "")

# ----------------- Premissas financeiras -----------------

ALIQUOTA_IMPOSTO = 0.10          # 10% sobre o faturamento real
FIXAS_MENSAIS = 1610000.00       # congeladas (espaco fisico ja existe)
FOLHA_BASE = 1572000.00          # Junho/2026
FOLHA_CRESC_MES = 0.05           # +5% ao mes a partir de Julho/2026
ANO_MES_BASE = (2026, 6)

MARGENS = {"fabrica": 0.50, "quimica": 0.30, "atacado": 0.30}

# Rampa de metas — total da empresa e rampa propria da Artfix (quimica)
RAMPA = {
    "2026-06": {"total": 20000000.00, "quimica": 800000.00},
    "2026-07": {"total": 21500000.00, "quimica": 1200000.00},
    "2026-08": {"total": 23000000.00, "quimica": 1600000.00},
    "2026-09": {"total": 25000000.00, "quimica": 2000000.00},
    "2026-10": {"total": 26500000.00, "quimica": 2400000.00},
    "2026-11": {"total": 28000000.00, "quimica": 2700000.00},
    "2026-12": {"total": 30000000.00, "quimica": 3000000.00},
}
# Divisao do restante entre Girus e Atacado (mix observado em Jun/2026)
SPLIT_GIRUS = 0.654
SPLIT_ATACADO = 0.346

# Ultimo valor conhecido, usado apenas se a API do Omie falhar
DADOS_FALLBACK = {
    "fabrica": 4732976.72,
    "quimica": 300215.60,
    "atacado": 2504858.65,
}

cache = {"dados": None, "atualizado_em": None, "erro": None}
BASE_URL = "https://app.omie.com.br/api/v1"
HEADERS = {"Content-Type": "application/json"}


def requer_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or auth.username != DASH_USER or auth.password != DASH_PASS:
            return Response(
                "Acesso restrito.",
                401,
                {"WWW-Authenticate": 'Basic realm="Click Forte Dashboard"'}
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


def chave_mes(dt):
    return "%04d-%02d" % (dt.year, dt.month)


def metas_do_mes(dt):
    chaves = sorted(RAMPA.keys())
    chave = chave_mes(dt)
    if chave < chaves[0]:
        chave = chaves[0]
    elif chave > chaves[-1]:
        chave = chaves[-1]
    r = RAMPA[chave]
    resto = r["total"] - r["quimica"]
    return {
        "fabrica": round(resto * SPLIT_GIRUS, 2),
        "quimica": round(r["quimica"], 2),
        "atacado": round(resto * SPLIT_ATACADO, 2),
        "total": round(r["total"], 2),
    }


def folha_do_mes(dt):
    n = (dt.year - ANO_MES_BASE[0]) * 12 + (dt.month - ANO_MES_BASE[1])
    n = max(0, min(n, 18))
    return round(FOLHA_BASE * ((1 + FOLHA_CRESC_MES) ** n), 2)


def omie_post(endpoint, call, params):
    payload = {
        "call": call,
        "app_key": APP_KEY,
        "app_secret": APP_SECRET,
        "param": [params]
    }
    r = requests.post(
        "%s/%s/" % (BASE_URL, endpoint),
        headers=HEADERS, json=payload, timeout=30
    )
    r.raise_for_status()
    return r.json()


def buscar_faturamento_por_marca():
    """
    Busca pedidos de venda do mes vigente no Omie e agrupa por marca
    (GIRUS / ARTFIX / demais). Ignora pedidos cancelados.
    """
    hoje = agora()
    ultimo_dia = calendar.monthrange(hoje.year, hoje.month)[1]
    data_de = "01/" + hoje.strftime("%m/%Y")
    data_ate = "%02d/%s" % (ultimo_dia, hoje.strftime("%m/%Y"))

    totais = {"fabrica": 0.0, "quimica": 0.0, "atacado": 0.0}
    total_geral = 0.0
    cancelados = 0
    pagina = 1

    while True:
        try:
            resp = omie_post("produtos/pedido", "ListarPedidos", {
                "pagina": pagina,
                "registros_por_pagina": 200,
                "filtrar_por_data_de": data_de,
                "filtrar_por_data_ate": data_ate,
                "apenas_importado_api": "N",
            })
        except Exception as e:
            print("  Erro pedidos pag %s: %s" % (pagina, e))
            break

        pedidos = resp.get("pedido_venda_produto", []) or []
        if not pedidos:
            break

        for pedido in pedidos:
            info = pedido.get("infoCadastro", {}) or {}
            if str(info.get("cancelado", "N")).upper() == "S":
                cancelados += 1
                continue
            for item in (pedido.get("det", []) or []):
                prod = item.get("produto", {}) or {}
                marca = prod.get("marca", "") or ""
                valor = prod.get("valor_mercadoria")
                if valor in (None, "", 0, "0"):
                    try:
                        valor = (float(prod.get("quantidade") or 0)
                                 * float(prod.get("valor_unitario") or 0))
                    except (TypeError, ValueError):
                        valor = 0.0
                try:
                    valor = float(valor or 0)
                except (TypeError, ValueError):
                    valor = 0.0
                seg = classificar_marca(marca)
                totais[seg] += valor
                total_geral += valor

        total_pag = int(resp.get("total_de_paginas", 1) or 1)
        print("  Pedidos pag %s/%s — R$ %s | cancelados ignorados: %s"
              % (pagina, total_pag, format(total_geral, ",.0f"), cancelados))
        if pagina >= total_pag:
            break
        pagina += 1

    return totais, total_geral


def montar_dados(fat, fonte="manual"):
    hoje = agora()
    dias_mes = calendar.monthrange(hoje.year, hoje.month)[1]
    dia = hoje.day
    prog = round(dia / dias_mes * 100.0, 1)

    fat = {k: float(fat.get(k, 0) or 0) for k in ("fabrica", "quimica", "atacado")}
    fat_total = fat["fabrica"] + fat["quimica"] + fat["atacado"]

    metas = metas_do_mes(hoje)
    folha = folha_do_mes(hoje)
    imposto_prev = round(metas["total"] * ALIQUOTA_IMPOSTO, 2)
    custos_prev = round(folha + FIXAS_MENSAIS + imposto_prev, 2)

    lucro_bruto_meta = 0.0
    for s in MARGENS:
        lucro_bruto_meta += metas[s] * MARGENS[s]
    resultado_previsto = round(lucro_bruto_meta - custos_prev, 2)

    fator = (float(dias_mes) / dia) if dia else 1.0
    fat_proj = {}
    for s in fat:
        fat_proj[s] = round(fat[s] * fator, 2)
    fat_proj_total = round(fat_total * fator, 2)

    imposto_real = round(fat_total * ALIQUOTA_IMPOSTO, 2)
    imposto_proj = round(fat_proj_total * ALIQUOTA_IMPOSTO, 2)

    lucro_bruto_proj = 0.0
    for s in MARGENS:
        lucro_bruto_proj += fat_proj[s] * MARGENS[s]
    resultado_projetado = round(
        lucro_bruto_proj - folha - FIXAS_MENSAIS - imposto_proj, 2)

    rampa_lista = []
    for chave in sorted(RAMPA.keys()):
        ano, mes_n = chave.split("-")
        rampa_lista.append({
            "mes": "%s/%s" % (mes_n, ano),
            "total": RAMPA[chave]["total"],
            "quimica": RAMPA[chave]["quimica"],
            "atual": (int(ano) == hoje.year and int(mes_n) == hoje.month),
        })

    fat_saida = dict(fat)
    fat_saida["total"] = round(fat_total, 2)
    fat_proj_saida = dict(fat_proj)
    fat_proj_saida["total"] = fat_proj_total

    return {
        "atualizado_em": agora().isoformat(),
        "mes": hoje.strftime("%m/%Y"),
        "dia_atual": dia,
        "dias_mes": dias_mes,
        "prog_mes": prog,
        "fonte": fonte,
        "aliquota_imposto": ALIQUOTA_IMPOSTO,
        "margens": MARGENS,
        "faturamento": fat_saida,
        "faturamento_proj": fat_proj_saida,
        "metas": metas,
        "previsao": {
            "colaboradores": folha,
            "fixas": FIXAS_MENSAIS,
            "impostos": imposto_prev,
            "custos_total": custos_prev,
            "faturamento": metas["total"],
        },
        "real": {
            "impostos": imposto_real,
            "impostos_proj": imposto_proj,
        },
        "resultado": {
            "previsto": resultado_previsto,
            "projetado": resultado_projetado,
            "lucro_bruto_meta": round(lucro_bruto_meta, 2),
        },
        "rampa": rampa_lista,
    }


def atualizar_cache():
    global cache
    print("[%s] Atualizando — %s" % (agora().strftime("%H:%M:%S"),
                                     agora().strftime("%m/%Y")))
    fat = dict(DADOS_FALLBACK)
    fonte = "omie-manual"

    if APP_KEY and APP_SECRET:
        try:
            totais, total = buscar_faturamento_por_marca()
            if total > 0:
                fat = totais
                fonte = "omie"
                print("  OK — Fabrica: R$%s | Quimica: R$%s | Atacado: R$%s"
                      % (format(fat["fabrica"], ",.0f"),
                         format(fat["quimica"], ",.0f"),
                         format(fat["atacado"], ",.0f")))
            else:
                print("  ! API retornou zero — usando ultimo valor conhecido")
        except Exception as e:
            print("  Erro API: %s — usando ultimo valor conhecido" % e)

    cache["dados"] = montar_dados(fat, fonte)
    cache["atualizado_em"] = agora().isoformat()
    cache["erro"] = None
    total = fat["fabrica"] + fat["quimica"] + fat["atacado"]
    print("  Total: R$ %s | Fonte: %s" % (format(total, ",.2f"), fonte))


def loop_atualizacao():
    while True:
        try:
            atualizar_cache()
        except Exception as e:
            print("Erro loop: %s" % e)
            if cache["dados"] is None:
                cache["dados"] = montar_dados(dict(DADOS_FALLBACK))
        time.sleep(3600)


@app.route("/")
@requer_auth
def index():
    return send_file("index.html")


@app.route("/api/dados")
@requer_auth
def api_dados():
    if cache["dados"] is None:
        return jsonify({"status": "ok",
                        "dados": montar_dados(dict(DADOS_FALLBACK))})
    return jsonify({"status": "ok", "dados": cache["dados"]})


@app.route("/api/status")
@requer_auth
def api_status():
    return jsonify({
        "online": True,
        "atualizado_em": cache["atualizado_em"],
        "erro": cache["erro"],
        "fonte": cache["dados"]["fonte"] if cache["dados"] else "manual",
    })


# Inicia a rotina de atualizacao no import do modulo.
# Necessario porque o Railway roda o app via gunicorn, que NUNCA executa
# o bloco __main__ — sem isso a busca no Omie nunca acontece.
_loop_iniciado = False


def iniciar_loop():
    global _loop_iniciado
    if not _loop_iniciado:
        _loop_iniciado = True
        threading.Thread(target=loop_atualizacao, daemon=True).start()


iniciar_loop()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
