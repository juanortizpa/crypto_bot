"""
Análisis de sentimiento avanzado para crypto.

MEJORAS vs crypto_news.py básico:
  1. Más figuras influyentes (CZ, Vitalik, Saylor, Gensler, etc.)
  2. Keywords contextuales por figura (no genéricos)
  3. Scoring por relevancia temporal (noticias recientes pesan más)
  4. Historial de sentimiento en SQLite (detecta CAMBIOS de sentimiento)
  5. Score numérico continuo que alimenta al meta-modelo
  6. Detección de eventos "spike" (noticia de alto impacto)

El score de sentimiento se usa en:
  - Gate factor N1 (GREEN/YELLOW/RED, peso doble)
  - Meta-modelo como feature numérica continua (-1.0 a +1.0)
  - Modelo C (News Spike) como trigger de entrada
"""
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import sqlite3
import os, sys, json, re
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from bot.logger import log

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                       "state", "sentiment.db")

# Cache propio con TTL. Antes se usaba crypto_data._cache, que el monitor
# limpia CADA ciclo (60s): eso relanzaba ~14 requests RSS a Google News por
# posicion por minuto — lento (timeouts de 8s en serie) y suficiente para
# que Google throttlee la IP en una corrida 24/7. Las noticias no cambian
# minuto a minuto: 15 min de TTL mantiene N1/R6 frescos sin martillar la red.
_sent_cache = {}   # key -> (timestamp, value)
SENT_TTL_SEC = float(os.environ.get("CRYPTO_SENTIMENT_TTL_SEC", "900"))

import time as _time


def _cache_get(key):
    hit = _sent_cache.get(key)
    if hit and (_time.time() - hit[0]) < SENT_TTL_SEC:
        return hit[1]
    return None


def _cache_put(key, value):
    _sent_cache[key] = (_time.time(), value)

# ════════════════════════════════════════════════════════════════════════
# FIGURAS INFLUYENTES + sus queries y assets afectados
# ════════════════════════════════════════════════════════════════════════

FIGURES = [
    # ── Políticos / Reguladores ──────────────────────────────────────
    {
        "id": "trump",
        "name": "Donald Trump",
        "query": "Trump cryptocurrency bitcoin digital asset executive order",
        "weight": 2.5,
        "assets": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"],
        "bullish": [
            "pro crypto", "bitcoin reserve", "strategic reserve",
            "crypto friendly", "digital asset", "executive order crypto",
            "deregulation", "embrace crypto", "bitcoin president",
            "pardons", "supports crypto", "crypto capital",
        ],
        "bearish": [
            "ban crypto", "regulate crypto", "crackdown",
            "crypto fraud", "against bitcoin",
        ],
    },
    {
        "id": "gensler",
        "name": "Gary Gensler / SEC",
        "query": "SEC cryptocurrency regulation enforcement lawsuit crypto",
        "weight": 2.0,
        "assets": ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "ADAUSDT", "BNBUSDT"],
        "bullish": [
            "etf approved", "etf approval", "cleared", "settlement",
            "drops case", "no enforcement", "clarity", "framework",
            "not a security", "commodity",
        ],
        "bearish": [
            "lawsuit", "sues", "enforcement", "security", "violation",
            "wells notice", "investigation", "penalty", "fine",
            "unregistered", "fraud charges",
        ],
    },
    # ── Líderes Crypto ───────────────────────────────────────────────
    {
        "id": "elon",
        "name": "Elon Musk",
        "query": "Elon Musk bitcoin dogecoin cryptocurrency Tesla",
        "weight": 2.0,
        "assets": ["DOGEUSDT", "BTCUSDT", "SHIBUSDT", "FLOKIUSDT", "PEPEUSDT"],
        "bullish": [
            "accepts bitcoin", "accepts dogecoin", "buy", "to the moon",
            "diamond hands", "hodl", "bullish", "love", "great",
            "tesla bitcoin", "spacex crypto", "doge",
        ],
        "bearish": [
            "sell", "dump", "scam", "fraud", "suspended",
            "not accepting", "energy concerns",
        ],
    },
    {
        "id": "cz",
        "name": "CZ / Binance",
        "query": "CZ Binance Changpeng Zhao cryptocurrency exchange",
        "weight": 1.8,
        "assets": ["BNBUSDT", "BTCUSDT", "ETHUSDT"],
        "bullish": [
            "expansion", "new listing", "partnership", "fund",
            "billion", "invest", "bullish", "growth", "adoption",
            "binance pay", "launchpad",
        ],
        "bearish": [
            "lawsuit", "ban", "fine", "penalty", "investigation",
            "delist", "hack", "frozen", "exit", "withdrawal halt",
            "arrested", "guilty", "settlement",
        ],
    },
    {
        "id": "vitalik",
        "name": "Vitalik Buterin",
        "query": "Vitalik Buterin Ethereum upgrade roadmap",
        "weight": 1.5,
        "assets": ["ETHUSDT", "OPUSDT", "ARBUSDT", "MATICUSDT"],
        "bullish": [
            "upgrade", "improvement", "scaling", "merge", "danksharding",
            "proto", "lower fees", "faster", "adoption", "bullish",
            "mass adoption", "roadmap",
        ],
        "bearish": [
            "sell", "dump", "concern", "delay", "bug", "vulnerability",
            "centralization", "problem",
        ],
    },
    {
        "id": "saylor",
        "name": "Michael Saylor / MicroStrategy",
        "query": "Michael Saylor MicroStrategy bitcoin purchase",
        "weight": 1.8,
        "assets": ["BTCUSDT"],
        "bullish": [
            "buy", "purchase", "acquire", "billion", "more bitcoin",
            "hodl", "never sell", "accumulate", "strategy",
            "treasury", "additional",
        ],
        "bearish": [
            "sell", "liquidate", "margin call", "loss", "debt",
        ],
    },
    # ── Institucional ────────────────────────────────────────────────
    {
        "id": "blackrock",
        "name": "BlackRock / ETF",
        "query": "BlackRock bitcoin ETF ethereum ETF crypto institutional",
        "weight": 2.0,
        "assets": ["BTCUSDT", "ETHUSDT"],
        "bullish": [
            "etf approved", "etf approval", "inflow", "inflows",
            "record", "billion", "buy", "accumulate", "filing",
            "institutional", "fidelity", "grayscale",
        ],
        "bearish": [
            "outflow", "outflows", "redemption", "sell", "reject",
            "denied", "postpone", "delay",
        ],
    },
    # ── Macro / Central Banks ────────────────────────────────────────
    {
        "id": "fed",
        "name": "Federal Reserve / Powell",
        "query": "Federal Reserve interest rate inflation crypto market",
        "weight": 1.5,
        "assets": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "bullish": [
            "rate cut", "lower rates", "dovish", "pause", "pivot",
            "easing", "stimulus", "quantitative easing", "soft landing",
            "disinflation",
        ],
        "bearish": [
            "rate hike", "higher rates", "hawkish", "tightening",
            "inflation", "restrictive", "recession", "hard landing",
        ],
    },
    {
        "id": "china",
        "name": "China / PBOC",
        "query": "China cryptocurrency ban mining regulation CBDC Hong Kong",
        "weight": 1.3,
        "assets": ["BTCUSDT", "BNBUSDT"],
        "bullish": [
            "unban", "allow", "hong kong", "legalize", "adopt",
            "mining allowed", "open",
        ],
        "bearish": [
            "ban", "crackdown", "illegal", "shutdown", "arrest",
            "mining ban", "restrict",
        ],
    },
    # ── Seguridad / Hacks ────────────────────────────────────────────
    {
        "id": "security",
        "name": "Hacks / Exploits",
        "query": "cryptocurrency hack exploit rug pull bridge hack DeFi",
        "weight": 1.8,
        "assets": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"],
        "bullish": [
            "recovered", "funds returned", "white hat", "patched",
            "security upgrade",
        ],
        "bearish": [
            "hack", "exploit", "rug pull", "drain", "stolen",
            "bridge hack", "vulnerability", "million stolen",
            "billion stolen", "scam", "fraud", "ponzi",
        ],
    },
    # ── Crypto Twitter / Comunidad ───────────────────────────────────
    {
        "id": "community",
        "name": "Crypto Market Sentiment",
        "query": "crypto market sentiment rally crash bitcoin price prediction",
        "weight": 1.0,
        "assets": ["BTCUSDT", "ETHUSDT"],
        "bullish": [
            "bull run", "bull market", "rally", "surge", "breakout",
            "all time high", "ath", "moon", "pump", "adoption",
            "mainstream", "halving", "accumulation",
        ],
        "bearish": [
            "bear market", "crash", "dump", "capitulation",
            "liquidation", "cascade", "panic", "sell-off",
            "fear", "blood", "collapse",
        ],
    },
]

# ── Keywords genéricos (fallback si figura no tiene propios) ─────────

GENERIC_BULLISH = [
    "rally", "surge", "boom", "record high", "all time high", "ath",
    "bullish", "gains", "pump", "moon", "breakout", "adoption",
    "buy", "invest", "partnership", "integration", "inflow",
]

GENERIC_BEARISH = [
    "crash", "plunge", "dump", "bear", "collapse", "panic",
    "ban", "regulation", "crackdown", "lawsuit", "hack", "exploit",
    "rug pull", "scam", "fraud", "liquidation", "sell-off",
    "outflow", "fear", "warning", "threat", "bankrupt",
]


# ════════════════════════════════════════════════════════════════════════
# FETCH + SCORING
# ════════════════════════════════════════════════════════════════════════

def _fetch_google_news(query, max_hours=24):
    """Retorna lista de (titulo, horas_desde_publicacion)."""
    # Key con el query COMPLETO: truncar a 30 chars hacia colisionar
    # queries de figuras distintas (compartian titulares por error).
    cache_key = f"sent_{query}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        url = (
            "https://news.google.com/rss/search?"
            f"q={urllib.parse.quote(query)}&hl=en-US&gl=US&ceid=US:en"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            xml_data = resp.read()

        root = ET.fromstring(xml_data)
        items = []
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=max_hours)

        for item in root.findall(".//item"):
            title = item.findtext("title", "")
            pub_str = item.findtext("pubDate", "")
            desc = item.findtext("description", "")
            hours_ago = 12  # default
            try:
                pub_dt = parsedate_to_datetime(pub_str)
                if pub_dt < cutoff:
                    continue
                hours_ago = (now - pub_dt).total_seconds() / 3600
            except Exception:
                pass
            text = f"{title} {desc}".lower()
            items.append({"text": text, "title": title, "hours_ago": hours_ago})

        _cache_put(cache_key, items)
        return items

    except Exception as e:
        log("WARN", f"sentiment fetch error: {e}")
        return []


def _score_figure(figure, headlines):
    """
    Puntúa titulares usando keywords específicos de la figura.
    Noticias más recientes pesan más.
    Retorna score -1.0 a +1.0 y lista de eventos detectados.
    """
    if not headlines:
        return 0.0, []

    bull_words = figure.get("bullish", GENERIC_BULLISH)
    bear_words = figure.get("bearish", GENERIC_BEARISH)

    total = 0.0
    events = []

    for h in headlines:
        text = h["text"]
        hours = h["hours_ago"]

        # Peso temporal: noticias de <2h pesan 2x, <6h pesan 1.5x
        if hours < 2:
            time_mult = 2.0
        elif hours < 6:
            time_mult = 1.5
        elif hours < 12:
            time_mult = 1.0
        else:
            time_mult = 0.7

        score = 0
        matched = []
        for w in bull_words:
            if w in text:
                score += 1
                matched.append(f"+{w}")
        for w in bear_words:
            if w in text:
                score -= 1
                matched.append(f"-{w}")

        # También revisar keywords genéricos
        for w in GENERIC_BULLISH:
            if w in text and w not in bull_words:
                score += 0.5
        for w in GENERIC_BEARISH:
            if w in text and w not in bear_words:
                score -= 0.5

        capped = max(-3, min(3, score))
        weighted = capped * time_mult
        total += weighted

        # Detectar eventos de alto impacto (score >= 2 o <= -2)
        if abs(capped) >= 2 and matched:
            direction = "BULL" if capped > 0 else "BEAR"
            short_title = h["title"][:80]
            events.append({
                "direction": direction,
                "score": round(capped * time_mult, 2),
                "title": short_title,
                "hours_ago": round(hours, 1),
                "keywords": matched[:5],
            })

    avg = round(total / len(headlines), 3) if headlines else 0.0
    return max(-1.0, min(1.0, avg)), events


# ════════════════════════════════════════════════════════════════════════
# SEÑAL CONSOLIDADA
# ════════════════════════════════════════════════════════════════════════

def get_sentiment(symbol=None):
    """
    Análisis de sentimiento completo.

    Retorna dict con:
      - overall:    'BULLISH' | 'BEARISH' | 'NEUTRAL'
      - score:      float -1.0 a +1.0 (continuo, para meta-modelo)
      - raw_score:  float sin cap (para detectar spikes)
      - alerts:     list de strings con eventos de alto impacto
      - events:     list de dicts con detalle de eventos
      - figures:    dict por figura con score y detalle
      - spike:      bool — True si hay evento de impacto extremo
      - weight:     2.0 (peso doble en gate)
    """
    cache_key = f"sentiment_{symbol or 'market'}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    figures_data = {}
    alerts = []
    all_events = []
    total_score = 0.0
    total_weight = 0.0

    for fig in FIGURES:
        weight = fig["weight"]

        # Más peso si el par está directamente afectado
        if symbol and symbol in fig.get("assets", []):
            weight *= 1.5

        query = fig["query"]
        if symbol:
            pair_name = symbol.replace("USDT", "")
            query += f" {pair_name}"

        headlines = _fetch_google_news(query, max_hours=24)
        score, events = _score_figure(fig, headlines)

        figures_data[fig["id"]] = {
            "name": fig["name"],
            "score": score,
            "headlines_count": len(headlines),
            "events": events,
            "top_headlines": [h["title"] for h in headlines[:3]],
        }

        total_score += score * weight
        total_weight += weight
        all_events.extend(events)

        # Alertas
        if score >= 0.4:
            alerts.append(f"[BULL] {fig['name']}: sentimiento positivo ({score:+.2f}, {len(headlines)} noticias)")
        elif score <= -0.4:
            alerts.append(f"[BEAR] {fig['name']}: sentimiento negativo ({score:+.2f}, {len(headlines)} noticias)")

    weighted_score = round(total_score / total_weight, 4) if total_weight else 0.0

    # Detectar spike: evento reciente (<4h) con score extremo
    spike = any(
        abs(e["score"]) >= 2.0 and e["hours_ago"] < 4
        for e in all_events
    )

    if weighted_score >= 0.2:
        overall = "BULLISH"
    elif weighted_score <= -0.2:
        overall = "BEARISH"
    else:
        overall = "NEUTRAL"

    result = {
        "overall": overall,
        "score": max(-1.0, min(1.0, weighted_score)),
        "raw_score": weighted_score,
        "alerts": alerts,
        "events": sorted(all_events, key=lambda e: abs(e["score"]), reverse=True)[:10],
        "figures": figures_data,
        "spike": spike,
        "weight": 2.0,
    }

    # Guardar en historial
    _save_sentiment(symbol or "MARKET", result)

    _cache_put(cache_key, result)
    return result


# ════════════════════════════════════════════════════════════════════════
# HISTORIAL DE SENTIMIENTO (detecta cambios)
# ════════════════════════════════════════════════════════════════════════

def _init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS sentiment_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            overall TEXT NOT NULL,
            score REAL NOT NULL,
            spike INTEGER DEFAULT 0,
            alerts_json TEXT,
            figures_json TEXT
        )
    """)
    con.execute("""
        CREATE INDEX IF NOT EXISTS idx_sent_sym_ts
        ON sentiment_history(symbol, timestamp)
    """)
    con.commit()
    return con


def _save_sentiment(symbol, result):
    """Guarda snapshot de sentimiento para historial."""
    try:
        con = _init_db()
        con.execute(
            """INSERT INTO sentiment_history
               (symbol, timestamp, overall, score, spike, alerts_json, figures_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                symbol,
                datetime.now().isoformat(),
                result["overall"],
                result["score"],
                1 if result["spike"] else 0,
                json.dumps(result["alerts"]),
                json.dumps({k: {"score": v["score"], "count": v["headlines_count"]}
                           for k, v in result["figures"].items()}),
            ),
        )
        con.commit()
        con.close()
    except Exception as e:
        log("WARN", f"sentiment save error: {e}")


def get_sentiment_trend(symbol="MARKET", hours=24):
    """
    Retorna tendencia de sentimiento en las últimas N horas.

    Returns dict:
      - direction: 'IMPROVING' | 'WORSENING' | 'STABLE'
      - current:   score actual
      - previous:  score promedio anterior
      - change:    diferencia
      - readings:  número de lecturas en el periodo
    """
    try:
        con = _init_db()
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        rows = con.execute(
            """SELECT score, timestamp FROM sentiment_history
               WHERE symbol = ? AND timestamp > ?
               ORDER BY timestamp""",
            (symbol, cutoff),
        ).fetchall()
        con.close()

        if len(rows) < 2:
            return {"direction": "STABLE", "current": 0, "previous": 0,
                    "change": 0, "readings": len(rows)}

        scores = [r[0] for r in rows]
        mid = len(scores) // 2
        first_half = sum(scores[:mid]) / mid
        second_half = sum(scores[mid:]) / (len(scores) - mid)
        change = second_half - first_half

        if change >= 0.15:
            direction = "IMPROVING"
        elif change <= -0.15:
            direction = "WORSENING"
        else:
            direction = "STABLE"

        return {
            "direction": direction,
            "current": round(scores[-1], 3),
            "previous": round(first_half, 3),
            "change": round(change, 3),
            "readings": len(rows),
        }
    except Exception:
        return {"direction": "STABLE", "current": 0, "previous": 0,
                "change": 0, "readings": 0}


# ════════════════════════════════════════════════════════════════════════
# REPORTE
# ════════════════════════════════════════════════════════════════════════

def print_sentiment_report(symbol=None):
    """Imprime reporte detallado de sentimiento."""
    result = get_sentiment(symbol)
    trend = get_sentiment_trend(symbol or "MARKET")

    icon = {"BULLISH": "[BULL]", "BEARISH": "[BEAR]", "NEUTRAL": "[NEUT]"}[result["overall"]]
    sep = "=" * 62

    pair_label = f" — {symbol}" if symbol else ""
    print(f"\n  {sep}")
    print(f"  SENTIMIENTO CRYPTO{pair_label}")
    print(f"  {len(FIGURES)} figuras monitoreadas | Peso 2x en gate")
    print(f"  {sep}")
    print(f"  Señal: {icon} {result['overall']}  (score: {result['score']:+.3f})")

    if result["spike"]:
        print(f"  ⚡ SPIKE DETECTADO — evento de alto impacto reciente")

    # Tendencia
    trend_icon = {"IMPROVING": "↑", "WORSENING": "↓", "STABLE": "→"}[trend["direction"]]
    print(f"  Tendencia: {trend_icon} {trend['direction']} "
          f"(cambio: {trend['change']:+.3f}, {trend['readings']} lecturas)")
    print()

    # Figuras
    for fid, fdata in result["figures"].items():
        s = fdata["score"]
        n = fdata["headlines_count"]
        if n == 0:
            continue
        bar = "[BULL]" if s >= 0.2 else "[BEAR]" if s <= -0.2 else "[NEUT]"
        print(f"  {bar} {fdata['name']:<28} score {s:+.3f}  ({n} noticias)")
        for title in fdata["top_headlines"][:2]:
            short = title[:75].strip()
            if short:
                print(f"       > {short}...")

    # Eventos de alto impacto
    if result["events"]:
        print(f"\n  EVENTOS DE ALTO IMPACTO:")
        for e in result["events"][:5]:
            icon_e = "[BULL]" if e["direction"] == "BULL" else "[BEAR]"
            print(f"    {icon_e} {e['title'][:70]}")
            print(f"          score={e['score']:+.1f}  hace {e['hours_ago']:.0f}h  "
                  f"keys: {', '.join(e['keywords'][:3])}")

    if result["alerts"]:
        print(f"\n  ALERTAS:")
        for a in result["alerts"]:
            print(f"    {a}")

    print(f"  {sep}\n")
