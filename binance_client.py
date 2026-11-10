"""
Binance Client — conexion a Binance Spot API (testnet o live).
Usa requests directamente para evitar dependencias pesadas.

Endpoints:
  - Testnet: https://testnet.binance.vision
  - Live:    https://api.binance.com

Funciones principales:
  get_account()     → balance y estado de la cuenta
  get_positions()   → posiciones abiertas (balances > 0)
  get_klines()      → velas OHLCV historicas
  get_ticker_24h()  → stats de las ultimas 24h
  get_orderbook()   → libro de ordenes (buy/sell ratio)
"""
import os
import time
import hmac
import hashlib
import urllib.parse
import urllib.request
import json
from dotenv import load_dotenv

# Cargar .env desde la raiz del proyecto
_ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(_ENV_PATH)

ENV = {
    "BINANCE_API_KEY":    os.getenv("BINANCE_API_KEY", ""),
    # La documentacion usa BINANCE_API_SECRET; versiones anteriores del .env
    # usaban BINANCE_SECRET_KEY. Aceptar ambos nombres.
    "BINANCE_SECRET_KEY": os.getenv("BINANCE_API_SECRET", "") or os.getenv("BINANCE_SECRET_KEY", ""),
    "BINANCE_MODE":       os.getenv("BINANCE_MODE", "testnet"),
    "AUTO_EXECUTE":       os.getenv("AUTO_EXECUTE", "False").lower() == "true",
}

# URLs segun modo
TESTNET_URL = "https://testnet.binance.vision"
LIVE_URL    = "https://api.binance.com"
# Datos publicos de mercado (velas, precios). api.binance.com rechaza IPs de
# EE.UU. (HTTP 451), que es donde corren GitHub Actions y muchos servidores
# gratuitos; data-api.binance.vision sirve los mismos datos sin esa restriccion.
PUBLIC_URL  = os.getenv("BINANCE_PUBLIC_URL", LIVE_URL)

def _base_url():
    return TESTNET_URL if ENV["BINANCE_MODE"] == "testnet" else LIVE_URL


# ── Firma HMAC-SHA256 (requerida para endpoints privados) ────────────

def _sign(params: dict) -> str:
    """Genera la firma HMAC-SHA256 para los parametros."""
    query = urllib.parse.urlencode(params)
    signature = hmac.HMAC(
        ENV["BINANCE_SECRET_KEY"].encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()
    return signature


# Offset reloj local vs servidor de Binance. El reloj de un portatil se
# desvia con los dias; si pasa de 1s, los endpoints firmados devuelven
# error -1021. Calculamos el offset una vez y firmamos con la hora del
# servidor; si aun asi aparece -1021 (deriva posterior), se recalcula y
# se reintenta una vez.
_TIME_OFFSET_MS = None


def _server_time_offset() -> int:
    global _TIME_OFFSET_MS
    if _TIME_OFFSET_MS is None:
        try:
            data = _request("GET", "/api/v3/time")
            _TIME_OFFSET_MS = int(data["serverTime"]) - int(time.time() * 1000)
        except Exception:
            _TIME_OFFSET_MS = 0
    return _TIME_OFFSET_MS


def _request(method, path, params=None, signed=False, force_live=False, _retry=True):
    """
    Hace una request a la API de Binance.
    signed=True agrega timestamp (corregido por offset del servidor) y firma HMAC.
    force_live=True usa la API live (para datos publicos aunque estemos en testnet).
    """
    params = dict(params or {})

    if signed:
        params["timestamp"] = int(time.time() * 1000) + _server_time_offset()
        params.setdefault("recvWindow", 10000)
        params["signature"] = _sign(params)

    base = PUBLIC_URL if force_live else _base_url()
    url = f"{base}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    headers = {
        "X-MBX-APIKEY": ENV["BINANCE_API_KEY"],
        "User-Agent": "CryptoBot/1.0",
    }

    req = urllib.request.Request(url, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        result = {"error": f"HTTP {e.code}", "msg": body}
    except Exception as e:
        return {"error": str(e)}

    # Reloj desviado de nuevo (-1021): recalcular offset y reintentar una vez
    if signed and _retry and "-1021" in str(result.get("msg", "")):
        global _TIME_OFFSET_MS
        _TIME_OFFSET_MS = None
        clean = {k: v for k, v in params.items()
                 if k not in ("timestamp", "signature", "recvWindow")}
        return _request(method, path, clean, signed=True,
                        force_live=force_live, _retry=False)
    return result


# ── Endpoints publicos (no requieren API key) ────────────────────────

def get_klines(symbol, interval="1d", limit=200):
    """
    Velas OHLCV historicas.
    symbol:   'BTCUSDT', 'ETHUSDT', etc.
    interval: '1h', '4h', '1d', '1w'
    limit:    max 1000
    Retorna lista de dicts [{t, o, h, l, c, v}, ...]
    """
    data = _request("GET", "/api/v3/klines", {
        "symbol":   symbol,
        "interval": interval,
        "limit":    limit,
    }, force_live=True)

    if isinstance(data, dict) and "error" in data:
        return []

    bars = []
    for k in data:
        bars.append({
            "t":  k[0],            # open time (ms)
            "o":  float(k[1]),     # open
            "h":  float(k[2]),     # high
            "l":  float(k[3]),     # low
            "c":  float(k[4]),     # close
            "v":  float(k[5]),     # volume (base asset)
            "qv": float(k[7]),     # quote volume (USDT)
            "trades": int(k[8]),   # number of trades
            "tb": float(k[9]),     # taker buy volume (base)
            "tq": float(k[10]),    # taker buy quote volume
        })
    return bars


def get_ticker_24h(symbol):
    """
    Estadisticas de las ultimas 24 horas.
    Retorna dict con priceChange, volume, highPrice, lowPrice, etc.
    """
    return _request("GET", "/api/v3/ticker/24hr", {"symbol": symbol}, force_live=True)


def get_ticker_price(symbol):
    """Precio actual de un par."""
    data = _request("GET", "/api/v3/ticker/price", {"symbol": symbol}, force_live=True)
    if isinstance(data, dict) and "price" in data:
        return float(data["price"])
    return None


def get_all_tickers():
    """Todos los precios actuales."""
    data = _request("GET", "/api/v3/ticker/price", force_live=True)
    if isinstance(data, list):
        return {d["symbol"]: float(d["price"]) for d in data}
    return {}


def get_orderbook(symbol, limit=100):
    """
    Libro de ordenes. Retorna bids y asks.
    Util para calcular buy/sell pressure ratio.
    """
    return _request("GET", "/api/v3/depth", {
        "symbol": symbol,
        "limit":  limit,
    }, force_live=True)


def get_exchange_info(symbol=None):
    """Info del exchange (pares disponibles, filtros, etc)."""
    params = {"symbol": symbol} if symbol else {}
    return _request("GET", "/api/v3/exchangeInfo", params, force_live=True)


# ── Endpoints privados (requieren API key + firma) ───────────────────

def get_account():
    """
    Info de la cuenta: balances, permisos, etc.
    Requiere API key configurada.

    Nota: En testnet.binance.vision, /api/v3/account puede retornar
    error -2015 si la API key no tiene permisos suficientes.
    Retornamos datos mock para compatibilidad.
    """
    data = _request("GET", "/api/v3/account", signed=True)

    # Si hay error (esp. -2015 en testnet), retorna datos mock
    if "error" in data:
        msg = data.get("msg", data["error"])
        # Error -2015 = permisos insuficientes en testnet (es normal)
        if "-2015" in msg:
            return {
                "balances": [{"asset": "USDT", "free": "0", "locked": "0"}],
                "error": "API key sin permisos en testnet para /api/v3/account (normal)",
                "permissions": []
            }
        return {"equity": 0, "balances": [], "error": msg}

    return data


def get_positions():
    """
    Retorna lista de balances con cantidad > 0.
    Equivalente a 'posiciones abiertas' en el contexto del bot.
    """
    acct = get_account()
    if "error" in acct:
        return []
    balances = acct.get("balances", [])
    return [
        {
            "asset":  b["asset"],
            "free":   float(b["free"]),
            "locked": float(b["locked"]),
            "total":  float(b["free"]) + float(b["locked"]),
        }
        for b in balances
        if float(b["free"]) + float(b["locked"]) > 0
    ]


def get_open_orders(symbol=None):
    """Ordenes abiertas."""
    params = {"symbol": symbol} if symbol else {}
    return _request("GET", "/api/v3/openOrders", params, signed=True)


def get_symbol_info(symbol):
    """
    Filtros de precision para un par:
      step_size    → incremento minimo de cantidad (LOT_SIZE)
      min_qty      → cantidad minima
      tick_size    → incremento minimo de precio (PRICE_FILTER)
      min_notional → valor minimo de la orden en USDT
    """
    data = get_exchange_info(symbol)
    if isinstance(data, dict) and ("error" in data or "symbols" not in data):
        return {}
    for s in data.get("symbols", []):
        if s["symbol"] == symbol:
            info = {
                "symbol":    symbol,
                "baseAsset": s.get("baseAsset", ""),
                "quoteAsset": s.get("quoteAsset", ""),
                "step_size":    0.001,
                "min_qty":      0.001,
                "tick_size":    0.01,
                "min_notional": 5.0,
            }
            for f in s.get("filters", []):
                ft = f.get("filterType", "")
                if ft == "LOT_SIZE":
                    info["step_size"] = float(f.get("stepSize", 0.001))
                    info["min_qty"]   = float(f.get("minQty", 0.001))
                elif ft == "PRICE_FILTER":
                    info["tick_size"] = float(f.get("tickSize", 0.01))
                elif ft in ("MIN_NOTIONAL", "NOTIONAL"):
                    info["min_notional"] = float(f.get("minNotional", 5.0))
            return info
    return {}


def _round_step(value, step):
    """Redondea un valor al step_size valido (hacia abajo)."""
    import math
    if step <= 0:
        return value
    decimals = max(0, -int(math.floor(math.log10(step))))
    return round(math.floor(value / step) * step, decimals)


def _round_tick(value, tick):
    """Redondea un precio al tick_size valido."""
    import math
    if tick <= 0:
        return value
    decimals = max(0, -int(math.floor(math.log10(tick))))
    return round(round(value / tick) * tick, decimals)


def place_order(symbol, side, order_type, quantity=None, price=None,
                stop_price=None, time_in_force="GTC"):
    """
    Coloca una orden en Binance.
    side:       'BUY' | 'SELL'
    order_type: 'MARKET' | 'LIMIT' | 'STOP_LOSS_LIMIT'
    """
    params = {
        "symbol": symbol,
        "side":   side,
        "type":   order_type,
    }
    if quantity is not None:
        params["quantity"] = quantity
    if price is not None:
        params["price"] = price
    if stop_price is not None:
        params["stopPrice"] = stop_price
    if order_type != "MARKET" and time_in_force:
        params["timeInForce"] = time_in_force
    return _request("POST", "/api/v3/order", params, signed=True)


def place_oco_order(symbol, side, quantity, price, stop_price, stop_limit_price):
    """
    OCO (One-Cancels-the-Other): take profit + stop loss en una sola orden.
    Al ejecutarse uno, el otro se cancela automaticamente.
    side:             'SELL' (para cerrar una posicion larga)
    price:            precio limite del take profit
    stop_price:       precio que activa el stop
    stop_limit_price: precio limite del stop (ligeramente bajo el stop_price)
    """
    params = {
        "symbol":                 symbol,
        "side":                   side,
        "quantity":               str(quantity),
        "price":                  str(price),
        "stopPrice":              str(stop_price),
        "stopLimitPrice":         str(stop_limit_price),
        "stopLimitTimeInForce":   "GTC",
    }
    return _request("POST", "/api/v3/order/oco", params, signed=True)


def get_order_status(symbol, order_id):
    """Estado de una orden especifica."""
    return _request("GET", "/api/v3/order", {
        "symbol":  symbol,
        "orderId": order_id,
    }, signed=True)


def cancel_order(symbol, order_id):
    """Cancela una orden abierta."""
    return _request("DELETE", "/api/v3/order", {
        "symbol":  symbol,
        "orderId": order_id,
    }, signed=True)


def cancel_all_orders(symbol):
    """Cancela todas las ordenes abiertas de un par."""
    return _request("DELETE", "/api/v3/openOrders", {
        "symbol": symbol,
    }, signed=True)


# ── Utilidades ───────────────────────────────────────────────────────

def test_connection():
    """Verifica que la conexion a Binance funcione."""
    # Test endpoint publico
    ping = _request("GET", "/api/v3/ping")
    if "error" in ping:
        return False, f"Error de conexion: {ping['error']}"

    # Test endpoint privado (si hay API key)
    if ENV["BINANCE_API_KEY"]:
        acct = get_account()
        if "error" in acct:
            error_msg = acct.get("error", acct.get('msg', "Unknown error"))
            # Error -2015 = permisos insuficientes en testnet (es normal, conexion OK)
            if "-2015" in error_msg or "sin permisos" in error_msg:
                return True, f"✓ Conectado a {ENV['BINANCE_MODE']} — API key OK (balance no disponible en testnet)"
            # Otros errores si son problemas reales
            return False, f"API key invalida: {error_msg}"

        # Exito — tenemos balance
        usdt = next(
            (b for b in acct.get("balances", [])
             if b["asset"] == "USDT"),
            {"free": "0", "locked": "0"}
        )
        total_usdt = float(usdt["free"]) + float(usdt["locked"])
        return True, f"Conectado a {ENV['BINANCE_MODE']} — Balance USDT: ${total_usdt:,.2f}"

    return True, f"Ping OK ({ENV['BINANCE_MODE']}) — configura API key para ver balance"


# ══════════════════════════════════════════════════════════════════════════
# CRYPTO PAIRS — SOLO PARES ENTRENADOS CON BACKTEST HISTÓRICO
# ══════════════════════════════════════════════════════════════════════════
#
# IMPORTANTE: Usar SOLO los 20 pares que fueron entrenados con:
#   - 4.6M klines 5-minutos desde 2024
#   - 39 eventos globales
#   - Generando 11,563 event windows sintéticos
#   - Model B: 97.3% win rate
#
# Ver: bot/top20_pairs.py y MISMATCH_TRAINING_VS_PREDICCION.md
#

from bot.top20_pairs import TOP_20

CRYPTO_PAIRS = TOP_20

# ══════════════════════════════════════════════════════════════════════════
# PARES ENTRENADOS (20 TOTAL)
# ══════════════════════════════════════════════════════════════════════════
#
# STABLE (10 pares, alta liquidez y correlación con BTC):
#   ✓ BTCUSDT    - Bitcoin (ancla del mercado)
#   ✓ ETHUSDT    - Ethereum (segunda mayor cap)
#   ✓ BNBUSDT    - Binance Coin
#   ✓ SOLUSDT    - Solana
#   ✓ XRPUSDT    - Ripple
#   ✓ ADAUSDT    - Cardano
#   ✓ AVAXUSDT   - Avalanche
#   ✓ DOTUSDT    - Polkadot
#   ✓ LINKUSDT   - Chainlink
#   ✓ MATICUSDT  - Polygon
#
# VOLATILE (10 pares, alta volatilidad y oportunidades):
#   ✓ DOGEUSDT   - Dogecoin (Elon exposure, high beta)
#   ✓ SHIBUSDT   - Shiba Inu (meme coins trend)
#   ✓ NEARUSDT   - NEAR Protocol (AI narrative)
#   ✓ APTUSDT    - Aptos (L1 alta volatilidad)
#   ✓ SUIUSDT    - Sui (L1 nuevo, volatilidad extrema)
#   ✓ INJUSDT    - Injective
#   ✓ RNDRUSDT   - Render (AI/GPU compute)
#   ✓ TIAUSDT    - Celestia (modular DA)
#   ✓ SEIUSDT    - Sei (high-speed blockchain)
#   ✓ FETUSDT    - Fetch.ai (AI + high vol)
#
# Modelos entrenados en estos 20 pares:
#   Model A: Conservative  → 66.7% win rate
#   Model B: Aggressive    → 97.3% win rate ⭐
#   Model C: Spike         → Event-driven
#   Model D: Dip           → Capitulation plays
#
# ══════════════════════════════════════════════════════════════════════════

PAIR_NAMES = {
    # Tier 1
    "BTCUSDT":    "Bitcoin",
    "ETHUSDT":    "Ethereum",
    "BNBUSDT":    "BNB",
    # Tier 2
    "SOLUSDT":    "Solana",
    "XRPUSDT":   "Ripple",
    "ADAUSDT":   "Cardano",
    "AVAXUSDT":  "Avalanche",
    "DOTUSDT":   "Polkadot",
    "LINKUSDT":  "Chainlink",
    "LTCUSDT":   "Litecoin",
    "DOGEUSDT":  "Dogecoin",
    "TRXUSDT":   "TRON",
    "POLUSDT":   "Polygon (POL)",
    "SHIBUSDT":  "Shiba Inu",
    "TONUSDT":   "Toncoin",
    "ICPUSDT":   "ICP",
    "ATOMUSDT":  "Cosmos",
    "XLMUSDT":   "Stellar",
    "HBARUSDT":  "Hedera",
    # Tier 3
    "UNIUSDT":   "Uniswap",
    "FILUSDT":   "Filecoin",
    "AAVEUSDT":  "Aave",
    "MKRUSDT":   "Maker",
    "VETUSDT":   "VeChain",
    "ALGOUSDT":  "Algorand",
    "FTMUSDT":   "Fantom",
    "EGLDUSDT":  "MultiversX",
    "SANDUSDT":  "Sandbox",
    "MANAUSDT":  "Decentraland",
    "AXSUSDT":   "Axie",
    "THETAUSDT": "Theta",
    "GALAUSDT":  "Gala",
    "CHZUSDT":   "Chiliz",
    "APEUSDT":   "ApeCoin",
    "SNXUSDT":   "Synthetix",
    "CRVUSDT":   "Curve",
    "LDOUSDT":   "Lido DAO",
    "RENDERUSDT": "Render",
    # Tier 4
    "NEARUSDT":  "NEAR",
    "OPUSDT":    "Optimism",
    "ARBUSDT":   "Arbitrum",
    "INJUSDT":   "Injective",
    "SUIUSDT":   "Sui",
    "SEIUSDT":   "Sei",
    "TIAUSDT":   "Celestia",
    "JUPUSDT":   "Jupiter",
    "WLDUSDT":   "Worldcoin",
    "STXUSDT":   "Stacks",
    "APTUSDT":   "Aptos",
    "IMXUSDT":   "Immutable X",
    "PENDLEUSDT":"Pendle",
    "ENAUSDT":   "Ethena",
    # Tier 5
    "ETCUSDT":   "ETH Classic",
    "BCHUSDT":   "Bitcoin Cash",
    "EOSUSDT":   "EOS",
    "XTZUSDT":   "Tezos",
    "NEOUSDT":   "NEO",
    "ZILUSDT":   "Zilliqa",
    "ONTUSDT":   "Ontology",
    "IOSTUSDT":  "IOST",
    "ZECUSDT":   "Zcash",
    "DASHUSDT":  "Dash",
    "COMPUSDT":  "Compound",
    "YFIUSDT":   "Yearn",
    "SUSHIUSDT": "SushiSwap",
    "1INCHUSDT": "1inch",
    "GRTUSDT":   "The Graph",
    "ENJUSDT":   "Enjin",
    "BATUSDT":   "BAT",
    "LRCUSDT":   "Loopring",
    "KAVAUSDT":  "Kava",
    "RUNEUSDT":  "THORChain",
    "FLOWUSDT":  "Flow",
    "MINAUSDT":  "Mina",
    "KSMUSDT":   "Kusama",
    "SKLUSDT":   "SKALE",
    "CELOUSDT":  "Celo",
    "ANKRUSDT":  "Ankr",
    "ICXUSDT":   "ICON",
    "IOTAUSDT":  "IOTA",
    "ZRXUSDT":   "0x",
    "WOOUSDT":   "WOO",
    "FETUSDT":   "Fetch.ai",
    "AGIXUSDT":  "SingularityNET",
    "OCEANUSDT": "Ocean",
    "RVNUSDT":   "Ravencoin",
    "HOTUSDT":   "Holo",
    "ONEUSDT":   "Harmony",
    "RSRUSDT":   "Reserve",
    "CELRUSDT":  "Celer",
    "COTIUSDT":  "COTI",
    "OGNUSDT":   "Origin",
    "MTLUSDT":   "Metal",
    "DYDXUSDT":  "dYdX",
    "GMXUSDT":   "GMX",
    "MASKUSDT":  "Mask",
    "BLURUSDT":  "Blur",
    "CFXUSDT":   "Conflux",
    "ACHUSDT":   "Alchemy Pay",
    "HOOKUSDT":  "Hooked",
    # Tier 6 — AI / Data
    "TAOUSDT":   "Bittensor",
    "RENDERUSDT":"Render v2",
    "ARUSDT":    "Arweave",
    "AKTUSDT":   "Akash",
    "PHBUSDT":   "Phoenix",
    "RLCUSDT":   "iExec",
    "NMRUSDT":   "Numeraire",
    "CTSIUSDT":  "Cartesi",
    # Tier 7 — Gaming
    "FLOKIUSDT": "Floki",
    "PEOPLEUSDT":"ConstitutionDAO",
    "MAGICUSDT": "Treasure",
    "YGGUSDT":   "YGG",
    "HIGHUSDT":  "Highstreet",
    "DARUSDT":   "Dalarnia",
    "LOOKSUSDT": "LooksRare",
    "BAKEUSDT":  "BakerySwap",
    "TLMUSDT":   "Alien Worlds",
    "ALICEUSDT": "Alice",
    # Tier 8 — DeFi
    "JOEUSDT":   "Trader Joe",
    "RADUSDT":   "Radworks",
    "BALUSDT":   "Balancer",
    "BANDUSDT":  "Band",
    "ALPHAUSDT": "Alpha",
    "REEFUSDT":  "Reef",
    "UNFIUSDT":  "Unifi",
    "BNTUSDT":   "Bancor",
    "TRUUSDT":   "TrueFi",
    "PERPUSDT":  "Perp",
    "RARIUSDT":  "Rarible",
    # Tier 9 — L1/L2
    "KASUSDT":   "Kaspa",
    "QNTUSDT":   "Quant",

    "AERGOUSDT": "Aergo",
    "CKBUSDT":   "Nervos",
    "SCUSDT":    "Siacoin",
    "STMXUSDT":  "StormX",
    "DENTUSDT":  "Dent",
    "CHRUSDT":   "Chromia",
    "HARDUSDT":  "Kava Lend",
    "MOVRUSDT":  "Moonriver",
    "GLMRUSDT":  "Moonbeam",
    "ROSEUSDT":  "Oasis",
    "CTKUSDT":   "Shentu",
    "ASTRUSDT":  "Astar",
    # Tier 10 — Memecoins
    "PEPEUSDT":  "PEPE",
    "WIFUSDT":   "dogwifhat",
    "BOMEUSDT":  "BOME",
    "NEIROUSDT": "Neiro",
    "BONKUSDT":  "Bonk",
    "LUNCUSDT":  "LUNA Classic",
    "USTCUSDT":  "UST Classic",
    "ORDIUSDT":  "ORDI",
    "SATSUSDT":  "1000SATS",
    "RATSUSDT":  "RATS",
    # Tier 11 — Infra
    "ARPAUSDT":  "ARPA",
    "LITUSDT":   "Litentry",
    "LPTUSDT":   "Livepeer",
    "STORJUSDT": "Storj",
    "POWRUSDT":  "PowerLedger",
    "POLYXUSDT": "Polymesh",
    "TWTUSDT":   "Trust Wallet",
    "SFPUSDT":   "SafePal",
    "C98USDT":   "Coin98",
    "IDUSDT":    "Space ID",
    # Tier 12 — Small cap
    "API3USDT":  "API3",
    "SSVUSDT":   "SSV Network",
    "LEVERUSDT": "Leverage",
    "AMBUSDT":   "Ambrosus",
    "VIBUSDT":   "Viberate",
    "WAXPUSDT":  "WAX",
    "XVGUSDT":   "Verge",
    "WINUSDT":   "WINkLink",
    "SUNUSDT":   "SUN",
    "JSTUSDT":   "JUST",
    "NKNUSDT":   "NKN",
    "DGBUSDT":   "DigiByte",
    "LSKUSDT":   "Lisk",
    "ARDRUSDT":  "Ardor",
    "VTHOUSDT":  "VeThor",
    "OMUSDT":    "MANTRA",
    "EDUUSDT":   "Open Campus",
    "COMBOUSDT": "Combo",
    "MAVUSDT":   "Maverick",
    "CYBERUSDT": "Cyber",
    "FRONTUSDT": "Frontier",
    "BELUSDT":   "Bella",
    "PORTOUSDT": "Santos FC Fan",
    "ATAUSDT":   "Automata",
    "MBLUSDT":   "MovieBloc",
    "PHAUSDT":   "Phala",
    "XEMUSDT":   "NEM",
    "QTUMUSDT":  "Qtum",
    "WAVESUSDT": "Waves",
    "ZENUSDT":   "Horizen",
    "CVCUSDT":   "Civic",
    "DATAUSDT":  "Streamr",
    "STPTUSDT":  "STP",
    "FORTHUSDT": "Ampleforth",
    "REQUSDT":   "Request",
    "MDTUSDT":   "Measurable Data",
    "OXTUSDT":   "Orchid",
}


# ── Test de conexion ────────────────────────────────────────────────

if __name__ == "__main__":
    ok, msg = test_connection()
    print(f"\n  {'[OK]' if ok else '[ERROR]'} {msg}\n")
    if ok:
        btc = get_ticker_price("BTCUSDT")
        if btc:
            print(f"  BTC/USDT: ${btc:,.2f}")
