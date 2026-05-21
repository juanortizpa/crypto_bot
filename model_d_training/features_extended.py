"""
features_extended.py — Pipeline de features sobre datos 1-minuto + datos auxiliares.

Lee data_extended.db (producida por download_extended.py) y produce un CSV de
entrenamiento con las ~80 features descritas en el plan, organizadas en 9 grupos:

  A) Precio multi-timeframe   (RSI/ATR/SMA en 1m,5m,15m,1h,4h,1d, Bollinger, MACD, VWAP)
  B) Volumen y order flow     (CVD, vol Z-score, taker buy ratio, OBV)
  C) Microestructura          (spread proxy, profundidad de volumen)
  D) On-chain y flujos        (placeholder: funding rate como proxy de leverage flow)
  E) Sentimiento              (F&G actual + delta 7d)
  F) Macro cross-asset        (DXY, SP500, VIX, GOLD, US10Y - cambios y niveles)
  G) Correlacion              (BTC dominance, beta vs BTC, beta vs ETH)
  H) Tiempo y ciclos          (hour, day-of-week, sesion activa)
  I) Estado del trade target  (labels triple-barrier para 6 combos stop/target/hours)

Para cada candidato a entrada, se simula el trade hacia adelante en velas 1m con
las 6 combinaciones de (stop_pct, target_pct, max_hours) y se etiqueta:
  - label_sXXX_tXXX_hXX: WIN / LOSS / TIMEOUT
  - pnl_sXXX_tXXX_hXX:   PnL% real obtenido
  - held_sXXX_tXXX_hXX:  horas mantenidas

Pre-filtros de candidato (para no etiquetar todo y reducir CSV a un tamaño
manejable): RSI <= 55 y drawdown_7d <= -2%. (Configurable.)

Uso:
    python -m model_d_training.features_extended
    python -m model_d_training.features_extended --pair BTCUSDT
    python -m model_d_training.features_extended --limit 100000   # smoke test

Salida:
    state/features_extended.csv

Variables de entorno:
    EXTENDED_DB_PATH         override de la DB
    FEATURES_OUTPUT_CSV      override del CSV de salida
    FEATURES_PREFILTER_RSI   default 55
    FEATURES_PREFILTER_DD    default -2.0
"""

import os
import sys
import math
import csv
import sqlite3
import argparse
import bisect
from datetime import datetime, timezone, timedelta
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bot.top20_pairs import TOP_20


DB_PATH = os.environ.get(
    "EXTENDED_DB_PATH",
    os.path.join(os.path.dirname(__file__), "state", "data_extended.db"),
)
OUT_CSV = os.environ.get(
    "FEATURES_OUTPUT_CSV",
    os.path.join(os.path.dirname(__file__), "state", "features_extended.csv"),
)

PREFILTER_RSI_MAX = float(os.environ.get("FEATURES_PREFILTER_RSI", "55"))
PREFILTER_DD_MAX  = float(os.environ.get("FEATURES_PREFILTER_DD",  "-2.0"))

# Combos triple-barrier adaptados a 1m con un rango mas amplio
LABEL_COMBOS = [
    # (stop_pct, target_pct, max_hours, label_suffix)
    (0.015, 0.025, 4,  "s015_t025_h04"),
    (0.020, 0.035, 6,  "s020_t035_h06"),
    (0.025, 0.040, 8,  "s025_t040_h08"),  # default histórico
    (0.030, 0.050, 12, "s030_t050_h12"),
    (0.035, 0.060, 16, "s035_t060_h16"),
    (0.040, 0.080, 24, "s040_t080_h24"),
]

FEE_PCT = 0.10  # 0.10% por lado en Binance spot (0.20% round-trip)


# ── Indicadores tecnicos ──────────────────────────────────────────────────

def sma(arr, n):
    if len(arr) < n:
        return None
    return sum(arr[-n:]) / n


def ema(arr, n):
    if len(arr) < n:
        return None
    k = 2 / (n + 1)
    val = sum(arr[:n]) / n
    for x in arr[n:]:
        val = x * k + val * (1 - k)
    return val


def rsi(closes, n=14):
    if len(closes) < n + 1:
        return 50.0
    gains, losses = 0.0, 0.0
    for i in range(-n, 0):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            gains += diff
        else:
            losses -= diff
    avg_g = gains / n
    avg_l = losses / n if losses > 0 else 1e-9
    rs = avg_g / avg_l
    return 100 - (100 / (1 + rs))


def atr_pct(highs, lows, closes, n=14):
    """ATR como % del ultimo close."""
    if len(closes) < n + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i - 1]),
                 abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    if len(trs) < n:
        return None
    atr = sum(trs[-n:]) / n
    last = closes[-1]
    if last <= 0:
        return None
    return atr / last * 100


def macd(closes, fast=12, slow=26, signal=9):
    """Retorna (macd_line, signal_line, histogram) o None si insuficiente."""
    if len(closes) < slow + signal:
        return None, None, None
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    if ema_fast is None or ema_slow is None:
        return None, None, None
    macd_line = ema_fast - ema_slow
    # signal line aproximada (EMA del MACD seria recursivo; usamos SMA simplificada)
    # Para training es suficiente la senal cruda
    return macd_line, None, None


def bollinger(closes, n=20, k=2):
    """Devuelve (mid, upper, lower, pct_b, width). pct_b = posicion relativa 0..1."""
    if len(closes) < n:
        return None, None, None, None, None
    sub = closes[-n:]
    mid = sum(sub) / n
    var = sum((x - mid) ** 2 for x in sub) / n
    sd = math.sqrt(var)
    upper = mid + k * sd
    lower = mid - k * sd
    last = closes[-1]
    pct_b = (last - lower) / (upper - lower) if upper > lower else 0.5
    width = (upper - lower) / mid * 100 if mid > 0 else 0
    return mid, upper, lower, pct_b, width


def vwap_window(bars, n):
    """VWAP de los ultimos n bars: sum(close*vol)/sum(vol)."""
    if len(bars) < n:
        return None
    sub = bars[-n:]
    num = sum(b["c"] * b["v"] for b in sub)
    den = sum(b["v"] for b in sub) or 1e-9
    return num / den


# ── Carga de datos ────────────────────────────────────────────────────────

def load_1m_bars(con, pair):
    """Carga todas las velas 1m de un par ordenadas por timestamp."""
    rows = con.execute("""
        SELECT ts_ms, open, high, low, close, volume, quote_vol, trades,
               taker_buy_base, taker_buy_quote
        FROM ohlcv_1m WHERE pair=? ORDER BY ts_ms
    """, (pair,)).fetchall()
    return [{
        "ts": r[0], "o": r[1], "h": r[2], "l": r[3], "c": r[4],
        "v": r[5], "qv": r[6], "tr": r[7],
        "tbb": r[8], "tbq": r[9],
    } for r in rows]


def aggregate(bars_1m, period_min):
    """
    Re-samplea bars 1m a period_min minutos. Devuelve lista de dicts con
    timestamp = inicio del periodo.
    """
    if period_min == 1:
        return bars_1m
    if not bars_1m:
        return []
    out = []
    step_ms = period_min * 60_000
    bucket_start = (bars_1m[0]["ts"] // step_ms) * step_ms
    cur = {"ts": bucket_start, "o": bars_1m[0]["o"], "h": bars_1m[0]["h"],
           "l": bars_1m[0]["l"], "c": bars_1m[0]["c"], "v": 0.0, "qv": 0.0,
           "tr": 0, "tbb": 0.0, "tbq": 0.0}
    for b in bars_1m:
        bb = (b["ts"] // step_ms) * step_ms
        if bb != bucket_start:
            out.append(cur)
            bucket_start = bb
            cur = {"ts": bb, "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"],
                   "v": 0.0, "qv": 0.0, "tr": 0, "tbb": 0.0, "tbq": 0.0}
        cur["h"] = max(cur["h"], b["h"])
        cur["l"] = min(cur["l"], b["l"])
        cur["c"] = b["c"]
        cur["v"] += b["v"]
        cur["qv"] += b["qv"]
        cur["tr"] += b["tr"]
        cur["tbb"] += b["tbb"]
        cur["tbq"] += b["tbq"]
    out.append(cur)
    return out


def build_index_map(bars):
    """timestamps ordenados para bisect."""
    return [b["ts"] for b in bars]


def find_le(ts_array, ts):
    """Devuelve el indice del mayor ts_array[i] <= ts. -1 si no hay."""
    i = bisect.bisect_right(ts_array, ts) - 1
    return i if i >= 0 else -1


def load_macro_map(con):
    """Carga macro_indicators -> dict[symbol] -> sorted list of (ts_ms, close)."""
    out = defaultdict(list)
    rows = con.execute(
        "SELECT symbol, ts_ms, close FROM macro_indicators ORDER BY symbol, ts_ms"
    ).fetchall()
    for sym, ts, c in rows:
        out[sym].append((ts, c))
    return dict(out)


def load_fng_map(con):
    rows = con.execute("SELECT ts_ms, value FROM fear_greed ORDER BY ts_ms").fetchall()
    return [(r[0], r[1]) for r in rows]


def load_funding_map(con, pair):
    rows = con.execute(
        "SELECT ts_ms, rate FROM funding_rates WHERE pair=? ORDER BY ts_ms",
        (pair,)
    ).fetchall()
    return rows  # list of (ts_ms, rate)


def lookup_macro(macro_map, sym, ts):
    arr = macro_map.get(sym, [])
    if not arr:
        return None
    ts_arr = [a[0] for a in arr]
    i = find_le(ts_arr, ts)
    return arr[i][1] if i >= 0 else None


def lookup_fng(fng_arr, ts):
    if not fng_arr:
        return None
    ts_arr = [a[0] for a in fng_arr]
    i = find_le(ts_arr, ts)
    return fng_arr[i][1] if i >= 0 else None


# ── Simulacion de trade triple-barrier ────────────────────────────────────

def simulate_trade(bars_1m, start_idx, stop_pct, target_pct, max_hours):
    """
    Desde bars_1m[start_idx] (entry = close), simula hacia adelante:
      - Si toca target antes que stop -> WIN
      - Si toca stop primero -> LOSS
      - Si llega max_hours sin tocar -> TIMEOUT (pnl = close - entry)
    Considera comisiones FEE_PCT por lado.

    Devuelve (outcome, pnl_pct, held_hours).
    """
    if start_idx >= len(bars_1m) - 1:
        return "TIMEOUT", -2 * FEE_PCT, 0.0

    entry = bars_1m[start_idx]["c"]
    target_price = entry * (1 + target_pct)
    stop_price   = entry * (1 - stop_pct)
    max_bars = int(max_hours * 60)  # bars de 1m

    for i in range(start_idx + 1, min(start_idx + 1 + max_bars, len(bars_1m))):
        b = bars_1m[i]
        # Heuristica intra-bar: si bar abre arriba del entry -> target primero
        # mejor: chequear orden por proximidad al open
        opn = b["o"]
        if b["h"] >= target_price and b["l"] <= stop_price:
            # ambos tocados, decidir por apertura
            if abs(opn - target_price) <= abs(opn - stop_price):
                pnl = target_pct * 100 - 2 * FEE_PCT
                held = (i - start_idx) / 60.0
                return "WIN", pnl, held
            else:
                pnl = -stop_pct * 100 - 2 * FEE_PCT
                held = (i - start_idx) / 60.0
                return "LOSS", pnl, held
        if b["h"] >= target_price:
            pnl = target_pct * 100 - 2 * FEE_PCT
            return "WIN", pnl, (i - start_idx) / 60.0
        if b["l"] <= stop_price:
            pnl = -stop_pct * 100 - 2 * FEE_PCT
            return "LOSS", pnl, (i - start_idx) / 60.0

    # TIMEOUT
    last_idx = min(start_idx + max_bars, len(bars_1m) - 1)
    exit_price = bars_1m[last_idx]["c"]
    pnl = (exit_price - entry) / entry * 100 - 2 * FEE_PCT
    return "TIMEOUT", pnl, (last_idx - start_idx) / 60.0


# ── Calculo de features por candidato ─────────────────────────────────────

def compute_features(bars_1m, idx_1m, bars_5m, ts_idx_5m, bars_1h, ts_idx_1h,
                     bars_4h, ts_idx_4h, btc_close_1h_arr, eth_close_1h_arr,
                     fng_arr, macro_map, funding_arr, pair, btc_pair_arr_1m):
    """
    Calcula el vector de features en el bar bars_1m[idx_1m].
    Retorna dict feature_name -> value, o None si no hay datos suficientes.
    """
    b = bars_1m[idx_1m]
    ts = b["ts"]
    price = b["c"]
    if price <= 0:
        return None

    feats = {"pair": pair, "ts_ms": ts, "entry_price": price}

    # ----- A) Precio multi-timeframe -----
    # 1m
    closes_1m = [x["c"] for x in bars_1m[max(0, idx_1m - 200):idx_1m + 1]]
    highs_1m  = [x["h"] for x in bars_1m[max(0, idx_1m - 200):idx_1m + 1]]
    lows_1m   = [x["l"] for x in bars_1m[max(0, idx_1m - 200):idx_1m + 1]]
    feats["rsi14_1m"]  = rsi(closes_1m, 14)
    feats["atr_pct_1m"] = atr_pct(highs_1m, lows_1m, closes_1m, 14) or 0
    sma20 = sma(closes_1m, 20)
    sma50 = sma(closes_1m, 50)
    feats["dist_ma20_1m"] = (price / sma20 - 1) * 100 if sma20 else 0
    feats["dist_ma50_1m"] = (price / sma50 - 1) * 100 if sma50 else 0

    # 5m
    i5 = find_le(ts_idx_5m, ts)
    if i5 < 30:
        return None  # no hay historial suficiente
    closes_5m = [x["c"] for x in bars_5m[max(0, i5 - 200):i5 + 1]]
    highs_5m  = [x["h"] for x in bars_5m[max(0, i5 - 200):i5 + 1]]
    lows_5m   = [x["l"] for x in bars_5m[max(0, i5 - 200):i5 + 1]]
    feats["rsi14_5m"]  = rsi(closes_5m, 14)
    feats["atr_pct_5m"] = atr_pct(highs_5m, lows_5m, closes_5m, 14) or 0
    _, _, _, pct_b, width = bollinger(closes_5m, 20, 2)
    feats["bb_pct_5m"]  = pct_b or 0.5
    feats["bb_width_5m"] = width or 0

    # 1h
    i1h = find_le(ts_idx_1h, ts)
    if i1h < 30:
        return None
    closes_1h = [x["c"] for x in bars_1h[max(0, i1h - 200):i1h + 1]]
    highs_1h  = [x["h"] for x in bars_1h[max(0, i1h - 200):i1h + 1]]
    lows_1h   = [x["l"] for x in bars_1h[max(0, i1h - 200):i1h + 1]]
    feats["rsi14_1h"]  = rsi(closes_1h, 14)
    feats["atr_pct_1h"] = atr_pct(highs_1h, lows_1h, closes_1h, 14) or 0
    sma20_1h = sma(closes_1h, 20)
    sma50_1h = sma(closes_1h, 50)
    feats["dist_ma20_1h"] = (price / sma20_1h - 1) * 100 if sma20_1h else 0
    feats["dist_ma50_1h"] = (price / sma50_1h - 1) * 100 if sma50_1h else 0
    _, _, _, pb1h, bw1h = bollinger(closes_1h, 20, 2)
    feats["bb_pct_1h"]  = pb1h or 0.5
    feats["bb_width_1h"] = bw1h or 0
    macd_l, _, _ = macd(closes_1h)
    feats["macd_1h"] = macd_l or 0

    # 4h
    i4h = find_le(ts_idx_4h, ts)
    if i4h >= 30:
        closes_4h = [x["c"] for x in bars_4h[max(0, i4h - 100):i4h + 1]]
        feats["rsi14_4h"] = rsi(closes_4h, 14)
        sma50_4h = sma(closes_4h, 50)
        feats["dist_ma50_4h"] = (price / sma50_4h - 1) * 100 if sma50_4h else 0
    else:
        feats["rsi14_4h"] = 50
        feats["dist_ma50_4h"] = 0

    # ----- Momentum y drawdown -----
    # mom_xh = cambio % en x horas usando 1m bars
    def mom_h(h):
        offset = h * 60
        if idx_1m < offset:
            return 0
        return (price / bars_1m[idx_1m - offset]["c"] - 1) * 100
    feats["mom_1h"]  = mom_h(1)
    feats["mom_4h"]  = mom_h(4)
    feats["mom_12h"] = mom_h(12)
    feats["mom_24h"] = mom_h(24)

    # drawdown 7d
    look = min(idx_1m, 7 * 24 * 60)
    if look > 100:
        recent = [x["c"] for x in bars_1m[idx_1m - look:idx_1m + 1]]
        peak = max(recent)
        feats["drawdown_7d"] = (price / peak - 1) * 100 if peak > 0 else 0
    else:
        feats["drawdown_7d"] = 0

    # ----- B) Volumen y order flow -----
    vol_window = bars_1m[max(0, idx_1m - 60):idx_1m + 1]
    last_vol = vol_window[-1]["v"] if vol_window else 0
    avg_vol_60m = sum(x["v"] for x in vol_window[:-1]) / max(1, len(vol_window) - 1)
    feats["vol_ratio_1h"] = (last_vol / avg_vol_60m) if avg_vol_60m > 0 else 1
    # vol Z-score sobre 7 dias
    dlook = min(idx_1m, 7 * 24 * 60)
    if dlook > 1000:
        vols = [x["v"] for x in bars_1m[idx_1m - dlook:idx_1m]]
        m = sum(vols) / len(vols)
        var = sum((v - m) ** 2 for v in vols) / len(vols)
        sd = math.sqrt(var) or 1
        feats["vol_zscore_7d"] = (last_vol - m) / sd
    else:
        feats["vol_zscore_7d"] = 0

    # Taker buy ratio (sumando ultima hora)
    tbq_sum = sum(x["tbq"] for x in vol_window)
    qv_sum  = sum(x["qv"] for x in vol_window) or 1
    feats["taker_buy_ratio_1h"] = tbq_sum / qv_sum

    # CVD (cumulative volume delta) ultima hora: suma de (tbb*2 - v) por bar
    cvd = sum((x["tbb"] * 2 - x["v"]) for x in vol_window)
    feats["cvd_1h"] = cvd

    # ----- C) Microestructura (proxy) -----
    # Spread proxy: (high - low) / close de ultimas 5 velas 1m
    last5 = bars_1m[max(0, idx_1m - 4):idx_1m + 1]
    if last5:
        spreads = [(x["h"] - x["l"]) / x["c"] * 100 for x in last5 if x["c"] > 0]
        feats["spread_proxy_5m"] = sum(spreads) / len(spreads) if spreads else 0
    else:
        feats["spread_proxy_5m"] = 0
    # Number of trades en ultima hora
    feats["trades_1h"] = sum(x["tr"] for x in vol_window)

    # ----- D) On-chain / funding rates -----
    # Last funding rate
    if funding_arr:
        fts = [r[0] for r in funding_arr]
        i = find_le(fts, ts)
        feats["funding_last"] = funding_arr[i][1] if i >= 0 else 0
        # Avg ultimas 3 funding (24h)
        recent_fr = [r[1] for r in funding_arr[max(0, i - 2):i + 1]] if i >= 0 else []
        feats["funding_avg_24h"] = sum(recent_fr) / len(recent_fr) if recent_fr else 0
    else:
        feats["funding_last"] = 0
        feats["funding_avg_24h"] = 0

    # ----- E) Sentimiento -----
    fng_now = lookup_fng(fng_arr, ts)
    feats["fng_value"] = fng_now if fng_now is not None else 50
    # delta 7d
    fng_7d_ago = lookup_fng(fng_arr, ts - 7 * 86400_000)
    feats["fng_delta_7d"] = (fng_now - fng_7d_ago) if (fng_now is not None and fng_7d_ago is not None) else 0

    # ----- F) Macro cross-asset -----
    for sym in ["DXY", "SP500", "VIX", "GOLD", "US10Y"]:
        v_now = lookup_macro(macro_map, sym, ts)
        v_prev = lookup_macro(macro_map, sym, ts - 7 * 86400_000)
        feats[f"{sym.lower()}_close"] = v_now or 0
        feats[f"{sym.lower()}_chg_7d"] = ((v_now / v_prev - 1) * 100) if (v_now and v_prev) else 0

    # ----- G) Correlacion y contexto -----
    # BTC trend 24h (cambio en BTCUSDT)
    if btc_close_1h_arr and i1h >= 24:
        try:
            btc_now = btc_close_1h_arr[i1h]
            btc_prev = btc_close_1h_arr[i1h - 24]
            feats["btc_trend_24h"] = (btc_now / btc_prev - 1) * 100
        except IndexError:
            feats["btc_trend_24h"] = 0
    else:
        feats["btc_trend_24h"] = 0

    # ETH trend 24h
    if eth_close_1h_arr and i1h >= 24:
        try:
            feats["eth_trend_24h"] = (eth_close_1h_arr[i1h] / eth_close_1h_arr[i1h - 24] - 1) * 100
        except IndexError:
            feats["eth_trend_24h"] = 0
    else:
        feats["eth_trend_24h"] = 0

    # Relative strength del par vs BTC en 4h
    if btc_pair_arr_1m and idx_1m >= 240:
        try:
            pair_chg_4h = (price / bars_1m[idx_1m - 240]["c"] - 1) * 100
            btc_chg_4h = (btc_pair_arr_1m[idx_1m] / btc_pair_arr_1m[idx_1m - 240] - 1) * 100
            feats["rs_vs_btc_4h"] = pair_chg_4h - btc_chg_4h
        except (IndexError, ZeroDivisionError):
            feats["rs_vs_btc_4h"] = 0
    else:
        feats["rs_vs_btc_4h"] = 0

    # ----- H) Tiempo y ciclos -----
    dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
    feats["hour_of_day"] = dt.hour
    feats["day_of_week"] = dt.weekday()
    feats["is_weekend"] = 1 if dt.weekday() >= 5 else 0
    # Sesion activa: 0=Asia, 1=EU, 2=US (UTC)
    hr = dt.hour
    if 0 <= hr < 8:
        feats["session"] = 0
    elif 8 <= hr < 14:
        feats["session"] = 1
    else:
        feats["session"] = 2

    return feats


# ── Pipeline principal ────────────────────────────────────────────────────

def process_pair(con, pair, btc_1h_closes=None, btc_1m_closes=None, eth_1h_closes=None,
                 fng_arr=None, macro_map=None, limit=None):
    """Procesa un par: genera features + labels para cada candidato."""
    bars_1m = load_1m_bars(con, pair)
    if len(bars_1m) < 5000:
        print(f"  ! {pair}: solo {len(bars_1m)} bars 1m, skip")
        return []

    bars_5m = aggregate(bars_1m, 5)
    bars_1h = aggregate(bars_1m, 60)
    bars_4h = aggregate(bars_1m, 240)

    ts_idx_5m = build_index_map(bars_5m)
    ts_idx_1h = build_index_map(bars_1h)
    ts_idx_4h = build_index_map(bars_4h)

    funding_arr = load_funding_map(con, pair)

    print(f"  {pair}: {len(bars_1m):,} 1m | {len(bars_5m):,} 5m | "
          f"{len(bars_1h):,} 1h | {len(bars_4h):,} 4h | funding={len(funding_arr)}")

    # Iterar cada bar 1m como potencial entrada
    # Salto = 5 (cada 5 minutos) para no generar demasiadas filas
    out_rows = []
    skip_step = 5
    examined = 0
    for idx in range(200, len(bars_1m) - 60 * 24, skip_step):
        examined += 1
        if limit and len(out_rows) >= limit:
            break

        # Pre-filtros rapidos (calcular solo rsi y drawdown antes del resto)
        closes_1m_recent = [x["c"] for x in bars_1m[max(0, idx - 50):idx + 1]]
        rsi_quick = rsi(closes_1m_recent, 14)
        # drawdown 7d quick
        look_q = min(idx, 7 * 24 * 60)
        recent_q = [x["c"] for x in bars_1m[idx - look_q:idx + 1]] if look_q > 100 else closes_1m_recent
        peak_q = max(recent_q)
        dd_quick = (bars_1m[idx]["c"] / peak_q - 1) * 100 if peak_q > 0 else 0
        if rsi_quick > PREFILTER_RSI_MAX or dd_quick > PREFILTER_DD_MAX:
            continue

        feats = compute_features(
            bars_1m, idx, bars_5m, ts_idx_5m, bars_1h, ts_idx_1h, bars_4h, ts_idx_4h,
            btc_1h_closes, eth_1h_closes, fng_arr, macro_map, funding_arr, pair,
            btc_1m_closes
        )
        if feats is None:
            continue

        # Labels (6 combos)
        for stop_pct, target_pct, max_h, suffix in LABEL_COMBOS:
            outcome, pnl, held = simulate_trade(bars_1m, idx, stop_pct, target_pct, max_h)
            feats[f"label_{suffix}"] = outcome
            feats[f"pnl_{suffix}"] = round(pnl, 4)
            feats[f"held_{suffix}"] = round(held, 3)

        out_rows.append(feats)

    print(f"  {pair}: examined={examined:,} candidatos={len(out_rows):,}")
    return out_rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", help="Solo este par (sino los 20)")
    ap.add_argument("--limit", type=int, help="Maximo de candidatos por par (smoke)")
    ap.add_argument("--out", help="CSV salida (override)")
    args = ap.parse_args()

    out_csv = args.out or OUT_CSV
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)

    pairs = [args.pair.upper()] if args.pair else TOP_20

    print(f"DB:      {DB_PATH}")
    print(f"Salida:  {out_csv}")
    print(f"Pares:   {len(pairs)}")
    print(f"Filtros: RSI<={PREFILTER_RSI_MAX}, DD<={PREFILTER_DD_MAX}%")

    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA temp_store=MEMORY")
    con.execute("PRAGMA cache_size=-100000")

    # Datos comunes
    fng_arr = load_fng_map(con)
    macro_map = load_macro_map(con)
    btc_1m = load_1m_bars(con, "BTCUSDT")
    if btc_1m:
        btc_1h = aggregate(btc_1m, 60)
        btc_1h_closes = [b["c"] for b in btc_1h]
        btc_1m_closes = [b["c"] for b in btc_1m]
    else:
        btc_1h_closes = []
        btc_1m_closes = []
    eth_1m = load_1m_bars(con, "ETHUSDT")
    if eth_1m:
        eth_1h = aggregate(eth_1m, 60)
        eth_1h_closes = [b["c"] for b in eth_1h]
    else:
        eth_1h_closes = []

    print(f"  F&G entries: {len(fng_arr)}")
    print(f"  Macro symbols: {len(macro_map)}")
    print(f"  BTC bars 1m: {len(btc_1m):,}")
    print(f"  ETH bars 1m: {len(eth_1m):,}")
    print()

    # Procesar pares
    all_rows = []
    for pair in pairs:
        try:
            rows = process_pair(con, pair, btc_1h_closes, btc_1m_closes,
                                eth_1h_closes, fng_arr, macro_map, limit=args.limit)
            all_rows.extend(rows)
        except Exception as e:
            print(f"  XX error procesando {pair}: {e}")

    con.close()

    if not all_rows:
        print("\nNO se generaron filas. Verifica que la DB tenga datos.")
        return

    # Determinar columnas (set union)
    columns = set()
    for row in all_rows:
        columns.update(row.keys())
    columns = sorted(columns)

    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in all_rows:
            writer.writerow(row)

    print(f"\n+ CSV escrito: {out_csv}")
    print(f"  Filas: {len(all_rows):,}")
    print(f"  Columnas: {len(columns)}")


if __name__ == "__main__":
    main()
