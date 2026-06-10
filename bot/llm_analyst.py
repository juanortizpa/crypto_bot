"""
llm_analyst.py — Análisis de sentimiento con Claude (Anthropic API)

Usa Claude claude-haiku-4-5 para analizar titulares de noticias crypto y
emitir una señal de sentimiento estructurada que alimenta el factor N1
del gate de decisión.

Flujo:
  1. Recibe una lista de titulares (strings) + el símbolo a analizar.
  2. Envía al LLM un prompt de sistema experto en trading crypto.
  3. Claude devuelve JSON con:
       - sentiment:  "BULLISH" | "BEARISH" | "NEUTRAL"
       - score:      float -1.0 … +1.0
       - confidence: float  0.0 … 1.0
       - key_signals: lista de las señales más relevantes detectadas
       - reasoning:  explicación breve en español
  4. El resultado se usa en crypto_gate.py para el factor N1 con peso 2x.

Requisitos:
  - Variable de entorno ANTHROPIC_API_KEY en el .env del proyecto.
  - pip install anthropic

Si la API key no está configurada, devuelve sentimiento NEUTRAL sin error
para no bloquear el resto del bot.
"""

import os
import sys
import json
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bot.logger import log

# Carga opcional de .env
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:
    pass

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Cache: evita llamadas repetidas si los titulares no cambiaron (TTL 5 min)
_cache: dict = {}
_cache_ts: dict = {}
CACHE_TTL = 300  # segundos


SYSTEM_PROMPT = """Eres un analista experto en trading de criptomonedas.
Tu tarea es analizar titulares de noticias y determinar el impacto en el precio del activo indicado.

Reglas de clasificación:
- BULLISH: noticias de adopción institucional, ETF aprobado, regulación favorable,
  tweet positivo de Elon Musk, reducción de tasas Fed, alianzas estratégicas,
  halving, actualizaciones de red exitosas.
- BEARISH: hackeos/exploits, regulación restrictiva, prohibiciones, SEC demandas,
  quiebras de exchanges, ballenas vendiendo masivamente, tasas al alza.
- NEUTRAL: noticias técnicas sin impacto inmediato, actualizaciones de desarrollo,
  eventos sin dirección clara.

Señales de alto impacto (peso doble):
- Elon Musk menciona el activo → muy fuerte
- Trump o gobierno de EE.UU menciona crypto → muy fuerte
- ETF aprobado/rechazado → muy fuerte
- Hack o exploit confirmado → muy fuerte bajista inmediato

Responde ÚNICAMENTE con un JSON válido, sin texto adicional:
{
  "sentiment": "BULLISH" | "BEARISH" | "NEUTRAL",
  "score": <float de -1.0 a +1.0>,
  "confidence": <float de 0.0 a 1.0>,
  "key_signals": ["señal 1", "señal 2"],
  "reasoning": "<explicación breve en español, max 2 oraciones>"
}"""


def _neutral_result(reason: str = "") -> dict:
    return {
        "sentiment": "NEUTRAL",
        "score": 0.0,
        "confidence": 0.0,
        "key_signals": [],
        "reasoning": reason or "Sin datos suficientes para análisis.",
        "source": "fallback",
    }


def analyze_news(headlines: list[str], symbol: str = "crypto") -> dict:
    """
    Analiza una lista de titulares para el símbolo dado.

    Args:
        headlines: lista de strings con titulares de noticias
        symbol:    símbolo del activo (ej. "BTC", "ETH", "DOGE")

    Returns:
        dict con sentiment, score, confidence, key_signals, reasoning, source
    """
    if not headlines:
        return _neutral_result("Sin titulares disponibles.")

    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("sk-ant-") is False and len(ANTHROPIC_API_KEY) < 20:
        return _neutral_result("ANTHROPIC_API_KEY no configurada.")

    # Cache key = primeros 5 titulares + símbolo
    cache_key = symbol + "|" + "|".join(headlines[:5])
    now = time.time()
    if cache_key in _cache and (now - _cache_ts.get(cache_key, 0)) < CACHE_TTL:
        cached = _cache[cache_key].copy()
        cached["source"] = "cache"
        return cached

    # Preparar mensaje
    headlines_text = "\n".join(f"- {h}" for h in headlines[:15])  # máx 15 titulares
    user_msg = f"Activo: {symbol.upper()}\n\nTitulares recientes:\n{headlines_text}"

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = message.content[0].text.strip()

        # Extraer JSON si viene envuelto en markdown
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        result = json.loads(raw)
        result["source"] = "claude"

        # Validar campos mínimos
        if "sentiment" not in result or result["sentiment"] not in ("BULLISH", "BEARISH", "NEUTRAL"):
            raise ValueError(f"sentiment inválido: {result.get('sentiment')}")

        result["score"] = float(result.get("score", 0.0))
        result["confidence"] = float(result.get("confidence", 0.5))
        result.setdefault("key_signals", [])
        result.setdefault("reasoning", "")

        # Guardar en cache
        _cache[cache_key] = result.copy()
        _cache_ts[cache_key] = now

        log("INFO", f"llm_analyst: {symbol} → {result['sentiment']} (score={result['score']:+.2f}, conf={result['confidence']:.2f})")
        return result

    except Exception as e:
        log("WARN", f"llm_analyst: error en Claude API: {e}")
        return _neutral_result(f"Error de API: {str(e)[:80]}")


def analyze_symbol_news(symbol: str, news_list: list[dict]) -> dict:
    """
    Wrapper conveniente: recibe la lista de dicts que devuelve crypto_news.py
    (cada dict tiene al menos una clave 'title') y extrae los titulares.

    Args:
        symbol:    símbolo limpio, ej. "BTC"
        news_list: lista de dicts con clave 'title'

    Returns:
        mismo formato que analyze_news()
    """
    headlines = [n.get("title", "") for n in news_list if n.get("title")]
    return analyze_news(headlines, symbol)


# ── CLI de prueba ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Test del analizador LLM de noticias crypto")
    ap.add_argument("symbol", nargs="?", default="BTC", help="Símbolo (ej. BTC, ETH, DOGE)")
    args = ap.parse_args()

    sym = args.symbol.upper()
    print(f"\n  Analizando noticias de {sym} con Claude...\n")

    # Importar noticias reales del módulo crypto_news
    headlines = []
    try:
        from bot.crypto_news import get_news_signal
        signal = get_news_signal(sym + "USDT")
        for v in signal.get("details", {}).values():
            headlines.extend(v.get("headlines", []))
    except Exception:
        pass

    if not headlines:
        # Fallback con titulares de ejemplo para testing
        headlines = [
            f"bitcoin surges past $100k as institutional demand grows",
            f"sec approves new spot {sym.lower()} etf applications",
            f"elon musk tweets about {sym.lower()} sending price up 15%",
            f"federal reserve signals interest rate cuts in 2026",
        ]

    result = analyze_news(headlines, sym)

    print(f"  Símbolo:      {sym}")
    print(f"  Sentimiento:  {result['sentiment']}")
    print(f"  Score:        {result['score']:+.2f}")
    print(f"  Confianza:    {result['confidence']:.0%}")
    print(f"  Fuente:       {result['source']}")
    if result.get("key_signals"):
        print(f"  Señales clave:")
        for s in result["key_signals"]:
            print(f"    • {s}")
    print(f"  Razonamiento: {result['reasoning']}")
    print()
