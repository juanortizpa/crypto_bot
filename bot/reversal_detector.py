"""
Reversal Detector — detecta cuando un par esta bajando y a punto de revertir.

ESTRATEGIA:
  1. OBSERVAR: rastrear precio de cada par en cada escaneo
  2. DETECTAR: identificar pares en caida (drawdown desde max reciente)
  3. CONFIRMAR: esperar señales de reversion antes de entrar
  4. ENTRAR: cuando la reversion se confirma, generar prediccion

SEÑALES DE REVERSION (se acumulan como puntaje):
  +2  RSI cruzando arriba de 30 (saliendo de oversold)
  +2  Precio rebotando de MA50 (soporte fuerte)
  +1  Volumen actual > 1.5x promedio (interes comprador)
  +1  Ultima vela verde despues de 3+ rojas (cambio de momentum)
  +1  Drawdown > 5% desde max reciente (caida significativa)
  +1  F&G < 35 (mercado en miedo = oportunidad)
  +1  MACD histogram pasando de negativo a menos negativo

  Umbral: puntaje >= 4 = señal de entrada

ANTI-SEÑALES (invalidan la reversion):
  -3  Precio bajo MA200 (tendencia macro bajista)
  -2  Volumen decreciente en el rebote (fake bounce)
  -1  BTC cayendo fuerte (arrastra todo)
"""
import os, sys, json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from bot.crypto_data import (
    get_bars, get_price, get_fear_greed,
    sma, rsi, atr, avg_volume, buy_sell_ratio,
    get_btc_trend
)
from bot.logger import log


class ReversalSignal:
    """Resultado del analisis de reversion para un par."""
    def __init__(self, symbol):
        self.symbol = symbol
        self.score = 0
        self.signals = []       # señales positivas
        self.anti_signals = []  # señales negativas
        self.drawdown_pct = 0
        self.price = 0
        self.rsi_val = None
        self.phase = "NONE"     # NONE | DECLINING | BOTTOMING | REVERSING
        self.entry_ready = False

    def add(self, points, reason):
        if points > 0:
            self.signals.append((points, reason))
        else:
            self.anti_signals.append((points, reason))
        self.score += points

    @property
    def net_score(self):
        return self.score

    def summary(self):
        parts = [f"{self.symbol} [{self.phase}] score={self.net_score}"]
        if self.drawdown_pct:
            parts.append(f"dd={self.drawdown_pct:+.1f}%")
        if self.rsi_val:
            parts.append(f"RSI={self.rsi_val:.0f}")
        if self.entry_ready:
            parts.append("→ ENTRY!")
        return "  ".join(parts)


def analyze_reversal(symbol, min_score=4) -> ReversalSignal:
    """
    Analiza un par para detectar señales de reversion alcista.

    Usa velas de 1h para timing preciso y 1d para contexto.

    Retorna ReversalSignal con score y detalle.
    """
    result = ReversalSignal(symbol)

    # Obtener datos
    bars_1h = get_bars(symbol, "1h", 100)   # ~4 dias de datos
    bars_1d = get_bars(symbol, "1d", 60)    # 2 meses

    if len(bars_1h) < 30 or len(bars_1d) < 20:
        result.phase = "NO_DATA"
        return result

    closes_1h = [b["c"] for b in bars_1h]
    closes_1d = [b["c"] for b in bars_1d]
    volumes_1h = [b["v"] for b in bars_1h]
    price = closes_1h[-1]
    result.price = price

    # ── Helpers locales (sma/rsi devuelven un solo float) ──────────

    def _sma_list(closes, period):
        """SMA rolling: retorna lista de valores."""
        if len(closes) < period:
            return []
        return [sum(closes[i-period:i]) / period for i in range(period, len(closes) + 1)]

    def _rsi_pair(bars_list, period=14):
        """Calcula RSI actual y anterior usando las bars."""
        if len(bars_list) < period + 2:
            return 50, 50
        # RSI actual (todas las bars)
        rsi_now = rsi(bars_list, period)
        # RSI anterior (sin la ultima bar)
        rsi_prev = rsi(bars_list[:-1], period)
        return (rsi_now or 50), (rsi_prev or 50)

    # ── Calcular indicadores ────────────────────────────────────────

    # RSI 14 en 1h (actual y anterior)
    rsi_now, rsi_prev = _rsi_pair(bars_1h, 14)
    result.rsi_val = rsi_now

    # Medias moviles (valores actuales, single float)
    ma20_1h_now  = sma(bars_1h, 20)
    ma50_1h_now  = sma(bars_1h, 50)
    ma20_1h_prev = sma(bars_1h[:-1], 20)  # valor anterior
    ma50_1h_prev = sma(bars_1h[:-1], 50)
    ma20_1d_now  = sma(bars_1d, 20)
    ma50_1d_now  = sma(bars_1d, 50)
    ma200_1d_now = sma(bars_1d, 200) if len(bars_1d) >= 200 else None

    # Volumen promedio
    avg_vol_1h = sum(volumes_1h[-20:]) / 20 if len(volumes_1h) >= 20 else 1
    vol_now = volumes_1h[-1]
    vol_ratio = vol_now / avg_vol_1h if avg_vol_1h > 0 else 1

    # Max reciente (ultimas 48h = 48 velas de 1h)
    lookback = min(48, len(closes_1h))
    recent_high = max(closes_1h[-lookback:])
    drawdown = (price - recent_high) / recent_high * 100
    result.drawdown_pct = round(drawdown, 2)

    # Velas recientes (colores)
    recent_candles = []
    for b in bars_1h[-8:]:
        recent_candles.append("green" if b["c"] >= b["o"] else "red")

    # Racha de rojas consecutivas antes de la ultima verde
    red_streak = 0
    for c in reversed(recent_candles[:-1]):
        if c == "red":
            red_streak += 1
        else:
            break

    # ── Determinar fase ─────────────────────────────────────────────

    if drawdown > -1:
        result.phase = "STABLE"
    elif drawdown > -3:
        result.phase = "DIPPING"
    elif rsi_now < 35:
        result.phase = "BOTTOMING"
    elif rsi_now > rsi_prev and drawdown < -3:
        result.phase = "REVERSING"
    else:
        result.phase = "DECLINING"

    # ── Señales de reversion ────────────────────────────────────────

    # RSI saliendo de oversold (cruce arriba de 30)
    if rsi_prev < 30 and rsi_now >= 30:
        result.add(+2, f"RSI cruzó 30↑ ({rsi_prev:.0f}→{rsi_now:.0f})")
    elif rsi_now < 30:
        result.add(+1, f"RSI oversold ({rsi_now:.0f})")

    # Rebote en MA50 horaria
    if ma50_1h_now and ma50_1h_prev:
        near_ma50 = abs(price - ma50_1h_now) / ma50_1h_now < 0.01
        bouncing = price > ma50_1h_now and closes_1h[-2] <= ma50_1h_prev
        if bouncing:
            result.add(+2, f"Rebote en MA50(1h)")
        elif near_ma50 and price > ma50_1h_now:
            result.add(+1, f"Cerca de MA50(1h), arriba")

    # Rebote en MA20 diaria
    if ma20_1d_now:
        near_ma20d = abs(price - ma20_1d_now) / ma20_1d_now < 0.015
        if near_ma20d and price > ma20_1d_now:
            result.add(+1, f"Rebote en MA20(1d)")

    # Volumen alto (interes comprador)
    if vol_ratio >= 2.0:
        result.add(+2, f"Volumen {vol_ratio:.1f}x avg (spike)")
    elif vol_ratio >= 1.5:
        result.add(+1, f"Volumen {vol_ratio:.1f}x avg")

    # Vela verde despues de racha roja
    if recent_candles[-1] == "green" and red_streak >= 3:
        result.add(+2, f"Verde tras {red_streak} rojas seguidas")
    elif recent_candles[-1] == "green" and red_streak >= 2:
        result.add(+1, f"Verde tras {red_streak} rojas")

    # Drawdown significativo (oportunidad de compra)
    if drawdown <= -8:
        result.add(+2, f"Drawdown fuerte ({drawdown:.1f}%)")
    elif drawdown <= -5:
        result.add(+1, f"Drawdown moderado ({drawdown:.1f}%)")

    # Fear & Greed bajo (mercado en panico)
    fng = get_fear_greed()
    fng_val = fng.get("value", 50) if fng else 50
    if fng_val < 25:
        result.add(+2, f"F&G extremo ({fng_val})")
    elif fng_val < 35:
        result.add(+1, f"F&G miedo ({fng_val})")

    # Momentum cambiando (velocidad de caida disminuyendo)
    if len(closes_1h) >= 6:
        vel_recent = (closes_1h[-1] - closes_1h[-3]) / closes_1h[-3] * 100
        vel_before = (closes_1h[-3] - closes_1h[-6]) / closes_1h[-6] * 100
        if vel_before < -0.5 and vel_recent > vel_before:
            result.add(+1, f"Momentum frenando ({vel_before:.2f}%→{vel_recent:.2f}%)")

    # ── Anti-señales ────────────────────────────────────────────────

    # Bajo MA200 diaria (tendencia macro bajista)
    if ma200_1d_now and price < ma200_1d_now:
        result.add(-3, f"Bajo MA200(1d) — tendencia macro bajista")

    # Bajo MA50 diaria sin señales de rebote
    if ma50_1d_now and price < ma50_1d_now and rsi_now > 40:
        result.add(-1, f"Bajo MA50(1d) sin oversold")

    # Volumen bajo en el rebote (fake bounce)
    if recent_candles[-1] == "green" and vol_ratio < 0.7:
        result.add(-2, f"Rebote sin volumen ({vol_ratio:.1f}x)")

    # BTC cayendo fuerte
    btc_trend = get_btc_trend()
    if isinstance(btc_trend, dict) and btc_trend.get("trend") == "BEARISH":
        result.add(-2, f"BTC bajista")

    # ── Decision ────────────────────────────────────────────────────

    result.entry_ready = result.net_score >= min_score
    return result


def scan_reversals(pairs, min_score=4, top_n=10) -> list:
    """
    Escanea una lista de pares y retorna los mejores candidatos
    para entrada por reversion, ordenados por score.
    """
    results = []
    for pair in pairs:
        try:
            r = analyze_reversal(pair, min_score=min_score)
            if r.phase not in ("NO_DATA", "STABLE"):
                results.append(r)
        except Exception as e:
            log("WARN", f"reversal scan error {pair}: {e}")

    # Ordenar por score (mayor = mejor candidato)
    results.sort(key=lambda r: r.net_score, reverse=True)
    return results[:top_n]
