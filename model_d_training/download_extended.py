"""
download_extended.py — Motor de descarga completa para reentrenamiento del bot.

Descarga, desde 2024-01-01 hasta hoy, los siguientes datos en SQLite:

  1. OHLCV de 1 minuto para los 20 pares (Binance Spot)            -> tabla ohlcv_1m
  2. Funding rates de perpetuos (Binance Futures, cada 8h)         -> tabla funding_rates
  3. Open Interest de perpetuos (Binance Futures, cada 1h)         -> tabla open_interest
  4. Macro: DXY, S&P 500, VIX, ORO (Yahoo Finance, daily)          -> tabla macro_indicators
  5. Fear & Greed Index diario (alternative.me)                    -> tabla fear_greed
  6. BTC Dominance diario (CoinGecko)                              -> tabla btc_dominance

Caracteristicas:

  - Resume automatico: si una pasada se corta, la siguiente continua donde quedo
    (por par y por tipo de dato).
  - Una sola pasada larga (modo recomendado): bash de 3-8 horas sin intervencion.
  - Rate limiting respetuoso: 0.1s entre chunks de klines, mas para Yahoo.
  - Reporta progreso por par y total de filas descargadas.
  - Smoke test integrado: --smoke ejecuta solo BTCUSDT 7 dias para validar conexion.

Uso:
    cd crypto_bot
    python -m model_d_training.download_extended            # descarga completa
    python -m model_d_training.download_extended --smoke    # smoke test 7 dias BTC
    python -m model_d_training.download_extended --only ohlcv_1m    # solo 1m klines
    python -m model_d_training.download_extended --only macro       # solo macro
    python -m model_d_training.download_extended --resume           # continua descarga
    python -m model_d_training.download_extended --start 2025-01-01 # cambia fecha inicio

Salidas:
    crypto_bot/model_d_training/state/data_extended.db (nueva DB, no toca data_2026.db)

Variables de entorno:
    EXTENDED_DB_PATH   override del path de la DB
    EXTENDED_START_DT  override del start date (formato YYYY-MM-DD)
"""

import os
import sys
import time
import json
import sqlite3
import urllib.request
import urllib.parse
import argparse
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bot.top20_pairs import TOP_20


# ── Configuracion ────────────────────────────────────────────────────────

DB_PATH = os.environ.get(
    "EXTENDED_DB_PATH",
    os.path.join(os.path.dirname(__file__), "state", "data_extended.db"),
)
START_DATE = datetime.fromisoformat(
    os.environ.get("EXTENDED_START_DT", "2024-01-01")
).replace(tzinfo=timezone.utc)

# APIs
BINANCE_KLINES   = "https://api.binance.com/api/v3/klines"
BINANCE_FUNDING  = "https://fapi.binance.com/fapi/v1/fundingRate"
BINANCE_OI       = "https://fapi.binance.com/futures/data/openInterestHist"
FNG_URL          = "https://api.alternative.me/fng/?limit=0&format=json"
COINGECKO_GLOBAL = "https://api.coingecko.com/api/v3/global"
YAHOO_CHART      = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"

# Macro tickers (Yahoo Finance)
MACRO_SYMBOLS = {
    "DXY":    "DX-Y.NYB",   # US Dollar Index
    "SP500":  "^GSPC",      # S&P 500
    "VIX":    "^VIX",       # Volatility Index
    "GOLD":   "GC=F",       # Gold Futures
    "US10Y":  "^TNX",       # 10-Year Treasury yield
}

# Mapeo de pares spot -> perpetual (algunos no tienen perpetual)
PERP_MAP = {
    "BTCUSDT": "BTCUSDT", "ETHUSDT": "ETHUSDT", "BNBUSDT": "BNBUSDT",
    "SOLUSDT": "SOLUSDT", "XRPUSDT": "XRPUSDT", "ADAUSDT": "ADAUSDT",
    "AVAXUSDT": "AVAXUSDT", "DOTUSDT": "DOTUSDT", "LINKUSDT": "LINKUSDT",
    "POLUSDT": "POLUSDT",  # ex-MATIC
    "DOGEUSDT": "DOGEUSDT", "SHIBUSDT": "1000SHIBUSDT",  # perp uses 1000SHIB
    "NEARUSDT": "NEARUSDT", "APTUSDT": "APTUSDT", "SUIUSDT": "SUIUSDT",
    "INJUSDT": "INJUSDT", "RENDERUSDT": "RENDERUSDT",
    "TIAUSDT": "TIAUSDT", "SEIUSDT": "SEIUSDT", "FETUSDT": "FETUSDT",
}


# ── Logging mini ──────────────────────────────────────────────────────────

def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def log(msg):
    print(f"[{_now()}] {msg}", flush=True)


# ── HTTP helper ───────────────────────────────────────────────────────────

def http_json(url, max_retries=5, timeout=20, headers=None):
    """Fetch JSON con reintentos exponenciales.

    Los errores 4xx (cliente: rango invalido, endpoint restringido, symbol
    inexistente) NO se reintentan — un 400 no se arregla esperando, y con
    5 retries x 20 pares el refresco diario perdia ~6 min solo en OI."""
    last_err = None
    for attempt in range(max_retries):
        try:
            h = {"User-Agent": "BotTrainer/2.0"}
            if headers:
                h.update(headers)
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500:
                raise RuntimeError(f"HTTP {e.code} (sin retry): {url[:80]}...")
            last_err = e
            wait = min(2 ** attempt, 30)
            if attempt < max_retries - 1:
                log(f"  ! retry {attempt+1}/{max_retries} en {wait}s ({e})")
                time.sleep(wait)
        except Exception as e:
            last_err = e
            wait = min(2 ** attempt, 30)
            if attempt < max_retries - 1:
                log(f"  ! retry {attempt+1}/{max_retries} en {wait}s ({e})")
                time.sleep(wait)
    raise RuntimeError(f"HTTP fallo tras {max_retries}: {url[:80]}... | {last_err}")


# ── Schema ────────────────────────────────────────────────────────────────

def init_db():
    """Crea todas las tablas necesarias e indices."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    c = con.cursor()

    # 1) OHLCV 1m: tabla principal
    c.execute("""
        CREATE TABLE IF NOT EXISTS ohlcv_1m (
            pair      TEXT NOT NULL,
            ts_ms     INTEGER NOT NULL,
            open      REAL, high REAL, low REAL, close REAL,
            volume    REAL, quote_vol REAL, trades INTEGER,
            taker_buy_base REAL, taker_buy_quote REAL,
            PRIMARY KEY (pair, ts_ms)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_ohlcv1m ON ohlcv_1m(pair, ts_ms)")

    # 2) Funding rates (cada 8h en Binance perpetuals)
    c.execute("""
        CREATE TABLE IF NOT EXISTS funding_rates (
            pair  TEXT NOT NULL,
            ts_ms INTEGER NOT NULL,
            rate  REAL,
            PRIMARY KEY (pair, ts_ms)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_fund ON funding_rates(pair, ts_ms)")

    # 3) Open interest histórico (cada 1h via Binance, 5min para últimos 30 dias)
    c.execute("""
        CREATE TABLE IF NOT EXISTS open_interest (
            pair          TEXT NOT NULL,
            ts_ms         INTEGER NOT NULL,
            oi_contracts  REAL,
            oi_usd        REAL,
            PRIMARY KEY (pair, ts_ms)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_oi ON open_interest(pair, ts_ms)")

    # 4) Macro indicators (daily)
    c.execute("""
        CREATE TABLE IF NOT EXISTS macro_indicators (
            symbol TEXT NOT NULL,
            ts_ms  INTEGER NOT NULL,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            PRIMARY KEY (symbol, ts_ms)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_macro ON macro_indicators(symbol, ts_ms)")

    # 5) Fear & Greed
    c.execute("""
        CREATE TABLE IF NOT EXISTS fear_greed (
            ts_ms INTEGER PRIMARY KEY,
            value INTEGER, classification TEXT
        )
    """)

    # 6) BTC Dominance
    c.execute("""
        CREATE TABLE IF NOT EXISTS btc_dominance (
            ts_ms INTEGER PRIMARY KEY,
            dominance REAL
        )
    """)

    # Tabla de control de descarga (resume)
    c.execute("""
        CREATE TABLE IF NOT EXISTS download_progress (
            kind TEXT NOT NULL,     -- 'ohlcv_1m' | 'funding' | 'oi' | 'macro'
            pair TEXT NOT NULL,
            last_ts_ms INTEGER,
            completed_at TEXT,
            rows_total INTEGER DEFAULT 0,
            PRIMARY KEY (kind, pair)
        )
    """)

    con.commit()
    return con


def _get_progress(con, kind, pair):
    row = con.execute(
        "SELECT last_ts_ms, completed_at, rows_total FROM download_progress WHERE kind=? AND pair=?",
        (kind, pair)
    ).fetchone()
    return row  # None si no hay registro

def _set_progress(con, kind, pair, last_ts_ms, completed=False, rows_added=0):
    row = _get_progress(con, kind, pair)
    rows_total = (row[2] if row else 0) + rows_added
    completed_at = datetime.now(timezone.utc).isoformat() if completed else None
    con.execute("""
        INSERT INTO download_progress(kind, pair, last_ts_ms, completed_at, rows_total)
        VALUES (?,?,?,?,?)
        ON CONFLICT(kind, pair) DO UPDATE SET
            last_ts_ms=excluded.last_ts_ms,
            completed_at=excluded.completed_at,
            rows_total=excluded.rows_total
    """, (kind, pair, last_ts_ms, completed_at, rows_total))
    con.commit()


# ── 1) OHLCV 1m ──────────────────────────────────────────────────────────

def fetch_klines_chunk(pair, start_ms, end_ms, interval="1m", limit=1000):
    params = {"symbol": pair, "interval": interval,
              "startTime": start_ms, "endTime": end_ms, "limit": limit}
    return http_json(BINANCE_KLINES + "?" + urllib.parse.urlencode(params))


def download_ohlcv_1m(con, pair, start_dt, end_dt):
    """Descarga 1m del par con resume automatico. Devuelve filas guardadas."""
    progress = _get_progress(con, "ohlcv_1m", pair)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms   = int(end_dt.timestamp()   * 1000)

    if progress and progress[0]:
        # Resume desde el ultimo timestamp guardado + 1 minuto
        resume_ms = progress[0] + 60_000
        if resume_ms < end_ms:
            log(f"  [resume] {pair} desde {datetime.fromtimestamp(resume_ms/1000, tz=timezone.utc).isoformat()}")
            start_ms = resume_ms
        else:
            log(f"  [skip] {pair} ya completo hasta {datetime.fromtimestamp(progress[0]/1000, tz=timezone.utc).isoformat()}")
            return 0

    cur = start_ms
    chunk_ms = 1000 * 60_000  # 1000 bars * 1min
    total = 0
    c = con.cursor()
    last_ts = progress[0] if progress else None
    started_at = time.time()

    while cur < end_ms:
        chunk_end = min(cur + chunk_ms, end_ms)
        try:
            bars = fetch_klines_chunk(pair, cur, chunk_end, interval="1m")
        except Exception as e:
            log(f"  X chunk fallo {pair} @ {cur}: {e}")
            cur = chunk_end
            continue

        if not bars:
            cur = chunk_end
            continue

        rows = []
        for b in bars:
            # b[0]=openTime, 1=open, 2=high, 3=low, 4=close, 5=vol, 6=closeTime,
            # 7=quoteVol, 8=trades, 9=takerBuyBase, 10=takerBuyQuote
            rows.append((
                pair, int(b[0]),
                float(b[1]), float(b[2]), float(b[3]), float(b[4]),
                float(b[5]), float(b[7]), int(b[8]),
                float(b[9]), float(b[10]),
            ))

        c.executemany("""
            INSERT OR REPLACE INTO ohlcv_1m
            (pair, ts_ms, open, high, low, close, volume, quote_vol, trades,
             taker_buy_base, taker_buy_quote)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, rows)
        con.commit()
        total += len(rows)
        last_ts = int(bars[-1][0])
        _set_progress(con, "ohlcv_1m", pair, last_ts, rows_added=len(rows))

        # log periodico
        if total % 50000 == 0:
            elapsed = time.time() - started_at
            rate = total / elapsed if elapsed > 0 else 0
            log(f"  {pair}: {total:,} bars ({rate:.0f}/s) ts={datetime.fromtimestamp(last_ts/1000, tz=timezone.utc).date()}")

        cur = last_ts + 60_000
        time.sleep(0.1)  # respeto rate limit

    _set_progress(con, "ohlcv_1m", pair, last_ts or end_ms, completed=True)
    log(f"  + {pair}: {total:,} filas guardadas")
    return total


# ── 2) Funding rates ──────────────────────────────────────────────────────

def download_funding(con, pair, start_dt, end_dt):
    perp = PERP_MAP.get(pair)
    if not perp:
        log(f"  ! {pair} no tiene mapping a perpetual, skip funding")
        return 0

    progress = _get_progress(con, "funding", pair)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms   = int(end_dt.timestamp()   * 1000)
    if progress and progress[0]:
        start_ms = max(start_ms, progress[0] + 1)

    if start_ms >= end_ms:
        return 0

    cur = start_ms
    total = 0
    last_ts = None
    c = con.cursor()
    # Binance permite hasta 1000 funding records por request, cada uno ~8h apart
    # = ~333 dias por chunk. Asi que normalmente baja entero en una pasada.
    while cur < end_ms:
        params = {"symbol": perp, "startTime": cur, "endTime": end_ms, "limit": 1000}
        try:
            data = http_json(BINANCE_FUNDING + "?" + urllib.parse.urlencode(params))
        except Exception as e:
            log(f"  X funding {pair}: {e}")
            break
        if not data:
            break
        rows = [(pair, int(r["fundingTime"]), float(r["fundingRate"])) for r in data]
        c.executemany("INSERT OR REPLACE INTO funding_rates(pair, ts_ms, rate) VALUES (?,?,?)", rows)
        con.commit()
        total += len(rows)
        last_ts = rows[-1][1]
        _set_progress(con, "funding", pair, last_ts, rows_added=len(rows))
        if len(data) < 1000:
            break
        cur = last_ts + 1
        time.sleep(0.15)

    _set_progress(con, "funding", pair, last_ts or end_ms, completed=True)
    log(f"  + funding {pair}: {total} filas")
    return total


# ── 3) Open Interest ──────────────────────────────────────────────────────

def download_oi(con, pair, start_dt, end_dt):
    """
    OI desde Binance: limit max 500 por request. period=1h max 30d hacia atras.
    Para historico mas largo necesitariamos otro endpoint. Bajamos lo que se pueda.
    """
    perp = PERP_MAP.get(pair)
    if not perp:
        return 0

    # Binance OI historico solo expone ultimos 30 dias.
    # Para mas historico habria que pagar Coinglass. Bajamos los ultimos 30 dias.
    progress = _get_progress(con, "oi", pair)
    end_ms = int(end_dt.timestamp() * 1000)
    start_ms = max(int(start_dt.timestamp() * 1000), end_ms - 30 * 24 * 3600 * 1000)
    if progress and progress[0]:
        start_ms = max(start_ms, progress[0] + 1)

    if start_ms >= end_ms:
        return 0

    cur = start_ms
    chunk_ms = 500 * 3600 * 1000  # 500 bars de 1h
    total = 0
    last_ts = None
    c = con.cursor()
    while cur < end_ms:
        chunk_end = min(cur + chunk_ms, end_ms)
        params = {"symbol": perp, "period": "1h",
                  "startTime": cur, "endTime": chunk_end, "limit": 500}
        try:
            data = http_json(BINANCE_OI + "?" + urllib.parse.urlencode(params))
        except Exception as e:
            log(f"  X OI {pair}: {e}")
            break
        if not data:
            cur = chunk_end
            continue
        rows = [(pair, int(r["timestamp"]),
                 float(r.get("sumOpenInterest", 0)),
                 float(r.get("sumOpenInterestValue", 0))) for r in data]
        c.executemany(
            "INSERT OR REPLACE INTO open_interest(pair, ts_ms, oi_contracts, oi_usd) VALUES (?,?,?,?)",
            rows
        )
        con.commit()
        total += len(rows)
        last_ts = rows[-1][1]
        _set_progress(con, "oi", pair, last_ts, rows_added=len(rows))
        cur = last_ts + 3600_000
        time.sleep(0.15)

    _set_progress(con, "oi", pair, last_ts or end_ms, completed=True)
    log(f"  + OI {pair}: {total} filas")
    return total


# ── 4) Macro (Yahoo Finance) ──────────────────────────────────────────────

def download_macro(con, symbol_key, ticker, start_dt, end_dt):
    """Daily candles via Yahoo Finance chart API."""
    progress = _get_progress(con, "macro", symbol_key)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms   = int(end_dt.timestamp()   * 1000)
    if progress and progress[0]:
        # Re-baja siempre el ultimo dia por si no estaba cerrado
        start_ms = max(start_ms, progress[0] - 86400_000)

    if start_ms >= end_ms:
        return 0

    params = {
        "period1": int(start_ms / 1000),
        "period2": int(end_ms / 1000),
        "interval": "1d",
        "events": "history",
    }
    url = YAHOO_CHART.format(sym=urllib.parse.quote(ticker)) + "?" + urllib.parse.urlencode(params)
    try:
        data = http_json(url, headers={"Accept": "application/json"})
    except Exception as e:
        log(f"  X macro {symbol_key}: {e}")
        return 0

    try:
        result = data["chart"]["result"][0]
        ts_arr = result["timestamp"]
        ohlc = result["indicators"]["quote"][0]
        opens   = ohlc.get("open", [])
        highs   = ohlc.get("high", [])
        lows    = ohlc.get("low", [])
        closes  = ohlc.get("close", [])
        vols    = ohlc.get("volume", [])
    except (KeyError, IndexError, TypeError) as e:
        log(f"  X macro {symbol_key}: respuesta inesperada ({e})")
        return 0

    rows = []
    for i, ts in enumerate(ts_arr):
        if closes[i] is None:
            continue
        rows.append((
            symbol_key, ts * 1000,
            opens[i] or 0.0, highs[i] or 0.0, lows[i] or 0.0,
            closes[i], vols[i] or 0.0,
        ))

    if rows:
        c = con.cursor()
        c.executemany("""
            INSERT OR REPLACE INTO macro_indicators
            (symbol, ts_ms, open, high, low, close, volume)
            VALUES (?,?,?,?,?,?,?)
        """, rows)
        con.commit()
        _set_progress(con, "macro", symbol_key, rows[-1][1], completed=True, rows_added=len(rows))

    log(f"  + macro {symbol_key} ({ticker}): {len(rows)} dias")
    return len(rows)


# ── 5) Fear & Greed ───────────────────────────────────────────────────────

def download_fng(con):
    try:
        data = http_json(FNG_URL)
    except Exception as e:
        log(f"  X F&G: {e}")
        return 0
    rows = []
    for r in data.get("data", []):
        ts_sec = int(r["timestamp"])
        rows.append((ts_sec * 1000, int(r["value"]), r["value_classification"]))
    if rows:
        con.executemany("INSERT OR REPLACE INTO fear_greed(ts_ms, value, classification) VALUES (?,?,?)", rows)
        con.commit()
    log(f"  + F&G: {len(rows)} dias")
    return len(rows)


# ── 6) BTC Dominance (CoinGecko, solo snapshot) ───────────────────────────

def download_btc_dom_snapshot(con):
    try:
        data = http_json(COINGECKO_GLOBAL)
        dom = float(data["data"]["market_cap_percentage"]["btc"])
        ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        con.execute("INSERT OR REPLACE INTO btc_dominance(ts_ms, dominance) VALUES (?,?)", (ts_ms, dom))
        con.commit()
        log(f"  + BTC dominance snapshot: {dom:.2f}%")
        return 1
    except Exception as e:
        log(f"  X BTC dominance: {e}")
        return 0


# ── Reporte de estado ─────────────────────────────────────────────────────

def print_status(con):
    log("=" * 70)
    log("ESTADO DE DESCARGA")
    log("=" * 70)
    counts = {
        "ohlcv_1m":         "SELECT COUNT(*) FROM ohlcv_1m",
        "funding_rates":    "SELECT COUNT(*) FROM funding_rates",
        "open_interest":    "SELECT COUNT(*) FROM open_interest",
        "macro_indicators": "SELECT COUNT(*) FROM macro_indicators",
        "fear_greed":       "SELECT COUNT(*) FROM fear_greed",
        "btc_dominance":    "SELECT COUNT(*) FROM btc_dominance",
    }
    for name, sql in counts.items():
        try:
            n = con.execute(sql).fetchone()[0]
            log(f"  {name:<22s}: {n:>12,} filas")
        except Exception:
            log(f"  {name:<22s}: tabla ausente")
    log("=" * 70)


# ── Orquestador ───────────────────────────────────────────────────────────

def run(only=None, smoke=False, start_dt=None, end_dt=None, pairs=None):
    """
    only: None (todo) o lista subset de {'ohlcv_1m','funding','oi','macro','fng'}
    smoke: si True, solo BTCUSDT 7 dias y macro 30 dias
    """
    end_dt = end_dt or datetime.now(timezone.utc)
    start_dt = start_dt or START_DATE
    pairs = pairs or TOP_20

    if smoke:
        log("SMOKE TEST: BTCUSDT + macro, 7 dias")
        pairs = ["BTCUSDT"]
        start_dt = end_dt - timedelta(days=7)
        only = only or ["ohlcv_1m", "funding", "macro", "fng"]

    log(f"DB:    {DB_PATH}")
    log(f"Rango: {start_dt.isoformat()}  ->  {end_dt.isoformat()}")
    log(f"Pares: {len(pairs)}  ({', '.join(pairs[:5])}{'...' if len(pairs) > 5 else ''})")
    log(f"Tipos: {only or 'todos'}")

    con = init_db()
    sections = only or ["fng", "ohlcv_1m", "funding", "oi", "macro"]
    do = lambda s: s in sections

    if do("fng"):
        log("\n[1/5] Fear & Greed Index")
        download_fng(con)

    if do("ohlcv_1m"):
        log(f"\n[2/5] OHLCV 1m de {len(pairs)} pares")
        for i, pair in enumerate(pairs, 1):
            log(f"  ({i}/{len(pairs)}) {pair}")
            try:
                download_ohlcv_1m(con, pair, start_dt, end_dt)
            except Exception as e:
                log(f"  XX error fatal {pair}: {e}")

    if do("funding"):
        log(f"\n[3/5] Funding rates de perpetuals")
        for pair in pairs:
            try:
                download_funding(con, pair, start_dt, end_dt)
            except Exception as e:
                log(f"  XX error funding {pair}: {e}")

    if do("oi"):
        log(f"\n[4/5] Open Interest (ultimos 30 dias, limitado por Binance)")
        for pair in pairs:
            try:
                download_oi(con, pair, start_dt, end_dt)
            except Exception as e:
                log(f"  XX error OI {pair}: {e}")

    if do("macro"):
        log(f"\n[5/5] Macro indicators (Yahoo Finance)")
        for sym_key, ticker in MACRO_SYMBOLS.items():
            try:
                download_macro(con, sym_key, ticker, start_dt, end_dt)
            except Exception as e:
                log(f"  XX error macro {sym_key}: {e}")

    download_btc_dom_snapshot(con)

    print_status(con)
    con.close()
    log("\nDESCARGA COMPLETA")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="Smoke test: BTC 7 dias")
    ap.add_argument("--only", nargs="+",
                    choices=["ohlcv_1m", "funding", "oi", "macro", "fng"],
                    help="Solo descargar estos tipos")
    ap.add_argument("--start", help="Fecha inicio YYYY-MM-DD (default 2024-01-01)")
    ap.add_argument("--end", help="Fecha fin YYYY-MM-DD (default ahora)")
    ap.add_argument("--pair", help="Solo este par (override TOP_20)")
    ap.add_argument("--resume", action="store_true", help="(default) Resume automatico")
    ap.add_argument("--status", action="store_true", help="Solo muestra estado y sale")
    args = ap.parse_args()

    if args.status:
        con = init_db()
        print_status(con)
        con.close()
        return

    start_dt = (datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
                if args.start else None)
    end_dt = (datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
              if args.end else None)
    pairs = [args.pair.upper()] if args.pair else None

    run(only=args.only, smoke=args.smoke, start_dt=start_dt, end_dt=end_dt, pairs=pairs)


if __name__ == "__main__":
    main()
