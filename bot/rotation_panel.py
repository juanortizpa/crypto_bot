"""
Datos para el panel web de la estrategia ROTACION y prueba de conexion con Binance.

  python bot_crypto.py rotation dashboard   -> reports/dashboard[_live].json
  python bot_crypto.py rotation conexion    -> reports/conexion.json

El panel (docs/panel/index.html) es una pagina estatica: lee estos JSON desde
la rama `paper-state` del repositorio, donde los guarda el workflow diario.

Dinero real: Binance rechaza los servidores de GitHub (HTTP 451, estan en
EE.UU.). Por eso GitHub solo DECIDE y publica `orden.json`; el programa
`ejecutor/ejecutor.py`, corriendo en el celular del usuario, envia las ordenes
desde su pais y publica su resultado en `live.json`. Con eso este modulo arma
`dashboard_live.json` para la pestana "Dinero real" del panel.

Privacidad: el repositorio es publico, asi que en modo real los montos en
dolares se omiten salvo que ROT_MOSTRAR_MONTOS=si (se publican solo
porcentajes). La prueba de conexion nunca publica saldos ni claves.
"""
import os
import sys
import csv
import json
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from bot import rotation as R
from bot.logger import log

REPORTS = os.path.join(R.ROOT, "reports")
SHOW_USD = R.MODE == "paper" or os.environ.get("ROT_MOSTRAR_MONTOS", "").lower() in ("si", "sí", "yes", "true", "1")

# referencia fija del backtest (ESTRATEGIA_ROTACION.md): no se recalcula en cada ciclo
BACKTEST = {
    "periodo": "2023 – nov 2026 (validación)",
    "retorno_anual_pct": 28.6, "caida_max_pct": -31.1, "aciertos_pct": 43.5, "payoff": 2.4,
    "mediana_variantes_pct": 26.6,
    "por_anio": [[2019, 1.9], [2020, 103.4], [2021, 97.8], [2022, -10.0], [2023, 96.0], [2024, 34.2], [2025, -3.5], [2026, 3.9]],
}


def _read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _usd(x):
    return round(float(x), 2) if SHOW_USD else None


def export_dashboard():
    """Escribe el JSON que alimenta el panel. No descarga datos: usa los del ciclo recien corrido."""
    import numpy as np
    import pandas as pd
    from backtest.data import load_panel
    from backtest.strategies import rotation

    P = R.PARAMS
    close = load_panel("1d")
    alive = [c for c in close.columns if not pd.isna(close[c].iloc[-1])]
    close = close[alive]
    asof = close.index[-1]
    btc = close["BTCUSDT"]
    ma = btc.rolling(P["regime_ma"]).mean()
    on = btc > ma
    cur = bool(on.iloc[-1])
    days = int((on == cur).iloc[::-1].cumprod().sum())
    W = rotation(close, **P)
    target = {s: round(float(x) * 100, 1) for s, x in W.iloc[-1].items() if x > 0}

    mom = close.iloc[-1] / close.shift(P["mom_n"]).iloc[-1] - 1
    ma50 = close.rolling(P["trend_ma"]).mean().iloc[-1]
    vol = close.pct_change().rolling(P["vol_n"]).std().iloc[-1] * np.sqrt(365)
    rank = []
    for s in mom.dropna().sort_values(ascending=False).index:
        rank.append({"s": s.replace("USDT", ""), "mom": round(float(mom[s]) * 100, 1), "tendencia": bool(close[s].iloc[-1] > ma50[s]),
                     "vol": round(float(vol[s]) * 100), "precio": float(close[s].iloc[-1]), "elegida": s in target})

    # proximo rebalanceo: cierre de la vela del domingo UTC (= lunes 00:00 UTC)
    d = asof + pd.Timedelta(days=1)
    while d.dayofweek != P["weekday"]:
        d += pd.Timedelta(days=1)
    next_reb = (d + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    st = R._load_state()
    syms = sorted(st["holdings"])
    try:
        prices = R._prices(syms) if syms else {}
    except Exception:
        prices = {s: float(close[s].iloc[-1]) for s in syms}
    eq = R._equity(st, prices)
    ini = st.get("initial_capital", R.CAPITAL)
    peak = max(st.get("peak_equity", eq), eq)
    trades = _read_csv(R.TRADES_CSV)
    cost = {}
    for t in trades:                      # precio medio de compra de lo que sigue en cartera
        s, q, u = t["symbol"], float(t["qty"]), float(t["usd"])
        c = cost.setdefault(s, [0.0, 0.0])
        if t["side"] == "BUY":
            c[0] += q
            c[1] += u
        elif c[0] > 0:
            f = max(0.0, 1 - q / c[0])
            c[0] *= f
            c[1] *= f
    hold = []
    for s in syms:
        q = st["holdings"][s]
        v = q * prices[s]
        avg = cost[s][1] / cost[s][0] if s in cost and cost[s][0] > 0 else None
        hold.append({"s": s.replace("USDT", ""), "pct": round(v / eq * 100, 1) if eq else 0, "valor": _usd(v),
                     "precio": prices[s], "entrada": avg, "pnl_pct": round((prices[s] / avg - 1) * 100, 2) if avg else None})
    hist = [{"d": r["date"], "pct": round((float(r["equity"]) / ini - 1) * 100, 2), "equity": _usd(r["equity"]),
             "expo": float(r["exposure_pct"]), "on": r["regime_on"] == "1"} for r in _read_csv(R.EQUITY_CSV)]
    seen = {}
    for h in hist:                        # una fila por dia (la ultima)
        seen[h["d"]] = h
    hist = list(seen.values())[-400:]

    out = {
        "generado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "modo": R.MODE, "montos_visibles": SHOW_USD, "asof": str(asof.date()), "proximo_rebalanceo": next_reb,
        "regimen": {"on": cur, "btc": float(btc.iloc[-1]), "media": float(ma.iloc[-1]),
                    "dist_pct": round((float(btc.iloc[-1]) / float(ma.iloc[-1]) - 1) * 100, 2), "dias": days},
        "btc_serie": [{"d": str(i.date()), "c": round(float(c), 1), "m": round(float(m), 1)}
                      for i, c, m in zip(btc.index[-240:], btc.iloc[-240:], ma.iloc[-240:])],
        "ranking": rank, "objetivo": {k.replace("USDT", ""): v for k, v in target.items()},
        "cartera": {"inicial": _usd(ini), "equity": _usd(eq), "usdt": _usd(st["cash"]),
                    "pnl_pct": round((eq / ini - 1) * 100, 2) if ini else 0.0,
                    "caida_pct": round((eq / peak - 1) * 100, 2) if peak else 0.0,
                    "expo_pct": round((1 - st["cash"] / eq) * 100, 1) if eq else 0.0,
                    "detenido": bool(st.get("halted")), "motivo": st.get("halt_reason"),
                    "inicio": (st.get("started") or "")[:10], "ultimo_cierre": st.get("last_asof"), "posiciones": hold},
        "historial": hist,
        "operaciones": [{"t": t["ts_utc"], "s": t["symbol"].replace("USDT", ""), "lado": t["side"], "usd": _usd(t["usd"]),
                         "precio": float(t["price"]), "motivo": t["reason"]} for t in trades[-60:]][::-1],
        "n_operaciones": len(trades),
        "parametros": {"media_regimen": P["regime_ma"], "momentum": P["mom_n"], "top": P["top_k"], "media_tendencia": P["trend_ma"],
                       "tope_pct": int(P["w_max"] * 100), "freno_pct": int(R.MAX_DD_PCT), "universo": len(alive)},
        "backtest": BACKTEST,
    }
    os.makedirs(REPORTS, exist_ok=True)
    path = os.path.join(REPORTS, f"dashboard{R.SUF}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    log("INFO", f"  [ROT] panel exportado: {path} ({os.path.getsize(path) // 1024} KB)")
    if R.MODE == "paper":
        _export_orden(W, close, cur, asof)
        _export_live_dashboard(out)
    return out


def _export_orden(W, close, regime_on, asof):
    """La decision del dia para el ejecutor del celular. Solo pesos y control; nada privado."""
    modo = os.environ.get("ROT_MODO_REAL", "paper").strip().lower()
    if modo not in ("paper", "live", "salir"):
        modo = "paper"
    w = W.iloc[-1]
    orden = {
        "version": 1,
        "generado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "asof": str(asof.date()),
        "modo": modo,
        "regimen_on": bool(regime_on),
        "pesos": {s: round(float(x), 4) for s, x in w.items() if x > 0},
        "tope_por_moneda": R.PARAMS["w_max"],
        "freno_pct": R.MAX_DD_PCT,
        "universo": sorted(close.columns),
    }
    with open(os.path.join(REPORTS, "orden.json"), "w", encoding="utf-8") as f:
        json.dump(orden, f, ensure_ascii=False, indent=1)
    log("INFO", f"  [ROT] orden publicada: modo={modo} pesos={orden['pesos'] or 'USDT 100%'}")


def _export_live_dashboard(paper):
    """Si el celular ya publico live.json, arma dashboard_live.json con el mercado de hoy y su cartera."""
    src = os.path.join(REPORTS, "live.json")
    dst = os.path.join(REPORTS, "dashboard_live.json")
    if not os.path.exists(src):
        if os.path.exists(dst):
            os.remove(dst)
        return
    try:
        with open(src, encoding="utf-8") as f:
            live = json.load(f)
        out = dict(paper)
        out.update(modo="live", montos_visibles=bool(live.get("montos_visibles")),
                   cartera=live["cartera"], historial=live.get("historial", []),
                   operaciones=live.get("operaciones", []), n_operaciones=live.get("n_operaciones", 0),
                   ejecutor=live.get("ejecutor", {}), generado_utc=live.get("actualizado_utc", paper["generado_utc"]))
        with open(dst, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
        log("INFO", "  [ROT] panel de dinero real actualizado con el reporte del celular")
    except Exception as e:
        log("WARN", f"  [ROT] live.json ilegible, se ignora: {e}")


def conexion():
    """
    Prueba de conexion con Binance desde donde corre el bot. Solo LEE: no envia ordenes.
    Publica unicamente indicadores si/no (nunca saldos ni claves).
    """
    import urllib.request
    import urllib.error
    import binance_client as bc

    res = {"probado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "pasos": [], "listo": False}

    def paso(nombre, ok, detalle):
        res["pasos"].append({"nombre": nombre, "ok": ok, "detalle": detalle})
        log("INFO" if ok else "WARN", f"  [CONEXION] {'OK ' if ok else 'NO '} {nombre}: {detalle}")
        return ok

    # 1. Binance acepta conexiones desde este servidor? (bloquea algunas regiones, p. ej. IPs de EE.UU.)
    try:
        with urllib.request.urlopen(urllib.request.Request(bc.LIVE_URL + "/api/v3/ping", headers={"User-Agent": "CryptoBot/1.0"}), timeout=15) as r:
            alcanzable = paso("Binance responde desde este servidor", r.status == 200, f"HTTP {r.status}")
    except urllib.error.HTTPError as e:
        cuerpo = e.read().decode(errors="replace")[:160]
        motivo = "Binance bloquea la región de este servidor" if e.code in (451, 403) else "respuesta inesperada"
        alcanzable = paso("Binance responde desde este servidor", False, f"HTTP {e.code}: {motivo}. {cuerpo}")
    except Exception as e:
        alcanzable = paso("Binance responde desde este servidor", False, f"sin respuesta: {e}")

    tiene = bool(bc.ENV["BINANCE_API_KEY"] and bc.ENV["BINANCE_SECRET_KEY"])
    paso("Claves guardadas en GitHub", tiene, "BINANCE_API_KEY y BINANCE_API_SECRET presentes" if tiene else "faltan los secretos BINANCE_API_KEY y/o BINANCE_API_SECRET")

    if alcanzable and tiene:
        bc.ENV["BINANCE_MODE"] = "live"
        acct = bc._request("GET", "/api/v3/account", signed=True)
        if isinstance(acct, dict) and "balances" in acct and "error" not in acct:
            paso("Las claves son válidas", True, "Binance aceptó la firma")
            can_trade = bool(acct.get("canTrade"))
            paso("Permiso de operar en Spot", can_trade, "activo" if can_trade else "activa 'Enable Spot & Margin Trading' en la clave")
            usdt = sum(float(b["free"]) for b in acct["balances"] if b["asset"] == "USDT")
            need = R.CAPITAL
            paso("USDT suficiente para el capital configurado", usdt >= need,
                 f"hay al menos {need:.0f} USDT libres" if usdt >= need else f"faltan USDT libres para cubrir ROT_CAPITAL_REAL={need:.0f}")
            rest = bc._request("GET", "/sapi/v1/account/apiRestrictions", signed=True)
            if isinstance(rest, dict) and "enableWithdrawals" in rest:
                paso("Retiros desactivados en la clave", not rest["enableWithdrawals"],
                     "correcto: la clave no puede retirar fondos" if not rest["enableWithdrawals"] else "PELIGRO: desactiva 'Enable Withdrawals' en la clave")
                res["listo"] = can_trade and usdt >= need and not rest["enableWithdrawals"]
            else:
                paso("Retiros desactivados en la clave", False, "no se pudo comprobar; revísalo a mano en Binance")
        else:
            msg = str(acct.get("msg", acct.get("error", "")))[:160] if isinstance(acct, dict) else "respuesta vacía"
            paso("Las claves son válidas", False, f"Binance las rechazó: {msg}")
    os.makedirs(REPORTS, exist_ok=True)
    with open(os.path.join(REPORTS, "conexion.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("LISTO PARA OPERAR" if res["listo"] else "TODAVÍA NO ESTÁ LISTO: revisa los pasos marcados NO")
    return res
