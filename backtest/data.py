"""
Descarga y cache de velas historicas de Binance (endpoint publico, sin API key).

Uso:
    python -m backtest.data                 # descarga 1d y 4h de todo el universo
    python -m backtest.data --interval 1h

Los CSV quedan en backtest/data/ (ignorado por git).
"""
import os
import sys
import time

import pandas as pd
import requests

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
API = os.getenv("BINANCE_PUBLIC_URL", "https://api.binance.com") + "/api/v3/klines"

# Universo amplio y FIJO, elegido por antiguedad/liquidez, incluyendo monedas
# que les fue mal (EOS, FIL, ETC, XLM...) para no sesgar el backtest hacia
# las ganadoras de hoy (sesgo de supervivencia).
UNIVERSE = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT",
    "AVAXUSDT", "DOTUSDT", "LINKUSDT", "LTCUSDT", "DOGEUSDT", "TRXUSDT",
    "NEARUSDT", "ATOMUSDT", "UNIUSDT", "ETCUSDT", "XLMUSDT", "BCHUSDT",
    "FILUSDT", "EOSUSDT", "MATICUSDT", "AAVEUSDT", "ALGOUSDT", "VETUSDT",
    "SHIBUSDT", "INJUSDT", "APTUSDT", "SUIUSDT", "ARBUSDT", "OPUSDT",
]

INTERVAL_MS = {"1h": 3600_000, "4h": 4 * 3600_000, "1d": 86400_000}
START_MS = int(pd.Timestamp("2019-01-01", tz="UTC").timestamp() * 1000)


def _path(symbol, interval):
    return os.path.join(DATA_DIR, f"{symbol}_{interval}.csv")


def download(symbol, interval="1d", verbose=True):
    """Descarga incremental: continua desde la ultima vela guardada."""
    os.makedirs(DATA_DIR, exist_ok=True)
    path = _path(symbol, interval)
    old = None
    start = START_MS
    if os.path.exists(path):
        old = pd.read_csv(path)
        if len(old):
            start = int(old["t"].iloc[-1])  # re-descarga la ultima (pudo estar abierta)
            old = old.iloc[:-1]
    rows = []
    while True:
        for attempt in range(5):
            try:
                r = requests.get(API, params={"symbol": symbol, "interval": interval,
                                              "startTime": start, "limit": 1000}, timeout=20)
                if r.status_code == 429:
                    time.sleep(10)
                    continue
                data = r.json()
                break
            except Exception:
                time.sleep(2 + attempt * 2)
        else:
            raise RuntimeError(f"sin respuesta de Binance para {symbol}")
        if isinstance(data, dict):  # error (simbolo invalido, etc.)
            if verbose:
                print(f"  {symbol}: {data.get('msg')}")
            break
        if not data:
            break
        rows.extend(data)
        if len(data) < 1000:
            break
        start = data[-1][0] + INTERVAL_MS[interval]
        time.sleep(0.15)
    if not rows and old is None:
        return None
    new = pd.DataFrame([[x[0], float(x[1]), float(x[2]), float(x[3]), float(x[4]),
                         float(x[5]), float(x[7])] for x in rows],
                       columns=["t", "o", "h", "l", "c", "v", "qv"])
    df = pd.concat([old, new]) if old is not None else new
    df = df.drop_duplicates("t").sort_values("t")
    # descartar la vela aun abierta
    now_ms = int(time.time() * 1000)
    df = df[df["t"] + INTERVAL_MS[interval] <= now_ms]
    df.to_csv(path, index=False)
    if verbose:
        print(f"  {symbol} {interval}: {len(df)} velas "
              f"({pd.to_datetime(df['t'].iloc[0], unit='ms').date()} -> "
              f"{pd.to_datetime(df['t'].iloc[-1], unit='ms').date()})")
    return df


def load(symbol, interval="1d"):
    path = _path(symbol, interval)
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    df.index = pd.to_datetime(df["t"], unit="ms", utc=True)
    return df


def load_panel(interval="1d", symbols=None, field="c"):
    """DataFrame fechas x simbolos con el campo pedido (c, o, h, l, qv)."""
    out = {}
    for s in symbols or UNIVERSE:
        df = load(s, interval)
        if df is not None and len(df):
            out[s] = df[field]
    return pd.DataFrame(out).sort_index()


if __name__ == "__main__":
    intervals = ["1d", "4h"]
    if "--interval" in sys.argv:
        intervals = [sys.argv[sys.argv.index("--interval") + 1]]
    for iv in intervals:
        print(f"== {iv} ==")
        for s in UNIVERSE:
            download(s, iv)
