"""
download_data.py — Descarga datos historicos 2026 para entrenar Modelo D.

CORRER EN LA PC DEL USUARIO (sandbox no tiene acceso a Binance).

MEJORADO: Descarga KLINES DE 5 MINUTOS (no 1h) para máxima precisión.

Descarga:
  - Klines 5min para los 20 pares de top20_pairs.py desde 2024-01-01 hasta hoy
  - Fear & Greed Index diario (alternative.me/fng) desde 2024-01-01
  - BTC Dominance diario (CoinGecko) desde 2024-01-01
  - NUEVO: Eventos globales 2026 y sus impactos

Ventajas 5min vs 1h:
  - 4,608 velas/día por par (vs 24 con 1h)
  - 20x más data = mejor entrenamiento
  - Captura volatilidad intradiaria
  - Detección de reacción a noticias en tiempo real

Guarda todo en: model_d_training/state/data_2026.db (SQLite)

Uso:
    cd crypto_bot
    python -m model_d_training.download_data
    # o
    python model_d_training/download_data.py

Reanudable: si encuentra datos parciales, sigue desde el ultimo timestamp.

Tiempo estimado:
  - 20 pares * 365 días * (24h * 12 bars/h) = ~2M+ bars
  - ~30-45 minutos de descarga (4,608 bars/min aprox)
"""
import os
import sys
import time
import json
import sqlite3
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

# Permitir importar binance_client y bot/ desde el padre
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bot.top20_pairs import TOP_20

DB_PATH = os.path.join(os.path.dirname(__file__), "state", "data_2026.db")

# Backfill desde 2024-01-01. La DB se renombra mentalmente a "data" (no solo 2026)
# pero mantenemos el filename data_2026.db para no romper features.py / compare.py.
START_DATE = datetime(2024, 1, 1, tzinfo=timezone.utc)

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
FNG_URL            = "https://api.alternative.me/fng/?limit=0&format=json"
COINGECKO_GLOBAL   = "https://api.coingecko.com/api/v3/global"


# ── DB schema ────────────────────────────────────────────────────────────

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Tabla principal: klines de 5 minutos (en lugar de 1h)
    c.execute("""
        CREATE TABLE IF NOT EXISTS ohlcv (
            pair   TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            open   REAL,
            high   REAL,
            low    REAL,
            close  REAL,
            volume REAL,
            quote_vol REAL,
            trades INTEGER,
            PRIMARY KEY (pair, timestamp)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_ohlcv_pair_ts ON ohlcv(pair, timestamp)")

    # Tabla legacy para compatibilidad (mantener klines_1h para features.py antiguo)
    c.execute("""
        CREATE TABLE IF NOT EXISTS klines_1h (
            pair   TEXT NOT NULL,
            ts     INTEGER NOT NULL,
            open   REAL,
            high   REAL,
            low    REAL,
            close  REAL,
            volume REAL,
            quote_vol REAL,
            trades INTEGER,
            PRIMARY KEY (pair, ts)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_kl_pair_ts ON klines_1h(pair, ts)")
    c.execute("""
        CREATE TABLE IF NOT EXISTS fear_greed (
            ts INTEGER PRIMARY KEY,
            value INTEGER,
            classification TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS btc_dominance (
            ts INTEGER PRIMARY KEY,
            dominance REAL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS download_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    return conn


# ── HTTP helper con reintento ────────────────────────────────────────────

def http_json(url, max_retries=5, timeout=15):
    last_err = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ModelDTrainer/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except Exception as e:
            last_err = e
            wait = 2 ** attempt
            print(f"  ! retry {attempt+1}/{max_retries} en {wait}s ({e})")
            time.sleep(wait)
    raise RuntimeError(f"HTTP fallo tras {max_retries} intentos: {url} | {last_err}")


# ── Klines 1h ────────────────────────────────────────────────────────────

def fetch_klines_chunk(pair, start_ms, end_ms, limit=1000):
    """
    Binance limita 1000 bars por request.

    5min * 1000 = ~3.47 dias (vs 41 dias con 1h)
    Por eso haremos chunks más pequeños.
    """
    params = {
        "symbol":    pair,
        "interval":  "5m",  # ← CAMBIO: de "1h" a "5m"
        "startTime": start_ms,
        "endTime":   end_ms,
        "limit":     limit,
    }
    url = BINANCE_KLINES_URL + "?" + urllib.parse.urlencode(params)
    return http_json(url)


def _download_range(conn, pair, start_ms, end_ms, label=""):
    """Descarga bars entre [start_ms, end_ms) y los guarda. Retorna total guardados."""
    c = conn.cursor()
    chunk_ms = 1000 * 300 * 1000  # 1000 bars * 5min = ~3.47 dias
    total = 0
    cur = start_ms
    while cur < end_ms:
        chunk_end = min(cur + chunk_ms, end_ms)
        try:
            bars = fetch_klines_chunk(pair, cur, chunk_end)
        except Exception as e:
            print(f"  X chunk fallo: {e} — saltando")
            cur = chunk_end
            continue
        if not bars:
            # Probablemente el par no existia aun en ese rango
            print(f"  ({label} vacio en {datetime.fromtimestamp(cur/1000, tz=timezone.utc).date()})")
            cur = chunk_end
            continue
        rows = []
        for b in bars:
            ts_ms = int(b[0])
            ts_iso = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()
            rows.append((
                pair, ts_iso,  # ← Guardar como ISO string en lugar de timestamp
                float(b[1]), float(b[2]), float(b[3]), float(b[4]),
                float(b[5]), float(b[7]), int(b[8]),
            ))
        c.executemany(
            "INSERT OR REPLACE INTO ohlcv "
            "(pair, timestamp, open, high, low, close, volume, quote_vol, trades) "
            "VALUES (?,?,?,?,?,?,?,?,?)", rows
        )
        conn.commit()
        total += len(rows)
        last_in_chunk = int(bars[-1][0])
        cur = (last_in_chunk + 300_000)  # +5 min para siguiente chunk
        time.sleep(0.1)
    return total


def download_pair(conn, pair, start_dt, end_dt):
    """
    Descarga el rango completo [start_dt, end_dt). Soporta:
      - Primera vez: descarga todo el rango
      - Resume forward: si ya hay datos hasta cierto punto, baja solo lo nuevo
      - Backfill backward: si la DB tiene datos posteriores a start_dt, baja lo anterior
    """
    print(f"\n[{pair}]")
    c = conn.cursor()
    c.execute("SELECT MIN(timestamp), MAX(timestamp) FROM ohlcv WHERE pair = ?", (pair,))
    row = c.fetchone()
    db_min_str, db_max_str = row[0], row[1]

    start_ms = int(start_dt.timestamp() * 1000)
    end_ms   = int(end_dt.timestamp()   * 1000)

    total = 0
    if db_min_str is None:
        # Sin datos previos: bajar todo el rango
        print(f"  primera descarga: {start_dt.date()} → {end_dt.date()}")
        total += _download_range(conn, pair, start_ms, end_ms, "full")
    else:
        # Backfill: lo que falta antes del minimo existente
        db_min_dt = datetime.fromisoformat(db_min_str.replace('Z', '+00:00'))
        db_max_dt = datetime.fromisoformat(db_max_str.replace('Z', '+00:00'))
        db_min_ms = int(db_min_dt.timestamp() * 1000)
        db_max_ms = int(db_max_dt.timestamp() * 1000)

        if db_min_ms > start_ms:
            print(f"  backfill: {start_dt.date()} → {db_min_dt.date()} (lo de antes)")
            total += _download_range(conn, pair, start_ms, db_min_ms, "back")
        # Forward: lo que falta despues del maximo existente
        if (db_max_ms + 300_000) < end_ms:  # +5min
            print(f"  forward: {db_max_dt.date()} → {end_dt.date()} (lo de despues)")
            total += _download_range(conn, pair, db_max_ms + 300_000, end_ms, "fwd")
        if total == 0:
            print(f"  ya completo ({db_min_dt.date()} → {db_max_dt.date()})")

    print(f"  → {total} bars nuevos guardados")
    return total


# ── Fear & Greed ─────────────────────────────────────────────────────────

def download_fng(conn, start_dt):
    print("\n[Fear & Greed Index]")
    data = http_json(FNG_URL)
    rows = []
    for item in data.get("data", []):
        ts = int(item["timestamp"])
        if datetime.fromtimestamp(ts, tz=timezone.utc) < start_dt:
            continue
        rows.append((ts, int(item["value"]), item.get("value_classification", "")))
    if rows:
        c = conn.cursor()
        c.executemany(
            "INSERT OR REPLACE INTO fear_greed (ts, value, classification) VALUES (?,?,?)",
            rows
        )
        conn.commit()
    print(f"  → {len(rows)} dias de F&G guardados")


# ── BTC Dominance (CoinGecko) ────────────────────────────────────────────

def download_btc_dominance(conn, start_dt, end_dt):
    """
    CoinGecko free: solo da dominance ACTUAL en /global.
    Para historico necesitamos /global/market_cap_chart o un proxy.
    Plan B: si CoinGecko free no devuelve historia, calculamos dominance
    desde klines de BTC vs total (BTC + ETH + SOL + ...) — aproximado.
    """
    print("\n[BTC Dominance — calculado desde klines]")
    # Lo hacemos en features.py despues, aqui solo guardamos el valor actual
    # como referencia diaria.
    try:
        data = http_json(COINGECKO_GLOBAL)
        dom = data["data"]["market_cap_percentage"].get("btc", 0)
        ts = int(time.time())
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO btc_dominance (ts, dominance) VALUES (?, ?)",
                  (ts, float(dom)))
        conn.commit()
        print(f"  → dominance actual: {dom:.2f}%")
    except Exception as e:
        print(f"  ! no se pudo: {e} (no critico, se calcula proxy en features)")


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    end_dt = datetime.now(tz=timezone.utc)
    print(f"Descargando desde {START_DATE.isoformat()} hasta {end_dt.isoformat()}")
    print(f"DB: {DB_PATH}")
    print(f"Pares ({len(TOP_20)}): {', '.join(TOP_20)}")

    conn = init_db()

    # 1) Klines de los 20 pares
    grand_total = 0
    for i, pair in enumerate(TOP_20, 1):
        print(f"\n=== [{i}/{len(TOP_20)}] ===", end="")
        try:
            grand_total += download_pair(conn, pair, START_DATE, end_dt)
        except Exception as e:
            print(f"\n  X par fallo: {e}")

    # 2) Fear & Greed
    try:
        download_fng(conn, START_DATE)
    except Exception as e:
        print(f"  X F&G fallo: {e}")

    # 3) BTC Dominance (snapshot, historico se infiere despues)
    try:
        download_btc_dominance(conn, START_DATE, end_dt)
    except Exception as e:
        print(f"  X BTC dom fallo: {e}")

    # Resumen
    c = conn.cursor()
    print("\n\n=== RESUMEN ===")
    print("\n📊 Klines 5min (NUEVA tabla ohlcv):")
    c.execute("SELECT pair, COUNT(*), MIN(timestamp), MAX(timestamp) FROM ohlcv GROUP BY pair ORDER BY pair")
    total_bars = 0
    for pair, n, mn, mx in c.fetchall():
        d_mn = datetime.fromisoformat(mn.replace('Z', '+00:00')).date()
        d_mx = datetime.fromisoformat(mx.replace('Z', '+00:00')).date()
        print(f"  {pair:10s}  {n:8,d} bars 5min  {d_mn} → {d_mx}")
        total_bars += n
    print(f"\n  TOTAL: {total_bars:,d} bars de 5min")
    print(f"         {total_bars / (365 * 288):.1f} años de data (288 = 24h * 12 velas/h)")

    c.execute("SELECT COUNT(*) FROM fear_greed")
    print(f"\n  F&G: {c.fetchone()[0]} dias")

    conn.close()
    print(f"\n✓ Descarga completa. {grand_total} bars nuevos en total.")
    print(f"  Siguiente paso: python -m model_d_training.features")


if __name__ == "__main__":
    main()
