"""
Monitor de noticias CRYPTO en tiempo real - Google News RSS.

MEJORAS v2:
  - Diccionario expandido (250+ palabras + bigramas)
  - Analisis especifico por par (queries personalizadas por coin)
  - Deteccion de eventos criticos (ETF, hack, halving, SEC) -> boost 2x extra
  - Peso 3x para figuras de alto poder (Trump, politicos clave)
  - Peso 2x base para todas las noticias crypto (vs acciones)

Figuras monitoreadas:
  - Trump          (peso 3.0)  -> politico de mayor impacto crypto
  - Politicos US   (peso 2.5)  -> Powell, Yellen, Warren, Gensler
  - Elon Musk      (peso 2.5)  -> meme coins (DOGE, SHIB)
  - SEC            (peso 2.0)
  - ETF/BlackRock  (peso 1.8)
  - Fed/Macro      (peso 1.5)
  - China          (peso 1.3)
  - Hacks          (peso 2.0)  -> impacto inmediato
"""
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import json, os, sys, re
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from bot.crypto_data import _cache

# -- Diccionario expandido bullish/bearish --------------------------------

BULLISH_WORDS = [
    # Movimientos de precio
    "rally", "surge", "soar", "soaring", "skyrocket", "moon", "mooning",
    "pump", "pumping", "breakout", "break out", "all-time high", "ath",
    "record high", "new high", "highs", "rally", "spike",
    # Adopcion / institucional
    "adoption", "mass adoption", "mainstream", "accumulate", "accumulating",
    "institutional", "institutions buying", "whale buying", "whales accumulating",
    "etf approved", "etf approval", "etf launch", "etf inflow", "etf inflows",
    "spot etf", "blackrock", "fidelity", "vanguard", "grayscale",
    "treasury reserve", "balance sheet", "corporate adoption",
    "partnership", "integration", "tier-1 listing", "binance listing",
    # Sentimiento positivo
    "bullish", "bull run", "bull market", "bull case", "uptrend", "upward",
    "gains", "winners", "outperform", "rally", "surge", "boom",
    "positive", "optimistic", "confident", "strong",
    # Macro favorable
    "rate cut", "rate cuts", "easing", "stimulus", "qe", "quantitative easing",
    "dovish", "soft landing", "lower rates", "fed pivot",
    # Crypto-especifico
    "halving", "hard cap", "supply shock", "scarcity", "deflationary",
    "burn", "burned", "buyback", "staking yield", "tvl growth",
    "defi growth", "web3", "blockchain adoption",
    # Compradores grandes
    "buy the dip", "btd", "smart money", "long position",
    "saylor", "microstrategy buying", "el salvador", "country adopts",
]

BEARISH_WORDS = [
    # Movimientos negativos
    "crash", "crashing", "plunge", "plunging", "tumble", "tumbling",
    "dump", "dumping", "collapse", "collapsing", "freefall", "nosedive",
    "selloff", "sell-off", "rout", "bloodbath", "carnage",
    # Liquidaciones / panico
    "liquidation", "liquidations", "liquidated", "cascading liquidations",
    "panic", "panic selling", "capitulation", "fear", "extreme fear",
    "uncertainty", "volatility spike", "flash crash",
    # Regulacion / legal
    "ban", "banned", "banning", "crackdown", "crackdowns",
    "regulation", "regulatory", "regulator", "lawsuit", "lawsuits",
    "sec sues", "sec charges", "sec investigation", "sec enforcement",
    "doj", "fbi investigation", "investigation", "subpoena",
    "fine", "penalty", "settlement", "guilty", "charges",
    "delisted", "delisting", "trading halt",
    # Hacks / seguridad
    "hack", "hacked", "hacker", "exploit", "exploited", "drained", "stolen",
    "rug pull", "rugpull", "scam", "fraud", "ponzi", "fake",
    "vulnerability", "breach", "compromised", "phishing",
    # Macro adverso
    "rate hike", "rate hikes", "hawkish", "tightening", "qt",
    "inflation", "stagflation", "recession", "depression",
    "recession fears", "credit crunch", "banking crisis",
    # Empresas en problemas
    "bankrupt", "bankruptcy", "insolvency", "insolvent", "default",
    "ftx", "ftx collapse", "celsius", "voyager", "blockfi",
    "terra luna", "ust depeg", "depeg", "stablecoin risk",
    "outflow", "outflows", "exchange outflow", "exchange inflow",
    "whale selling", "whales dumping", "selling pressure",
    # Sentimiento negativo
    "bearish", "bear market", "bear case", "downtrend", "downward",
    "losses", "losers", "underperform", "weak", "weakness",
    "negative", "pessimistic", "warning", "threat", "risk", "concern",
    # Specific FUD
    "china ban", "mining ban", "energy concern", "esg concern",
    "tether risk", "usdt risk", "fud",
]

# Bigramas / frases compuestas (peso reforzado)
BULLISH_PHRASES = [
    "etf approved", "etf approval", "all-time high", "all time high",
    "rate cut", "fed pivot", "spot etf", "supply shock",
    "country adopts", "treasury reserve", "buy the dip",
    "institutional adoption", "mass adoption",
]
BEARISH_PHRASES = [
    "sec sues", "sec charges", "rug pull", "rate hike",
    "ftx collapse", "stablecoin depeg", "exchange hack",
    "mining ban", "trading halt", "flash crash",
    "regulatory crackdown", "ponzi scheme",
]

# Eventos criticos -> boost adicional de peso
CRITICAL_EVENTS = {
    "ETF_APPROVAL":    {"keywords": ["etf approved", "etf approval", "spot etf launches", "etf goes live"], "weight_boost": 2.0, "direction": "bullish"},
    "SEC_LAWSUIT":     {"keywords": ["sec sues", "sec charges", "sec lawsuit", "sec enforcement"], "weight_boost": 2.0, "direction": "bearish"},
    "MAJOR_HACK":      {"keywords": ["billion stolen", "exchange hack", "exploit drained", "millions hacked"], "weight_boost": 2.5, "direction": "bearish"},
    "HALVING":         {"keywords": ["halving", "halved", "supply cut"], "weight_boost": 1.5, "direction": "bullish"},
    "REGULATORY_BAN":  {"keywords": ["country bans", "outlaws crypto", "crypto banned"], "weight_boost": 2.0, "direction": "bearish"},
    "INSTITUTIONAL":   {"keywords": ["blackrock files", "blackrock buys", "fidelity launches"], "weight_boost": 1.8, "direction": "bullish"},
    "FED_PIVOT":       {"keywords": ["fed pivot", "rate cut", "fed cuts rates"], "weight_boost": 1.5, "direction": "bullish"},
    "EXCHANGE_FAIL":   {"keywords": ["exchange bankruptcy", "exchange insolvent", "exchange halts"], "weight_boost": 2.5, "direction": "bearish"},
}

# -- Figuras y queries (con pesos elevados) -------------------------------

FIGURES = [
    {
        "id":     "trump_crypto",
        "name":   "Trump + Crypto",
        "query":  "Trump cryptocurrency bitcoin executive order strategic reserve",
        "weight": 3.0,    # MAS PESO - politico de mayor impacto
        "assets": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "XRPUSDT"],
    },
    {
        "id":     "us_politicians",
        "name":   "Politicos US (Powell/Yellen/Warren)",
        "query":  "Powell Yellen Warren Gensler crypto bitcoin policy",
        "weight": 2.5,
        "assets": ["BTCUSDT", "ETHUSDT"],
    },
    {
        "id":     "elon_crypto",
        "name":   "Elon Musk + Crypto",
        "query":  "Elon Musk bitcoin dogecoin Tesla X payments",
        "weight": 2.5,
        "assets": ["DOGEUSDT", "BTCUSDT", "SHIBUSDT"],
    },
    {
        "id":     "sec_regulation",
        "name":   "SEC / Regulacion",
        "query":  "SEC cryptocurrency lawsuit enforcement Binance Coinbase",
        "weight": 2.0,
        "assets": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "BNBUSDT"],
    },
    {
        "id":     "etf_institutional",
        "name":   "ETF / Institucional",
        "query":  "bitcoin ETF spot ETF BlackRock Fidelity Grayscale flows",
        "weight": 1.8,
        "assets": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    },
    {
        "id":     "fed_macro",
        "name":   "Fed / Macro",
        "query":  "Federal Reserve interest rate inflation FOMC crypto impact",
        "weight": 1.5,
        "assets": ["BTCUSDT", "ETHUSDT"],
    },
    {
        "id":     "china_crypto",
        "name":   "China / Mining",
        "query":  "China cryptocurrency ban mining regulation Hong Kong",
        "weight": 1.3,
        "assets": ["BTCUSDT", "BNBUSDT"],
    },
    {
        "id":     "hack_security",
        "name":   "Hacks / Seguridad",
        "query":  "cryptocurrency hack exploit drain stolen exchange security",
        "weight": 2.0,
        "assets": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"],
    },
    {
        "id":     "saylor_treasury",
        "name":   "Saylor / Treasury reserves",
        "query":  "Michael Saylor MicroStrategy treasury reserve corporate bitcoin",
        "weight": 1.8,
        "assets": ["BTCUSDT"],
    },
]

# -- Queries especificas por par ------------------------------------------

PAIR_QUERIES = {
    "BTCUSDT":   "Bitcoin BTC price news ETF whale halving",
    "ETHUSDT":   "Ethereum ETH price upgrade staking ETF",
    "SOLUSDT":   "Solana SOL price news ETF Jupiter Jito",
    "BNBUSDT":   "Binance BNB price CZ regulatory",
    "XRPUSDT":   "Ripple XRP SEC lawsuit settlement",
    "DOGEUSDT":  "Dogecoin DOGE Elon Musk meme",
    "ADAUSDT":   "Cardano ADA Hoskinson upgrade",
    "AVAXUSDT":  "Avalanche AVAX subnet partnership",
    "DOTUSDT":   "Polkadot DOT parachain news",
    "LINKUSDT":  "Chainlink LINK CCIP partnership",
    "SHIBUSDT":  "Shiba Inu SHIB Shibarium burn",
    "MATICUSDT": "Polygon MATIC zkEVM partnership",
    "TONUSDT":   "Toncoin TON Telegram integration",
}


# -- Fetch RSS de Google News ---------------------------------------------

def _fetch_google_news(query, max_hours=24, max_items=30):
    cache_key = f"cnews_{query[:40]}_{max_hours}"
    if cache_key in _cache:
        return _cache[cache_key]
    try:
        url = ("https://news.google.com/rss/search?"
               f"q={urllib.parse.quote(query)}&hl=en-US&gl=US&ceid=US:en")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            xml_data = resp.read()
        root = ET.fromstring(xml_data)
        items = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_hours)
        for item in root.findall(".//item"):
            title   = item.findtext("title", "")
            pub_str = item.findtext("pubDate", "")
            desc    = item.findtext("description", "")
            try:
                from email.utils import parsedate_to_datetime
                pub_dt = parsedate_to_datetime(pub_str)
                if pub_dt < cutoff:
                    continue
            except Exception:
                pass
            items.append(f"{title} {desc}".lower())
            if len(items) >= max_items:
                break
        _cache[cache_key] = items
        return items
    except Exception:
        return []


def _detect_critical_events(headlines):
    """Detecta eventos criticos en titulares. Retorna lista de eventos."""
    events_found = []
    for ev_name, ev_def in CRITICAL_EVENTS.items():
        for h in headlines:
            for kw in ev_def["keywords"]:
                if kw in h:
                    events_found.append({
                        "event": ev_name,
                        "direction": ev_def["direction"],
                        "boost": ev_def["weight_boost"],
                        "headline": h[:120],
                        "keyword": kw,
                    })
                    break
    return events_found


def _score_headlines(headlines):
    """Score con palabras + bigramas. -1.0 a +1.0."""
    if not headlines:
        return 0.0
    total = 0.0
    for h in headlines:
        score = 0
        # palabras simples
        for w in BULLISH_WORDS:
            if w in h: score += 1
        for w in BEARISH_WORDS:
            if w in h: score -= 1
        # bigramas (peso doble)
        for w in BULLISH_PHRASES:
            if w in h: score += 2
        for w in BEARISH_PHRASES:
            if w in h: score -= 2
        total += max(-5, min(5, score))
    return round(total / len(headlines), 3)


# -- Senal consolidada de noticias ----------------------------------------

def get_news_signal(symbol=None):
    cache_key = f"cnews_signal_{symbol or 'market'}"
    if cache_key in _cache:
        return _cache[cache_key]

    results = {}
    alerts = []
    critical_events = []
    total_score = 0.0
    total_weight = 0.0

    # 1) Scan global por figura
    for fig in FIGURES:
        weight = fig["weight"]
        if symbol and symbol in fig.get("assets", []):
            weight *= 1.5  # boost si la figura afecta directamente al par

        query = fig["query"]
        if symbol:
            pair_name = symbol.replace("USDT", "")
            query += f" {pair_name}"

        headlines = _fetch_google_news(query, max_hours=24)
        score = _score_headlines(headlines)
        events = _detect_critical_events(headlines)

        # Boost por eventos criticos
        for ev in events:
            score += ev["boost"] * (1 if ev["direction"] == "bullish" else -1) * 0.3
            critical_events.append({**ev, "figure": fig["name"]})

        score = max(-1.0, min(1.0, score))

        results[fig["id"]] = {
            "name": fig["name"],
            "score": round(score, 3),
            "headlines": headlines[:3],
            "count": len(headlines),
            "weight": weight,
        }
        total_score += score * weight
        total_weight += weight

        if score >= 0.5:
            alerts.append(f"[BULL] {fig['name']}: muy positivo ({len(headlines)} noticias)")
        elif score <= -0.5:
            alerts.append(f"[BEAR] {fig['name']}: muy negativo ({len(headlines)} noticias)")

    # 2) Scan especifico del par
    pair_specific_score = 0.0
    if symbol and symbol in PAIR_QUERIES:
        pair_query = PAIR_QUERIES[symbol]
        pair_headlines = _fetch_google_news(pair_query, max_hours=12, max_items=20)
        pair_specific_score = _score_headlines(pair_headlines)
        pair_events = _detect_critical_events(pair_headlines)
        critical_events.extend([{**e, "figure": f"PAIR_{symbol}"} for e in pair_events])
        # peso 2.0 para noticias especificas del par
        total_score += pair_specific_score * 2.0
        total_weight += 2.0
        results["pair_specific"] = {
            "name": f"Par especifico {symbol}",
            "score": round(pair_specific_score, 3),
            "headlines": pair_headlines[:3],
            "count": len(pair_headlines),
            "weight": 2.0,
        }

    weighted_score = round(total_score / total_weight, 3) if total_weight else 0.0

    # 3) Eventos criticos como alertas separadas
    for ev in critical_events:
        emoji = "[BULL]" if ev["direction"] == "bullish" else "[BEAR]"
        alerts.append(f"{emoji} EVENTO CRITICO: {ev['event']} ({ev['figure']}) -> {ev['headline'][:80]}")

    if weighted_score >= 0.2:
        overall = "BULLISH"
    elif weighted_score <= -0.2:
        overall = "BEARISH"
    else:
        overall = "NEUTRAL"

    signal = {
        "overall":         overall,
        "score":           weighted_score,
        "alerts":          alerts,
        "details":         results,
        "weight":          2.0,
        "critical_events": critical_events,
        "pair_score":      round(pair_specific_score, 3) if symbol else None,
    }
    _cache[cache_key] = signal
    return signal


def print_news_report(symbol=None):
    signal = get_news_signal(symbol)
    icon = {"BULLISH": "[BULL]", "BEARISH": "[BEAR]", "NEUTRAL": "[NEUT]"}[signal["overall"]]
    sep = "=" * 60
    pair_label = f" - {symbol}" if symbol else ""
    print(f"\n  {sep}")
    print(f"  SENTIMIENTO CRYPTO{pair_label}")
    print(f"  (Peso 2x base + eventos criticos boost)")
    print(f"  {sep}")
    print(f"  Senal global: {icon} {signal['overall']}  (score: {signal['score']:+.2f})")
    if signal.get("pair_score") is not None:
        print(f"  Par especifico:               score {signal['pair_score']:+.2f}")
    print()

    for fid, fdata in signal["details"].items():
        s = fdata["score"]
        n = fdata["count"]
        w = fdata.get("weight", 1.0)
        bar = "[BULL]" if s >= 0.2 else "[BEAR]" if s <= -0.2 else "[NEUT]"
        print(f"  {bar} {fdata['name']:<32} score {s:+.2f}  w={w:.1f}  ({n})")
        for h in fdata["headlines"][:2]:
            short = h[:80].strip()
            if short:
                print(f"       > {short}...")

    if signal["critical_events"]:
        print(f"\n  EVENTOS CRITICOS detectados:")
        for ev in signal["critical_events"][:5]:
            print(f"    [{ev['direction'].upper()}] {ev['event']} ({ev['figure']}): {ev['keyword']}")

    if signal["alerts"]:
        print(f"\n  ALERTAS:")
        for a in signal["alerts"][:6]:
            print(f"    {a}")
    print(f"  {sep}\n")
