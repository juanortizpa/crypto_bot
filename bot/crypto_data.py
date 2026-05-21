"""
Capa de datos para Crypto — todo viene de Binance API (gratis, sin limites).
No necesita yfinance.

Funciones:
  get_bars()          → velas OHLCV historicas
  get_price()         → precio actual
  technical_score()   → snapshot tecnico completo
  get_fear_greed()    → Fear & Greed Index (alternative.me)
  get_btc_dominance() → dominancia de BTC via CoinGecko
  sma(), rsi(), atr() → indicadores tecnicos
"""
import os, sys, json, urllib.request
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from binance_client import get_klines, get_ticker_24h, get_ticker_price

# ── Session cache ─────────────────────────────────────────────────────
_cache = {}

def clear_cache():
    _cache.clear()


# ── Historical bars ───────────────────────────────────────────────────

def get_bars(symbol, interval="1d", limit=200):
    """
    Velas OHLCV desde Binance.
    symbol: 'BTCUSDT', 'ETHUSDT', etc.
    interval: '1h', '4h', '1d'
    Retorna lista de dicts [{t, o, h, l, c, v}, ...]
    """
    key = f"bars_{symbol}_{interval}_{limit}"
    if key in _cache:
        return _cache[key]

    bars = get_klines(symbol, interval=interval, limit=limit)
    _cache[key] = bars
    return bars


def get_price(symbol):
    """Precio actual de un par."""
    key = f"price_{symbol}"
    if key in _cache:
        return _cache[key]
    price = get_ticker_price(symbol)
    if price:
        _cache[key] = price
    return price


# ── Indicadores tecnicos ──────────────────────────────────────────────

def sma(bars, period):
    """Simple Moving Average."""
    closes = [b["c"] for b in bars]
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def ema(bars, period):
    """Exponential Moving Average."""
    closes = [b["c"] for b in bars]
    if len(closes) < period:
        return None
    mult = 2 / (period + 1)
    ema_val = sum(closes[:period]) / period
    for c in closes[period:]:
        ema_val = (c - ema_val) * mult + ema_val
    return ema_val


def rsi(bars, period=14):
    """Relative Strength Index."""
    closes = [b["c"] for b in bars]
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0:
        return 100.0
    return round(100 - 100 / (1 + ag / al), 1)


def atr(bars, period=14):
    """Average True Range — volatilidad."""
    if len(bars) < period + 1:
        return None
    trs = []
    for i in range(1, len(bars)):
        high  = bars[i]["h"]
        low   = bars[i]["l"]
        prev_c = bars[i-1]["c"]
        tr = max(high - low, abs(high - prev_c), abs(low - prev_c))
        trs.append(tr)
    return sum(trs[-period:]) / period


def avg_volume(bars, period=20):
    """Volumen promedio en periodo."""
    vols = [b["v"] for b in bars]
    if len(vols) < period:
        return None
    return sum(vols[-period:]) / period


def buy_sell_ratio(bars, period=7):
    """
    Ratio de volumen de compra vs total.
    Binance klines incluyen 'tb' (taker buy volume).
    > 0.5 = mas compradores, < 0.5 = mas vendedores
    """
    if len(bars) < period:
        return None
    recent = bars[-period:]
    total_vol = sum(b["v"] for b in recent)
    total_buy = sum(b.get("tb", b["v"] * 0.5) for b in recent)
    if total_vol == 0:
        return 0.5
    return round(total_buy / total_vol, 3)


# ── Fear & Greed Index ────────────────────────────────────────────────

def get_fear_greed():
    """
    Fear & Greed Index de alternative.me (0-100).
    0 = Extreme Fear, 100 = Extreme Greed
    Retorna dict {value, classification}
    """
    key = "fear_greed"
    if key in _cache:
        return _cache[key]

    try:
        url = "https://api.alternative.me/fng/?limit=1&format=json"
        req = urllib.request.Request(url, headers={"User-Agent": "CryptoBot/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())

        if data.get("data"):
            entry = data["data"][0]
            result = {
                "value":          int(entry["value"]),
                "classification": entry["value_classification"],
            }
            _cache[key] = result
            return result
    except Exception:
        pass

    return {"value": 50, "classification": "Neutral"}


# ── BTC Dominance ─────────────────────────────────────────────────────

def get_btc_dominance():
    """
    BTC dominance % via CoinGecko API (gratis).
    Retorna float (ej: 54.3)
    """
    key = "btc_dominance"
    if key in _cache:
        return _cache[key]

    try:
        url = "https://api.coingecko.com/api/v3/global"
        req = urllib.request.Request(url, headers={"User-Agent": "CryptoBot/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())

        dom = data.get("data", {}).get("market_cap_percentage", {}).get("btc")
        if dom:
            _cache[key] = round(dom, 2)
            return _cache[key]
    except Exception:
        pass

    return None


# ── BTC trend (usado por varios factores) ─────────────────────────────

def get_btc_trend():
    """
    Analiza la tendencia de BTC en multiples timeframes.
    Retorna dict con: trend, ma20, ma50, rsi, change_7d, change_24h
    """
    key = "btc_trend"
    if key in _cache:
        return _cache[key]

    bars = get_bars("BTCUSDT", "1d", 60)
    if len(bars) < 50:
        return {"trend": "UNKNOWN"}

    price   = bars[-1]["c"]
    ma20    = sma(bars, 20)
    ma50    = sma(bars, 50)
    rsi14   = rsi(bars, 14)

    # Cambios porcentuales
    change_24h = round((bars[-1]["c"] - bars[-2]["c"]) / bars[-2]["c"] * 100, 2) if len(bars) >= 2 else 0
    change_7d  = round((bars[-1]["c"] - bars[-7]["c"]) / bars[-7]["c"] * 100, 2) if len(bars) >= 7 else 0

    # Determinar tendencia
    if price > ma20 and price > ma50 and (ma20 and ma50 and ma20 > ma50):
        trend = "BULLISH"
    elif price > ma50:
        trend = "NEUTRAL_BULL"
    elif price < ma50 and price < ma20:
        trend = "BEARISH"
    else:
        trend = "NEUTRAL"

    result = {
        "trend":      trend,
        "price":      price,
        "ma20":       round(ma20, 2) if ma20 else None,
        "ma50":       round(ma50, 2) if ma50 else None,
        "rsi":        rsi14,
        "change_24h": change_24h,
        "change_7d":  change_7d,
    }
    _cache[key] = result
    return result


# ── Technical score completo ──────────────────────────────────────────

def technical_score(symbol):
    """
    Snapshot tecnico completo para un par crypto.
    Similar a technical_score() del bot de acciones pero usando Binance.
    """
    key = f"tech_{symbol}"
    if key in _cache:
        return _cache[key]

    bars = get_bars(symbol, "1d", 200)
    if len(bars) < 20:
        return {}

    price = bars[-1]["c"]

    # Indicadores
    ma20_val  = sma(bars, 20)
    ma50_val  = sma(bars, 50) if len(bars) >= 50 else None
    ma200_val = sma(bars, 200) if len(bars) >= 200 else sma(bars, len(bars))
    rsi14     = rsi(bars, 14)
    atr14     = atr(bars, 14)
    avg_vol   = avg_volume(bars[:-1], 20) if len(bars) > 1 else None  # excluir vela actual (incompleta)
    # Usar penultima vela (completa) para vol ratio; la ultima vela diaria
    # puede estar a mitad de camino y daria volumen artificialmente bajo
    vol_24h   = bars[-2]["v"] if len(bars) >= 2 else (bars[-1]["v"] if bars else 0)
    vol_ratio = round(vol_24h / avg_vol, 2) if avg_vol and avg_vol > 0 else None

    # Stats de 24h desde Binance
    ticker = get_ticker_24h(symbol)
    change_24h = float(ticker.get("priceChangePercent", 0)) if isinstance(ticker, dict) and "priceChangePercent" in ticker else None

    # High historico
    high_all = max(b["h"] for b in bars)
    pct_from_high = round((price - high_all) / high_all * 100, 1)

    # Buy/sell ratio
    bs_ratio = buy_sell_ratio(bars, 7)

    result = {
        "symbol":            symbol,
        "price":             round(price, 6),
        "ma20":              round(ma20_val, 6) if ma20_val else None,
        "ma50":              round(ma50_val, 6) if ma50_val else None,
        "ma200":             round(ma200_val, 6) if ma200_val else None,
        "rsi14":             rsi14,
        "atr14":             round(atr14, 6) if atr14 else None,
        "atr_pct":           round(atr14 / price * 100, 2) if atr14 and price else None,
        "avg_vol_20d":       avg_vol,
        "vol_24h":           vol_24h,
        "vol_ratio":         vol_ratio,
        "change_24h":        change_24h,
        "pct_from_high":     pct_from_high,
        "above_ma20":        price > ma20_val if ma20_val else False,
        "above_ma50":        price > ma50_val if price and ma50_val else False,
        "buy_sell_ratio":    bs_ratio,
    }
    _cache[key] = result
    return result
