"""
Short Signal — score bajista 0-7 construido con los MISMOS factores del gate,
leidos en espejo (lado corto).

Los factores del bot siempre tuvieron informacion bajista (RSI alto, momentum
negativo, estructura de MAs rota, BTC cayendo, vendedores dominando), pero el
pipeline solo la usaba para decir "no compres". Este modulo la convierte en
senal activa con dos usos:

  1. VETO de entradas long:    bearish_score >= VETO_THRESHOLD
  2. SALIDA anticipada:        proteger ganancia / cortar perdida en monitor

No ejecuta shorts (spot no lo permite). Si algun dia se conecta Futures,
este mismo score es la base de la senal de entrada corta.

Uso:
    from bot.short_signal import bearish_score
    score, reasons = bearish_score("ETHUSDT")
    if score >= 4: ...  # mercado del par claramente bajista
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from bot.crypto_data import get_bars, sma, rsi, buy_sell_ratio
from bot.logger import log

# Umbral recomendado para veto/salida (de 7 posibles)
VETO_THRESHOLD = 4


def bearish_score(symbol):
    """
    Calcula score bajista 0-7 para un par.

    Retorna (score: int, reasons: list[str]).
    En caso de error de datos retorna (0, ["NO_DATA"]) — neutral, no veta.
    """
    try:
        bars_1h = get_bars(symbol, "1h", 60)
        if not bars_1h or len(bars_1h) < 55:
            return 0, ["NO_DATA"]

        closes = [b["c"] for b in bars_1h]
        price = closes[-1]
        score = 0
        reasons = []

        # 1. RSI 1h en sobrecompra (>70): probabilidad de reversion a la baja
        rsi_1h = rsi(bars_1h, 14)
        if rsi_1h and rsi_1h > 70:
            score += 1
            reasons.append(f"RSI(1h) {rsi_1h:.0f} sobrecompra")

        # 2. Estructura rota: precio bajo MA20 y MA20 bajo MA50 (1h)
        ma20 = sma(bars_1h, 20)
        ma50 = sma(bars_1h, 50)
        if ma20 and ma50 and price < ma20 and ma20 < ma50:
            score += 1
            reasons.append("estructura bajista (p<MA20<MA50)")

        # 3. Momentum 4h claramente negativo
        if len(bars_1h) >= 5:
            mom_4h = (closes[-1] - closes[-5]) / closes[-5] * 100
            if mom_4h < -1.0:
                score += 1
                reasons.append(f"mom 4h {mom_4h:+.1f}%")

        # 4. Micro-tendencia 6h: mayoria de velas rojas y retorno negativo
        if len(bars_1h) >= 7:
            ret_6h = (closes[-1] - closes[-7]) / closes[-7] * 100
            red_candles = sum(1 for b in bars_1h[-6:] if b["c"] < b["o"])
            if ret_6h < -0.3 and red_candles >= 4:
                score += 1
                reasons.append(f"{red_candles}/6 velas rojas, {ret_6h:+.1f}% 6h")

        # 5. BTC cayendo en 24h (arrastra a casi todo el mercado)
        btc = get_bars("BTCUSDT", "1h", 26)
        if btc and len(btc) >= 25:
            btc_24h = (btc[-1]["c"] - btc[-25]["c"]) / btc[-25]["c"] * 100
            if btc_24h < -2.0:
                score += 1
                reasons.append(f"BTC {btc_24h:+.1f}% 24h")

        # 6. Vendedores dominando (taker buy ratio bajo)
        bs = buy_sell_ratio(bars_1h, 6)
        if bs and bs < 0.45:
            score += 1
            reasons.append(f"B/S {bs:.2f} vendedores")

        # 7. Precio muy extendido sobre MA50 (>8%): riesgo de reversion
        if ma50 and (price - ma50) / ma50 * 100 > 8.0:
            score += 1
            reasons.append("extendido >8% sobre MA50")

        return score, reasons

    except Exception as e:
        log("WARN", f"bearish_score({symbol}): {e}")
        return 0, ["ERROR"]


def is_bearish(symbol, threshold=VETO_THRESHOLD):
    """Atajo booleano: True si el score bajista alcanza el umbral."""
    score, _ = bearish_score(symbol)
    return score >= threshold
