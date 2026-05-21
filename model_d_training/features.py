"""
features.py — Feature engineering + labeler para Modelo D.

Lee state/data_2026.db (klines 1h + F&G) y produce un dataset
state/features_d.csv con una fila por (pair, ts) candidato a entrada.

Cada fila tiene:
    Identificador:   pair, ts, dt_iso, entry_price
    Features:        rsi14, drawdown_7d, atr_pct, vol_ratio_24h,
                     mom_4h, mom_12h, mom_24h, dist_ma20, dist_ma50,
                     btc_trend_24h, btc_dom_proxy, fng_value, hour_of_day
    Labels (5 variantes de stop/target):
        Para cada combo de (stop_pct, target_pct, max_hours), simula el trade
        forward y guarda: result (WIN/LOSS/TIMEOUT), pnl_pct, hours_held

El labeler usa una heuristica de orden intra-bar (igual que run_backtest.py):
  - si bar abre arriba del entry → mayor prob de tocar target primero
  - si bar abre abajo            → mayor prob de tocar stop primero
  - si abre cerca                → proporcional a (open→high) vs (open→low)

Filtros de entrada candidato (Modelo D — Dip Scalper):
  Pre-filtro amplio para no perder datos: cualquier bar donde:
    * RSI <= 50  (algo de debilidad)
    * drawdown_7d <= -3%  (en correccion)
  El optimizador despues afinara los thresholds finales.

Uso:
    cd crypto_bot
    python -m model_d_training.features
"""
import os
import sys
import math
import json
import sqlite3
import csv
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bot.top20_pairs import TOP_20

DB_PATH    = os.path.join(os.path.dirname(__file__), "state", "data_2026.db")
OUT_CSV    = os.path.join(os.path.dirname(__file__), "state", "features_d.csv")

# Combos de stop/target a etiquetar (los que el grid va a explorar)
LABEL_COMBOS = [
    # (stop_pct, target_pct, max_hours)
    (0.02, 0.03,  6),   # tight scalp
    (0.025, 0.04, 8),   # default actual
    (0.03,  0.05, 12),  # standard dip
    (0.035, 0.06, 16),  # wider
    (0.04,  0.08, 24),  # swing dip
]

# Pre-filtros amplios (para no etiquetar todo)
PREFILTER_RSI_MAX = 55
PREFILTER_DD_MAX  = -2.0  # drawdown <= -2%


# ── Indicadores ──────────────────────────────────────────────────────────

def sma(arr, n):
    if len(arr) < n: return None
    return sum(arr[-n:]) / n

def rsi(closes, n=14):
    if len(closes) < n + 1: return 50.0
    gains, losses = 0.0, 0.0
    for i in range(-n, 0):
        diff = closes[i] - closes[i-1]
        if diff > 0: gains += diff
        else: losses += -diff
    avg_g = gains / n
    avg_l = losses / n if losses > 0 else 1e-9
    rs = avg_g / avg_l
    return 100 - (100 / (1 + rs))

def atr(bars, n=14):
    """bars: list of dicts with h,l,c."""
    if len(bars) < n + 1: return 0.0
    trs = []
    for i in range(-n, 0):
        h, l, prev_c = bars[i]["h"], bars[i]["l"], bars[i-1]["c"]
        trs.append(max(h - l, abs(h - prev_c), abs(l - prev_c)))
    return sum(trs) / n


# ── Carga de datos ───────────────────────────────────────────────────────

def load_pair_bars(conn, pair):
    c = conn.cursor()
    c.execute("""
        SELECT ts, open, high, low, close, volume
        FROM klines_1h WHERE pair = ?
        ORDER BY ts ASC
    """, (pair,))
    return [{"ts": r[0], "o": r[1], "h": r[2], "l": r[3], "c": r[4], "v": r[5]}
            for r in c.fetchall()]


def load_fng_map(conn):
    """ts (timestamp del dia) -> value."""
    c = conn.cursor()
    c.execute("SELECT ts, value FROM fear_greed ORDER BY ts ASC")
    return {ts: val for ts, val in c.fetchall()}


def fng_at(fng_map, ts):
    """Encuentra el F&G mas reciente ANTES de ts (el del dia anterior o el mismo dia)."""
    if not fng_map: return 50  # neutral default
    # busqueda: el F&G se publica una vez al dia, asi que tomar el mayor ts <= bar_ts
    candidates = [k for k in fng_map.keys() if k <= ts]
    if not candidates:
        # tomar el mas viejo disponible
        return fng_map[min(fng_map.keys())]
    return fng_map[max(candidates)]


# ── BTC dominance proxy (calculado desde klines) ─────────────────────────

def compute_btc_dom_proxy(bars_by_pair, ts):
    """
    Proxy de dominance: market_cap_btc / sum(market_cap_de_los_top_pairs)
    Sin supply real, usamos quote_volume como proxy (liquidez relativa).
    Es aproximado pero captura tendencia.
    """
    btc_v = 0
    total_v = 0
    for pair, bars in bars_by_pair.items():
        # Encontrar bar mas cercano <= ts
        idx = bisect_le(bars, ts)
        if idx < 0: continue
        v = bars[idx]["c"] * bars[idx]["v"]  # close * volume = quote vol approx
        if pair == "BTCUSDT":
            btc_v = v
        total_v += v
    if total_v == 0: return 50.0
    return (btc_v / total_v) * 100


def bisect_le(bars, ts):
    """Devuelve idx del mayor bar.ts <= ts, o -1."""
    lo, hi = 0, len(bars) - 1
    res = -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if bars[mid]["ts"] <= ts:
            res = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return res


# ── Labeler intra-bar ────────────────────────────────────────────────────

def simulate_trade(bars, start_idx, entry, stop, target, max_hours):
    """
    Simula el trade desde el bar start_idx en adelante.
    Returns (result, pnl_pct, hours_held)
        result: WIN | LOSS | TIMEOUT
    """
    fwd_bars = bars[start_idx + 1 : start_idx + 1 + max_hours]
    for h, bar in enumerate(fwd_bars, 1):
        bo, bh, bl, bc = bar["o"], bar["h"], bar["l"], bar["c"]
        hit_stop   = bl <= stop
        hit_target = bh >= target
        if hit_stop and hit_target:
            # Ambos en mismo bar → heuristica por open
            if bo >= entry:  # abrio cerca/arriba del entry → primero target
                return ("WIN", (target - entry) / entry, h)
            elif bo <= entry * (1 - 0.005):  # abrio abajo → primero stop
                return ("LOSS", (stop - entry) / entry, h)
            else:
                # proporcional
                up_dist = bh - bo
                dn_dist = bo - bl
                if up_dist > dn_dist:
                    return ("WIN", (target - entry) / entry, h)
                return ("LOSS", (stop - entry) / entry, h)
        if hit_target:
            return ("WIN", (target - entry) / entry, h)
        if hit_stop:
            return ("LOSS", (stop - entry) / entry, h)
    # Timeout
    if not fwd_bars:
        return ("TIMEOUT", 0.0, 0)
    final_close = fwd_bars[-1]["c"]
    return ("TIMEOUT", (final_close - entry) / entry, len(fwd_bars))


# ── Pipeline principal ──────────────────────────────────────────────────

def main():
    print(f"Leyendo {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    fng_map = load_fng_map(conn)
    print(f"F&G entries: {len(fng_map)}")

    # Carga todos los pares
    bars_by_pair = {}
    for pair in TOP_20:
        bars_by_pair[pair] = load_pair_bars(conn, pair)
        print(f"  {pair}: {len(bars_by_pair[pair])} bars")

    btc_bars = bars_by_pair.get("BTCUSDT", [])
    if not btc_bars:
        print("X No hay datos de BTC — abortando")
        return

    rows_out = []
    skipped_short = 0
    skipped_filter = 0

    for pair in TOP_20:
        bars = bars_by_pair[pair]
        if len(bars) < 200:
            print(f"  {pair}: skip (solo {len(bars)} bars, necesita 200+)")
            skipped_short += len(bars)
            continue

        for i in range(200, len(bars) - max(c[2] for c in LABEL_COMBOS) - 1):
            window = bars[max(0, i-200):i+1]
            closes = [b["c"] for b in window]
            price  = closes[-1]
            ts     = bars[i]["ts"]

            # Indicadores
            r = rsi(closes, 14)

            # Drawdown 7d (168 bars 1h)
            look = min(168, len(closes))
            high_recent = max(closes[-look:])
            dd = (price - high_recent) / high_recent * 100

            # Pre-filtro
            if r > PREFILTER_RSI_MAX or dd > PREFILTER_DD_MAX:
                skipped_filter += 1
                continue

            # Mas features
            ma20 = sma(closes, 20)
            ma50 = sma(closes, 50)
            atr_v = atr(window, 14)
            atr_pct = (atr_v / price * 100) if price else 0

            # Volumen 24h vs avg 7d
            vols = [b["v"] for b in window]
            vol_24h = sum(vols[-24:]) if len(vols) >= 24 else 0
            vol_7d_avg = sum(vols[-168:]) / 7 if len(vols) >= 168 else vol_24h
            vol_ratio = (vol_24h / vol_7d_avg) if vol_7d_avg > 0 else 1.0

            # Momentum
            mom_4h  = (closes[-1] - closes[-5]) / closes[-5] * 100 if len(closes) >= 5 else 0
            mom_12h = (closes[-1] - closes[-13]) / closes[-13] * 100 if len(closes) >= 13 else 0
            mom_24h = (closes[-1] - closes[-25]) / closes[-25] * 100 if len(closes) >= 25 else 0

            dist_ma20 = ((price - ma20) / ma20 * 100) if ma20 else 0
            dist_ma50 = ((price - ma50) / ma50 * 100) if ma50 else 0

            # BTC trend 24h
            btc_idx = bisect_le(btc_bars, ts)
            btc_trend = 0.0
            if btc_idx >= 24:
                btc_now = btc_bars[btc_idx]["c"]
                btc_24h = btc_bars[btc_idx - 24]["c"]
                btc_trend = (btc_now - btc_24h) / btc_24h * 100

            # BTC dominance proxy
            btc_dom = compute_btc_dom_proxy(bars_by_pair, ts)

            # F&G
            fng = fng_at(fng_map, ts)

            # Hora del dia (puede haber patron — Asian/EU/US session)
            hour_of_day = datetime.fromtimestamp(ts, tz=timezone.utc).hour

            # Labels para cada combo
            row = {
                "pair":         pair,
                "ts":           ts,
                "dt_iso":       datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                "entry_price":  price,
                "rsi14":        round(r, 2),
                "drawdown_7d":  round(dd, 3),
                "atr_pct":      round(atr_pct, 3),
                "vol_ratio":    round(vol_ratio, 3),
                "mom_4h":       round(mom_4h, 3),
                "mom_12h":      round(mom_12h, 3),
                "mom_24h":      round(mom_24h, 3),
                "dist_ma20":    round(dist_ma20, 3),
                "dist_ma50":    round(dist_ma50, 3),
                "btc_trend_24h": round(btc_trend, 3),
                "btc_dom_proxy": round(btc_dom, 2),
                "fng_value":    fng,
                "hour_of_day":  hour_of_day,
            }

            for stop_pct, target_pct, max_h in LABEL_COMBOS:
                stop_p   = price * (1 - stop_pct)
                target_p = price * (1 + target_pct)
                result, pnl, held = simulate_trade(bars, i, price, stop_p, target_p, max_h)
                key = f"s{int(stop_pct*1000):03d}_t{int(target_pct*1000):03d}_h{max_h}"
                row[f"label_{key}"]   = result
                row[f"pnl_{key}"]     = round(pnl * 100, 3)  # en %
                row[f"held_{key}"]    = held

            rows_out.append(row)

    print(f"\nFilas generadas: {len(rows_out)}")
    print(f"Filtradas (no cumplen pre-filtro): {skipped_filter}")

    if not rows_out:
        print("X Sin filas — algo fallo")
        return

    # Escribir CSV
    fieldnames = list(rows_out[0].keys())
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows_out)

    print(f"✓ Guardado: {OUT_CSV}")

    # Resumen rapido
    print("\nDistribucion de labels (combo default s025_t040_h8):")
    counts = {"WIN": 0, "LOSS": 0, "TIMEOUT": 0}
    for r in rows_out:
        counts[r["label_s025_t040_h8"]] += 1
    total = len(rows_out)
    for k, v in counts.items():
        print(f"  {k:8s}: {v:6d} ({v/total*100:.1f}%)")

    conn.close()
    print("\nSiguiente paso: python -m model_d_training.train_grid")


if __name__ == "__main__":
    main()
