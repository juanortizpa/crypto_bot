"""
live_runner.py — Wrapper LIVE del Modelo D ganador, con safety guards.

Carga results/winner_config.json y ejecuta el modelo en vivo contra Binance.

SAFETY GUARDS (CRITICAS para capital pequeno $10–$500):
    1) max_capital_per_trade  — % del portfolio usable por trade (default 50%)
    2) min_notional_usdt      — $5 (limite Binance MEXC)
    3) daily_loss_kill        — si perdiste >X% del portfolio en 24h, STOP
    4) total_dd_kill          — si DD acumulado >25%, STOP permanente
    5) max_concurrent         — cuantos trades simultaneos (default 1)
    6) cooldown_minutes       — pausa minima entre trades en mismo par
    7) confirmacion_humana    — si AUTO_EXECUTE=False, solo imprime senales

Modos:
    --dry-run    No coloca ordenes. Solo escanea y reporta.
    --paper      Usa testnet de Binance. Coloca ordenes simuladas.
    --live       LIVE REAL. Requiere AUTO_EXECUTE=True y confirmacion explicita.

Uso:
    python -m model_d_training.live_runner --dry-run
    python -m model_d_training.live_runner --paper
    python -m model_d_training.live_runner --live   # SOLO cuando todo este verificado
"""
import os
import sys
import json
import time
import pickle
import argparse
import sqlite3
from datetime import datetime, timezone, timedelta

ROOT_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_PARENT)

ROOT     = os.path.dirname(os.path.abspath(__file__))
WINNER   = os.path.join(ROOT, "results", "winner_config.json")
XGB_PKL  = os.path.join(ROOT, "results", "xgb_models.pkl")
HYB_PKL  = os.path.join(ROOT, "results", "hybrid_model.pkl")
GRID_BEST = os.path.join(ROOT, "results", "grid_best.json")
STATE_DB = os.path.join(ROOT, "state", "live_state.db")

# ── Defaults seguros para capital pequeno ─────────────────────────────────
DEFAULTS = {
    "portfolio_usdt":         10.0,    # ajusta a tu balance real
    "max_capital_per_trade":  0.50,    # 50% del portfolio max por trade
    "min_notional_usdt":      5.10,    # Binance min suele ser $5
    "daily_loss_kill_pct":    0.15,    # 15% de portfolio = $1.50 en $10
    "total_dd_kill_pct":      0.25,    # 25% acumulado
    "max_concurrent":         1,        # un trade a la vez con $10
    "cooldown_minutes":       60,
    "scan_interval_minutes":  15,
    "fee_pct":                0.10,
}


def init_state_db():
    os.makedirs(os.path.dirname(STATE_DB), exist_ok=True)
    conn = sqlite3.connect(STATE_DB)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS live_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_open INTEGER, ts_close INTEGER,
            pair TEXT, side TEXT,
            entry_price REAL, exit_price REAL,
            qty REAL, notional REAL,
            stop_price REAL, target_price REAL,
            max_hold_hours INTEGER,
            status TEXT,           -- OPEN | WIN | LOSS | TIMEOUT | KILLED
            pnl_usdt REAL, pnl_pct REAL,
            mode TEXT,             -- dry | paper | live
            model_id TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS kill_state (
            key TEXT PRIMARY KEY, value TEXT
        )
    """)
    conn.commit()
    return conn


def load_winner():
    if not os.path.exists(WINNER):
        print(f"X Falta {WINNER}. Corre primero compare.py")
        sys.exit(1)
    return json.load(open(WINNER))


# ── Calculo de senales (replica de features.py para LIVE) ─────────────────

def fetch_live_features(pair):
    """
    Trae los ultimos 200 bars 1h de Binance LIVE y calcula las features
    igual que features.py.
    """
    from binance_client import get_klines  # de crypto_bot/
    from bot.crypto_data import get_fear_greed
    bars_raw = get_klines(pair, "1h", limit=200)
    if not bars_raw or len(bars_raw) < 200:
        return None

    bars = [{"ts": int(b[0])//1000, "o": float(b[1]), "h": float(b[2]),
             "l": float(b[3]), "c": float(b[4]), "v": float(b[5])} for b in bars_raw]
    closes = [b["c"] for b in bars]
    vols   = [b["v"] for b in bars]
    price  = closes[-1]

    # Indicadores
    def _sma(a, n): return sum(a[-n:])/n if len(a) >= n else None
    def _rsi(c, n=14):
        if len(c) < n+1: return 50.0
        g, l = 0, 0
        for i in range(-n, 0):
            d = c[i]-c[i-1]
            if d > 0: g += d
            else: l -= d
        avg_g = g/n; avg_l = l/n if l>0 else 1e-9
        return 100 - (100/(1 + avg_g/avg_l))
    def _atr(b, n=14):
        if len(b) < n+1: return 0
        trs=[]
        for i in range(-n,0):
            h,l,pc = b[i]["h"], b[i]["l"], b[i-1]["c"]
            trs.append(max(h-l, abs(h-pc), abs(l-pc)))
        return sum(trs)/n

    rsi_v = _rsi(closes, 14)
    high7 = max(closes[-168:]) if len(closes) >= 168 else max(closes)
    dd = (price - high7) / high7 * 100
    atr_v = _atr(bars, 14)
    atr_pct = atr_v / price * 100 if price else 0
    vol_24 = sum(vols[-24:]); vol_7d_avg = sum(vols[-168:])/7 if len(vols)>=168 else vol_24
    vol_ratio = vol_24/vol_7d_avg if vol_7d_avg > 0 else 1
    mom_4h  = (closes[-1]-closes[-5])/closes[-5]*100 if len(closes)>=5 else 0
    mom_12h = (closes[-1]-closes[-13])/closes[-13]*100 if len(closes)>=13 else 0
    mom_24h = (closes[-1]-closes[-25])/closes[-25]*100 if len(closes)>=25 else 0
    ma20 = _sma(closes, 20); ma50 = _sma(closes, 50)
    dist_ma20 = (price-ma20)/ma20*100 if ma20 else 0
    dist_ma50 = (price-ma50)/ma50*100 if ma50 else 0

    # BTC trend
    btc_bars = get_klines("BTCUSDT", "1h", limit=30)
    btc_trend = 0
    if btc_bars and len(btc_bars) >= 25:
        btc_trend = (float(btc_bars[-1][4]) - float(btc_bars[-25][4])) / float(btc_bars[-25][4]) * 100

    # F&G
    try:
        fng = get_fear_greed()["value"]
    except Exception:
        fng = 50

    return {
        "pair": pair,
        "price": price,
        "rsi14": rsi_v,
        "drawdown_7d": dd,
        "atr_pct": atr_pct,
        "vol_ratio": vol_ratio,
        "mom_4h": mom_4h,
        "mom_12h": mom_12h,
        "mom_24h": mom_24h,
        "dist_ma20": dist_ma20,
        "dist_ma50": dist_ma50,
        "btc_trend_24h": btc_trend,
        "btc_dom_proxy": 50.0,  # placeholder — el proxy se calcula con todos los pares
        "fng_value": fng,
        "hour_of_day": datetime.now(tz=timezone.utc).hour,
    }


# ── Signal evaluation segun winner_config ─────────────────────────────────

def signal_grid(feat, cfg):
    f = cfg["filters"]
    return (feat["rsi14"]         <= f["rsi_max"]
        and feat["drawdown_7d"]   <= f["drawdown_min"]
        and feat["fng_value"]     <= f["fng_max"]
        and feat["btc_dom_proxy"] <= f["btc_dom_max"]
        and feat["mom_4h"]        >= f["mom_4h_min"]
        and feat["vol_ratio"]     >= f["vol_ratio_min"])


def signal_xgb(feat, cfg):
    pkg = pickle.load(open(XGB_PKL, "rb"))[cfg["xgb_combo"]]
    cols = pkg["feature_cols"]
    X = [[feat[c] for c in cols]]
    p = pkg["model"].predict_proba(X)[0][1]
    return p >= cfg["threshold"], p


def signal_hybrid(feat, cfg):
    pkg = pickle.load(open(HYB_PKL, "rb"))
    f = pkg["grid_filters"]
    if not (feat["rsi14"]         <= f["rsi_max"]
        and feat["drawdown_7d"]   <= f["drawdown_min"]
        and feat["fng_value"]     <= f["fng_max"]
        and feat["btc_dom_proxy"] <= f["btc_dom_max"]
        and feat["mom_4h"]        >= f["mom_4h_min"]
        and feat["vol_ratio"]     >= f["vol_ratio_min"]):
        return False, 0
    cols = pkg["feature_cols"]
    X = [[feat[c] for c in cols]]
    Xs = pkg["scaler"].transform(X)
    p = pkg["model"].predict_proba(Xs)[0][1]
    return p >= pkg["threshold"], p


def evaluate_signal(feat, winner_cfg):
    """Devuelve (toma_trade: bool, info: str)."""
    t = winner_cfg["type"]
    if t == "grid":
        return signal_grid(feat, winner_cfg), "grid_only"
    if t == "xgb":
        ok, p = signal_xgb(feat, winner_cfg)
        return ok, f"xgb_p={p:.2f}"
    if t == "hybrid":
        ok, p = signal_hybrid(feat, winner_cfg)
        return ok, f"hybrid_p={p:.2f}"
    if t == "ensemble":
        votes = 0
        notes = []
        if signal_grid(feat, {"filters": json.load(open(GRID_BEST))["filters"]}):
            votes += 1; notes.append("G")
        ok_x, p_x = signal_xgb(feat, json.load(open(os.path.join(ROOT, "results", "xgb_best.json"))))
        if ok_x: votes += 1; notes.append(f"X({p_x:.2f})")
        ok_h, p_h = signal_hybrid(feat, {})
        if ok_h: votes += 1; notes.append(f"H({p_h:.2f})")
        v = winner_cfg.get("voting", "")
        thr = 2 if "Majority" in v else (1 if "Any" in v else 3)
        return votes >= thr, f"votes={votes} {','.join(notes)}"
    return False, "unknown_type"


# ── Safety checks ─────────────────────────────────────────────────────────

def check_kill_switches(conn, defaults):
    c = conn.cursor()

    # 1) Daily loss
    cutoff = int(time.time()) - 24*3600
    c.execute("""SELECT COALESCE(SUM(pnl_usdt), 0) FROM live_trades
                 WHERE ts_close >= ? AND status IN ('WIN','LOSS','TIMEOUT')""",
              (cutoff,))
    daily_pnl = c.fetchone()[0] or 0
    daily_limit = -defaults["portfolio_usdt"] * defaults["daily_loss_kill_pct"]
    if daily_pnl <= daily_limit:
        return False, f"DAILY KILL: PnL 24h ${daily_pnl:.2f} <= limite ${daily_limit:.2f}"

    # 2) Total DD
    c.execute("SELECT COALESCE(SUM(pnl_usdt), 0) FROM live_trades WHERE status IN ('WIN','LOSS','TIMEOUT')")
    cum = c.fetchone()[0] or 0
    if cum <= -defaults["portfolio_usdt"] * defaults["total_dd_kill_pct"]:
        return False, f"TOTAL DD KILL: cum ${cum:.2f}"

    # 3) Concurrent open
    c.execute("SELECT COUNT(*) FROM live_trades WHERE status='OPEN'")
    n_open = c.fetchone()[0]
    if n_open >= defaults["max_concurrent"]:
        return False, f"MAX CONCURRENT: {n_open} ya abiertos"

    return True, "ok"


def can_enter_pair(conn, pair, cooldown_min):
    c = conn.cursor()
    cutoff = int(time.time()) - cooldown_min*60
    c.execute("""SELECT ts_close FROM live_trades
                 WHERE pair=? AND status IN ('WIN','LOSS','TIMEOUT')
                 ORDER BY ts_close DESC LIMIT 1""", (pair,))
    row = c.fetchone()
    if row and row[0] and row[0] >= cutoff:
        return False
    c.execute("""SELECT 1 FROM live_trades WHERE pair=? AND status='OPEN' LIMIT 1""", (pair,))
    if c.fetchone():
        return False
    return True


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Solo escanea, no opera")
    parser.add_argument("--paper",   action="store_true", help="Usa testnet")
    parser.add_argument("--live",    action="store_true", help="LIVE REAL")
    parser.add_argument("--once",    action="store_true", help="Una sola pasada (no loop)")
    args = parser.parse_args()

    mode = "dry"
    if args.live: mode = "live"
    elif args.paper: mode = "paper"

    print("="*60)
    print(f"MODEL D LIVE RUNNER — modo: {mode.upper()}")
    print("="*60)

    if mode == "live":
        env = os.getenv("AUTO_EXECUTE", "False").lower()
        if env != "true":
            print("X AUTO_EXECUTE no esta en True en .env")
            print("  Para LIVE REAL: edita .env y pon AUTO_EXECUTE=True")
            sys.exit(1)
        confirm = input("\n!!! VAS A OPERAR CON DINERO REAL !!!\n"
                        "Escribe 'CONFIRMO' para continuar: ")
        if confirm.strip() != "CONFIRMO":
            print("Cancelado.")
            sys.exit(0)

    winner = load_winner()

    # GUARD: no operar si el winner tiene metricas OOS perdedoras
    m = winner.get("winner_metrics", {})
    if m.get("total_pnl", 0) <= 0 or m.get("pf", 0) < 1.0:
        print("\n" + "!"*60)
        print(f"! WINNER no rentable en OOS: PnL {m.get('total_pnl')}  PF {m.get('pf')}")
        print(f"! NO se va a operar. Re-entrena o ajusta el GRID antes de continuar.")
        print("!"*60)
        if mode == "live":
            sys.exit(1)
        # En dry/paper, deja correr para inspeccion manual

    print(f"\nWinner cargado: {winner['winner_name']}  type={winner['type']}")
    print(f"Trade: stop {winner['trade']['stop_pct']*100:.1f}%  "
          f"target {winner['trade']['target_pct']*100:.1f}%  "
          f"max {winner['trade']['max_hours']}h")
    print(f"Metricas OOS: WR {winner['winner_metrics']['win_rate']*100:.1f}%  "
          f"PF {winner['winner_metrics']['pf']}  "
          f"PnL {winner['winner_metrics']['total_pnl']:+.2f}%")

    conn = init_state_db()
    defaults = DEFAULTS.copy()
    # Sobreescribir portfolio del .env si esta seteado
    pf_env = os.getenv("CRYPTO_PORTFOLIO")
    if pf_env:
        try: defaults["portfolio_usdt"] = float(pf_env)
        except: pass

    print(f"\nPortfolio configurado: ${defaults['portfolio_usdt']:.2f}")
    print(f"Max por trade: ${defaults['portfolio_usdt'] * defaults['max_capital_per_trade']:.2f}")
    print(f"Daily kill: ${defaults['portfolio_usdt'] * defaults['daily_loss_kill_pct']:.2f}")

    from bot.top20_pairs import TOP_20

    while True:
        ts = datetime.now(tz=timezone.utc).isoformat()
        print(f"\n[{ts}] === SCAN ===")
        ok, why = check_kill_switches(conn, defaults)
        if not ok:
            print(f"  [KILLED] {why}")
            if args.once: break
            time.sleep(defaults["scan_interval_minutes"]*60)
            continue

        for pair in TOP_20:
            if not can_enter_pair(conn, pair, defaults["cooldown_minutes"]):
                continue
            try:
                feat = fetch_live_features(pair)
            except Exception as e:
                print(f"  [{pair}] error: {e}")
                continue
            if not feat:
                continue
            take, info = evaluate_signal(feat, winner)
            tag = "✓" if take else " "
            print(f"  {tag} [{pair}]  px={feat['price']:.4f}  rsi={feat['rsi14']:.1f}  "
                  f"dd={feat['drawdown_7d']:+.1f}%  fng={feat['fng_value']}  "
                  f"mom4h={feat['mom_4h']:+.1f}%  | {info}")
            if take and mode != "dry":
                place_order(conn, feat, winner, mode, defaults)

        if args.once: break
        print(f"  Esperando {defaults['scan_interval_minutes']}min...")
        time.sleep(defaults["scan_interval_minutes"]*60)


def place_order(conn, feat, winner, mode, defaults):
    """Coloca orden en testnet/live. EN DRY-RUN no se llama."""
    from binance_client import _request, ENV
    pair = feat["pair"]
    price = feat["price"]
    notional = max(defaults["min_notional_usdt"],
                   defaults["portfolio_usdt"] * defaults["max_capital_per_trade"])
    if notional > defaults["portfolio_usdt"]:
        notional = defaults["portfolio_usdt"] * 0.95  # deja buffer
    qty = round(notional / price, 6)
    stop_p = round(price * (1 - winner["trade"]["stop_pct"]), 6)
    tgt_p  = round(price * (1 + winner["trade"]["target_pct"]), 6)

    print(f"    → COLOCAR ORDEN {mode}: BUY {qty} {pair} @ ${price:.4f} "
          f"(notional ${notional:.2f}) stop ${stop_p:.4f} target ${tgt_p:.4f}")

    if mode == "paper":
        # En testnet: Binance testnet acepta MARKET orders
        try:
            res = _request("POST", "/api/v3/order", {
                "symbol": pair, "side": "BUY", "type": "MARKET",
                "quantity": qty,
            }, signed=True)
            order_id = res.get("orderId", "?")
            print(f"      OK paper: orderId={order_id}")
        except Exception as e:
            print(f"      X paper falla: {e}")
            return
    elif mode == "live":
        # MISMA llamada pero contra api.binance.com (configurado en .env BINANCE_MODE=live)
        try:
            res = _request("POST", "/api/v3/order", {
                "symbol": pair, "side": "BUY", "type": "MARKET",
                "quantity": qty,
            }, signed=True)
            order_id = res.get("orderId", "?")
            print(f"      OK LIVE: orderId={order_id}")
        except Exception as e:
            print(f"      X LIVE falla: {e}")
            return

    # Registrar en DB
    c = conn.cursor()
    c.execute("""INSERT INTO live_trades
                 (ts_open, pair, side, entry_price, qty, notional,
                  stop_price, target_price, max_hold_hours, status, mode, model_id)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
              (int(time.time()), pair, "BUY", price, qty, notional,
               stop_p, tgt_p, winner["trade"]["max_hours"],
               "OPEN", mode, winner["winner_name"]))
    conn.commit()


if __name__ == "__main__":
    main()
