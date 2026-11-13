"""
Estrategia ROTACION — rotacion semanal por momentum con filtro de regimen BTC.

Es la unica estrategia del proyecto con ventaja medida en backtest con costes
y validada fuera de muestra (ver ESTRATEGIA_ROTACION.md y `backtest/`).

Reglas (identicas a backtest.strategies.rotation, misma funcion):
  1. Regimen: si BTC cierra bajo su media de 100 dias -> todo a USDT.
  2. Una vez por semana (cierre diario del domingo UTC = lunes 00:00 UTC):
     comprar las 3 monedas con mayor retorno a 30 dias que esten sobre su
     media de 50 dias.
  3. Tamano por volatilidad inversa, exposicion total escalada a ~50% de
     volatilidad anual, maximo 40% del capital en una sola moneda y nunca
     mas del 100% en total (sin apalancamiento).

Modos:
  paper   (default)  simula ordenes con comision+deslizamiento, sin tocar Binance.
  execute            envia ordenes MARKET al entorno de BINANCE_MODE (testnet/live).
                     Requiere --execute Y AUTO_EXECUTE=True en .env.

El bot solo gestiona el presupuesto ROT_CAPITAL y las monedas que el mismo
compro (estado propio en state/rotation_state.json): nunca toca otros saldos.

CLI:  python bot_crypto.py rotation status|once|run|backtest|reset [--execute]
"""
import os
import sys
import csv
import json
import time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from bot.logger import log

ROOT = os.path.dirname(os.path.dirname(__file__))
# ROT_MODE=live usa archivos propios (sufijo _live): la cartera real nunca se
# mezcla con la simulada, y ambas pueden correr en paralelo.
MODE = "live" if os.environ.get("ROT_MODE", "paper").lower() == "live" else "paper"
SUF = "_live" if MODE == "live" else ""
STATE_PATH = os.path.join(ROOT, "state", f"rotation_state{SUF}.json")
TRADES_CSV = os.path.join(ROOT, "reports", f"rotation_trades{SUF}.csv")
EQUITY_CSV = os.path.join(ROOT, "reports", f"rotation_equity{SUF}.csv")

# Parametros de la estrategia. NO se optimizaron al mejor resultado: son los
# valores por defecto fijados antes de mirar la validacion, y 216 variantes
# vecinas dieron todas resultado positivo fuera de muestra.
PARAMS = dict(regime_ma=100, mom_n=30, top_k=3, trend_ma=50, vol_n=30,
              port_vol=0.50, weekday=6, w_max=0.40)

CAPITAL = float(os.environ.get("ROT_CAPITAL", os.environ.get("CRYPTO_PORTFOLIO", "1000")))
MAX_DD_PCT = float(os.environ.get("ROT_MAX_DD_PCT", "40"))       # kill switch
MIN_TRADE_USD = float(os.environ.get("ROT_MIN_TRADE_USD", "10"))
MIN_TRADE_FRAC = 0.02      # ignorar ajustes menores al 2% del capital
PAPER_FEE = 0.0010
PAPER_SLIP = 0.0005
RUN_AT_UTC = (0, 5)        # hora diaria de ejecucion: 00:05 UTC (tras el cierre diario)


# ── estado ────────────────────────────────────────────────────────────

def _load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"cash": CAPITAL, "holdings": {}, "peak_equity": CAPITAL,
            "initial_capital": CAPITAL, "halted": False, "halt_reason": None,
            "last_target": {}, "last_asof": None, "started": datetime.now(timezone.utc).isoformat()}


def _save_state(st):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=2)
    os.replace(tmp, STATE_PATH)


def _append_csv(path, header, row):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(header)
        w.writerow(row)


# ── senal ─────────────────────────────────────────────────────────────

def compute_targets(refresh=True):
    """
    Devuelve dict con los pesos objetivo vigentes tras el ultimo cierre diario.
    Usa exactamente la misma funcion que el backtest.
    """
    import pandas as pd
    from backtest.data import UNIVERSE, download, load_panel
    from backtest.strategies import rotation

    if refresh:
        for s in UNIVERSE:
            try:
                download(s, "1d", verbose=False)
            except Exception as e:
                log("WARN", f"  rotation: no se pudo actualizar {s}: {e}")
    close = load_panel("1d")
    asof = close.index[-1]
    expected = (pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta(days=1))
    if asof < expected:
        raise RuntimeError(f"datos atrasados: ultima vela {asof.date()}, se esperaba {expected.date()}")
    if pd.isna(close["BTCUSDT"].iloc[-1]):
        raise RuntimeError("sin vela de BTC para el ultimo dia")
    # solo monedas que siguen cotizando (excluye deslistadas como EOS/MATIC)
    alive = [c for c in close.columns if not pd.isna(close[c].iloc[-1])]
    close = close[alive]
    W = rotation(close, **PARAMS)
    w = W.iloc[-1]
    btc = close["BTCUSDT"]
    ma = btc.rolling(PARAMS["regime_ma"]).mean().iloc[-1]
    return {
        "asof": str(asof.date()),
        "regime_on": bool(btc.iloc[-1] > ma),
        "btc_close": float(btc.iloc[-1]),
        "btc_ma": float(ma),
        "weights": {s: round(float(x), 4) for s, x in w.items() if x > 0},
    }


# ── ejecucion ─────────────────────────────────────────────────────────

def _prices(symbols):
    from binance_client import get_all_tickers
    allp = get_all_tickers()
    out = {s: allp.get(s) for s in symbols}
    missing = [s for s, p in out.items() if not p]
    if missing:
        raise RuntimeError(f"sin precio para {missing}")
    return out


def _equity(st, prices):
    return st["cash"] + sum(q * prices[s] for s, q in st["holdings"].items())


def _fill(st, sym, side, usd, price, execute):
    """Ejecuta (o simula) una orden MARKET. Devuelve (qty, usd_neto) o None."""
    if execute:
        import binance_client as bc
        info = bc.get_symbol_info(sym)
        if not info:
            log("WARN", f"  rotation: sin filtros de {sym}, orden omitida")
            return None
        qty = bc._round_step(usd / price, info["step_size"])
        if side == "SELL":
            qty = min(qty, bc._round_step(st["holdings"].get(sym, 0.0), info["step_size"]))
        if qty < info["min_qty"] or qty * price < info["min_notional"]:
            log("INFO", f"  rotation: {side} {sym} ${usd:.2f} bajo el minimo de Binance, omitida")
            return None
        resp = bc.place_order(sym, side, "MARKET", quantity=qty)
        if not isinstance(resp, dict) or "error" in resp or resp.get("status") not in ("FILLED", "PARTIALLY_FILLED"):
            log("ERROR", f"  rotation: orden {side} {sym} rechazada: {resp}")
            return None
        f_qty = float(resp.get("executedQty", 0))
        f_usd = float(resp.get("cummulativeQuoteQty", 0))
        # comision: si se cobra en la moneda comprada, se recibe algo menos
        fee_base = sum(float(x.get("commission", 0)) for x in resp.get("fills", [])
                       if x.get("commissionAsset") == sym.replace("USDT", ""))
        fee_usdt = sum(float(x.get("commission", 0)) for x in resp.get("fills", [])
                       if x.get("commissionAsset") == "USDT")
        if side == "BUY":
            return f_qty - fee_base, f_usd
        return f_qty, f_usd - fee_usdt
    # paper
    if side == "BUY":
        px = price * (1 + PAPER_SLIP)
        qty = usd * (1 - PAPER_FEE) / px
        return qty, usd
    px = price * (1 - PAPER_SLIP)
    qty = min(usd / price, st["holdings"].get(sym, 0.0))
    return qty, qty * px * (1 - PAPER_FEE)


def _trade(st, sym, side, usd, price, execute, reason):
    res = _fill(st, sym, side, usd, price, execute)
    if not res:
        return
    qty, net = res
    if side == "BUY":
        st["cash"] -= net
        st["holdings"][sym] = st["holdings"].get(sym, 0.0) + qty
    else:
        st["cash"] += net
        left = st["holdings"].get(sym, 0.0) - qty
        if left * price < 1.0:      # polvo
            st["holdings"].pop(sym, None)
        else:
            st["holdings"][sym] = left
    mode = "EXEC" if execute else "PAPER"
    log("INFO", f"  [ROT {mode}] {side} {sym} qty={qty:.8g} ~${net:.2f} @ {price:.6g} ({reason})")
    _append_csv(TRADES_CSV, ["ts_utc", "mode", "symbol", "side", "qty", "usd", "price", "reason"],
                [datetime.now(timezone.utc).isoformat(timespec="seconds"), mode, sym, side,
                 f"{qty:.10g}", f"{net:.2f}", f"{price:.8g}", reason])


def _liquidate(st, prices, execute, reason):
    for sym in list(st["holdings"].keys()):
        q = st["holdings"][sym]
        _trade(st, sym, "SELL", q * prices[sym], prices[sym], execute, reason)


def step(execute=False, refresh=True):
    """Un ciclo diario: calcula objetivo y ajusta la cartera si cambio."""
    if execute and os.environ.get("AUTO_EXECUTE", "False").lower() != "true":
        raise RuntimeError("--execute requiere AUTO_EXECUTE=True en .env")
    st = _load_state()
    # salida manual (ROT_LIQUIDAR=si): vender todo a USDT y detenerse
    if os.environ.get("ROT_LIQUIDAR", "").lower() in ("si", "sí", "1", "true", "yes"):
        syms = sorted(st["holdings"])
        if syms:
            _liquidate(st, _prices(syms), execute, "LIQUIDACION")
        st["halted"] = True
        st["halt_reason"] = "salida manual: todo vendido a USDT"
        _save_state(st)
        log("WARN", "  [ROT] salida manual: posiciones vendidas y bot detenido")
        return st
    tgt = compute_targets(refresh=refresh)
    if st.get("last_asof") == tgt["asof"] and not st["halted"]:
        log("INFO", f"  [ROT] el cierre {tgt['asof']} ya fue procesado — nada que hacer")
        return st
    weights = tgt["weights"]
    syms = sorted(set(weights) | set(st["holdings"]))
    prices = _prices(syms) if syms else {}
    eq = _equity(st, prices)
    st["peak_equity"] = max(st.get("peak_equity", eq), eq)
    dd = (eq / st["peak_equity"] - 1) * 100

    # kill switch: una caida mayor a cualquier cosa vista en el backtest
    # significa que la estrategia dejo de comportarse como se midio.
    if not st["halted"] and dd <= -MAX_DD_PCT:
        st["halted"] = True
        st["halt_reason"] = f"drawdown {dd:.1f}% <= -{MAX_DD_PCT:.0f}%"
        log("ERROR", f"  [ROT] KILL SWITCH: {st['halt_reason']} — liquidando y deteniendo")
        _liquidate(st, prices, execute, "KILL_SWITCH")
    if st["halted"]:
        if st["holdings"]:
            _liquidate(st, prices, execute, "HALTED")
        _save_state(st)
        log("WARN", f"  [ROT] detenido ({st['halt_reason']}). `rotation reset` para reanudar.")
        return st

    changed = weights != st.get("last_target", {})
    log("INFO", f"  [ROT] asof={tgt['asof']} regimen={'ON' if tgt['regime_on'] else 'OFF'} "
                f"(BTC {tgt['btc_close']:.0f} vs MA{PARAMS['regime_ma']} {tgt['btc_ma']:.0f}) "
                f"objetivo={weights or 'USDT 100%'} equity=${eq:.2f} dd={dd:.1f}%")
    if changed:
        thresh = max(MIN_TRADE_USD, MIN_TRADE_FRAC * eq)
        deltas = {}
        for s in syms:
            cur = st["holdings"].get(s, 0.0) * prices[s]
            deltas[s] = (weights.get(s, 0.0) * eq - cur, cur)
        # primero ventas (liberan USDT), luego compras
        for s, (d, cur) in sorted(deltas.items(), key=lambda kv: kv[1][0]):
            if d < 0 and (weights.get(s, 0.0) == 0 or -d >= thresh):
                _trade(st, s, "SELL", cur if weights.get(s, 0.0) == 0 else -d, prices[s], execute,
                       "SALIDA" if weights.get(s, 0.0) == 0 else "REBALANCEO")
        for s, (d, cur) in sorted(deltas.items(), key=lambda kv: -kv[1][0]):
            if d >= thresh:
                usd = min(d, st["cash"] * 0.995)
                if usd >= MIN_TRADE_USD:
                    _trade(st, s, "BUY", usd, prices[s], execute,
                           "ENTRADA" if cur < 1.0 else "REBALANCEO")
        st["last_target"] = weights
    else:
        log("INFO", "  [ROT] objetivo sin cambios — no se opera")
    st["last_asof"] = tgt["asof"]
    eq = _equity(st, prices)
    st["peak_equity"] = max(st["peak_equity"], eq)
    _save_state(st)
    _append_csv(EQUITY_CSV, ["date", "equity", "cash", "exposure_pct", "regime_on", "holdings"],
                [tgt["asof"], f"{eq:.2f}", f"{st['cash']:.2f}",
                 f"{(1 - st['cash'] / eq) * 100:.1f}" if eq else "0", int(tgt["regime_on"]),
                 " ".join(sorted(st["holdings"]))])
    return st


def status():
    st = _load_state()
    syms = sorted(st["holdings"])
    prices = _prices(syms) if syms else {}
    eq = _equity(st, prices)
    ini = st.get("initial_capital", CAPITAL)
    print(f"\n  ROTACION — estado ({'DETENIDO: ' + str(st['halt_reason']) if st['halted'] else 'activo'})")
    print(f"  Capital inicial: ${ini:.2f}   Equity: ${eq:.2f}   "
          f"P&L: {((eq / ini) - 1) * 100:+.2f}%   DD desde pico: {(eq / max(st['peak_equity'], eq) - 1) * 100:.1f}%")
    print(f"  USDT: ${st['cash']:.2f}   Ultimo cierre procesado: {st.get('last_asof')}")
    for s in syms:
        v = st["holdings"][s] * prices[s]
        print(f"    {s:<10} qty={st['holdings'][s]:.8g}  ${v:.2f}  ({v / eq * 100:.1f}%)")
    if not syms:
        print("    (sin posiciones: 100% USDT)")
    print()


def reset(hard=False):
    if hard and os.path.exists(STATE_PATH):
        os.remove(STATE_PATH)
        print("  Estado de rotacion borrado (se reinicia con ROT_CAPITAL).")
        return
    st = _load_state()
    st["halted"] = False
    st["halt_reason"] = None
    st["peak_equity"] = st["cash"]
    st["last_target"] = {}
    _save_state(st)
    print("  Kill switch reseteado.")


def run_loop(execute=False):
    """Bucle 24/7: un ciclo al dia a las 00:05 UTC. Reintenta si falla."""
    from bot.heartbeat import beat
    log("INFO", f"  [ROT] bucle iniciado (modo={'EXECUTE' if execute else 'PAPER'}, capital=${CAPITAL:.0f})")
    while True:
        st = _load_state()
        now = datetime.now(timezone.utc)
        yesterday = str((now - timedelta(days=1)).date())
        due = st.get("last_asof") != yesterday and (now.hour, now.minute) >= RUN_AT_UTC
        if due:
            try:
                step(execute=execute)
            except Exception as e:
                log("WARN", f"  [ROT] ciclo fallido ({e}); reintento en 10 min")
                beat("ROTATION_RETRY")
                time.sleep(600)
                continue
        beat("ROTATION_IDLE", last_asof=_load_state().get("last_asof"))
        time.sleep(240)


def backtest_report():
    from backtest.research import main
    main()


def cli(argv):
    sub = argv[0] if argv else "status"
    execute = "--execute" in argv
    if sub == "status":
        status()
    elif sub == "signal":
        print(json.dumps(compute_targets(), indent=2))
    elif sub == "once":
        step(execute=execute)
        status()
    elif sub == "run":
        run_loop(execute=execute)
    elif sub == "backtest":
        backtest_report()
    elif sub == "dashboard":
        from bot.rotation_panel import export_dashboard
        export_dashboard()
    elif sub == "conexion":
        from bot.rotation_panel import conexion
        conexion()
    elif sub == "reset":
        reset(hard="--hard" in argv)
    else:
        print("  Uso: python bot_crypto.py rotation status|signal|once|run|backtest|dashboard|conexion|reset [--execute] [--hard]")
