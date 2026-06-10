"""
6 modelos de prediccion CRYPTO para operaciones rapidas (1-3 horas).
Cada modelo tiene un umbral de gate distinto + 1-2 filtros extra.

PRINCIPIO: El gate de 13 factores ya hace el trabajo pesado.
Los modelos solo deciden CUANTO riesgo tomar segun el gate score.

A -- Scalp Conservador:  Gate >= 7, 0 RED. Stops tight.
B -- Momentum Burst:     Gate >= 5, 0 RED. S1 o T1 verde.
C -- News Spike:         Gate >= 4, max 1 RED. N1 verde.
D -- Dip Scalper:        Gate >= 3, max 2 RED. F&G < 45 o RSI bajo.
E -- Breakout Micro:     Gate >= 5, 0 RED. T3 verde (senal entrada).
F -- Trend Rider:        Gate >= 6, 0 RED. M1 verde (BTC alcista).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from bot.crypto_gate import GREEN, YELLOW, RED
from bot.crypto_data import get_fear_greed

MODELS = {
    "A": {
        "name":        "Scalp Conservador",
        "description": "Gate >= 7, 0 RED. Setup limpio. Stop -1.5%, target +2.5%.",
        "stop_pct":    0.015,
        "target_pct":  0.025,
        "max_hours":   4,
        "trail_after": 0.5,
    },
    "B": {
        "name":        "Momentum Burst",
        "description": "Gate >= 5, 0 RED. Momentum (S1/T1 verde). Stop -2%, target +3.5%.",
        "stop_pct":    0.02,
        "target_pct":  0.035,
        "max_hours":   2,
        "trail_after": 0.5,
    },
    "C": {
        "name":        "News Spike",
        "description": "Gate >= 4, max 1 RED. N1 verde (noticias). Stop -1.5%, target +2%.",
        "stop_pct":    0.015,
        "target_pct":  0.02,
        "max_hours":   4,
        "trail_after": 0.5,
    },
    "D": {
        "name":        "Dip Scalper",
        "description": "Gate >= 3, max 2 RED. F&G < 45 o dip. Stop -2.5%, target +3%.",
        "stop_pct":    0.025,
        "target_pct":  0.03,
        "max_hours":   8,
        "trail_after": 0.4,
    },
    "E": {
        "name":        "Breakout Micro",
        "description": "Gate >= 5, 0 RED. T3 verde (entrada). Stop -2%, target +4%.",
        "stop_pct":    0.02,
        "target_pct":  0.04,
        "max_hours":   6,
        "trail_after": 0.5,
    },
    "F": {
        "name":        "Trend Rider",
        "description": "Gate >= 6, 0 RED. M1 verde (BTC alcista). Stop -1.8%, target +3%.",
        "stop_pct":    0.018,
        "target_pct":  0.03,
        "max_hours":   12,
        "trail_after": 0.3,
    },
}


def evaluate_model(model_id, gate, tech):
    """
    Evalua si un par califica para el modelo dado.
    Se basa principalmente en el gate score + 1-2 filtros del gate.
    Retorna (califica: bool, stop: float, target: float).
    """
    price   = tech.get("price")
    factors = gate.factors
    model   = MODELS.get(model_id, {})

    if not price:
        return False, None, None

    stop_pct   = model.get("stop_pct", 0.02)
    target_pct = model.get("target_pct", 0.03)

    def _color(factor_name):
        return factors.get(factor_name, {}).get("color", YELLOW)

    # ── GUARDAS GLOBALES (todos los modelos excepto D) ──────────────────
    # Tu propio diagnostico (DIAGNOSIS_0TRADES.md) lo dice: la senal viene
    # del REGIMEN, no de los features. Estas guardas lo aplican:
    #
    # 1) Regimen BTC bajista (M1 RED): un sistema long-only pierde en serie
    #    cuando BTC cae. Solo D (Dip Scalper) tiene tesis valida ahi.
    # 2) Senal bajista del propio par (score >= 4 de 7): el lado corto
    #    domina — no abrir longs contra esa corriente (excepto D).
    if model_id != "D":
        if _color("M1") == RED:
            return False, None, None
        try:
            from bot.short_signal import bearish_score, VETO_THRESHOLD
            b_score, _ = bearish_score(gate.symbol)
            if b_score >= VETO_THRESHOLD:
                return False, None, None
        except Exception:
            pass  # sin datos no se veta (fail-open)

    califica = False

    if model_id == "A":
        # Scalp Conservador: gate alto, setup limpio (tolera 1 RED aislado)
        califica = (gate.green_count >= 7 and gate.red_count <= 1)

    elif model_id == "B":
        # Momentum Burst: momentum positivo confirmado
        momentum_ok = _color("S1") == GREEN or _color("T1") == GREEN
        califica = (gate.green_count >= 5 and gate.red_count <= 1 and momentum_ok)

    elif model_id == "C":
        # News Spike: noticias positivas
        news_ok = _color("N1") == GREEN
        califica = (gate.green_count >= 4 and gate.red_count <= 1 and news_ok)

    elif model_id == "D":
        # Dip Scalper: busca rebotes en miedo (el unico que tolera 2 RED)
        fng = get_fear_greed()
        fear_ok = fng["value"] < 45
        dip_ok = fear_ok or _color("S1") == RED
        califica = (gate.green_count >= 3 and gate.red_count <= 2 and dip_ok)

    elif model_id == "E":
        # Breakout Micro: senal de entrada clara
        entry_ok = _color("T3") == GREEN
        califica = (gate.green_count >= 5 and gate.red_count <= 1 and entry_ok)

    elif model_id == "F":
        # Trend Rider: BTC alcista, montar la ola
        btc_ok = _color("M1") == GREEN
        califica = (gate.green_count >= 6 and gate.red_count <= 1 and btc_ok)

    if califica:
        # Stops/targets dinamicos por ATR del activo (override del default del modelo)
        # Se mantiene el max_hours del modelo y el "perfil" general pero el riesgo
        # se adapta a la volatilidad real -> evita stops prematuros en alta vol
        # y targets inalcanzables en baja vol.
        try:
            from bot.dynamic_levels import dynamic_stop_target_pct
            from bot.crypto_data import get_bars
            from bot.crypto_data import atr as atr_fn
            bars_1h = get_bars(tech.get("symbol") or tech.get("pair", ""), "1h", 30)
            atr_val = atr_fn(bars_1h, 14) if bars_1h and len(bars_1h) >= 15 else None
            atr_pct = (atr_val / price * 100) if atr_val and price else None
            if atr_pct:
                dyn = dynamic_stop_target_pct(atr_pct)
                # dyn devuelve porcentajes positivos (1.5 = 1.5%)
                stop_pct = dyn["stop_pct"] / 100.0
                target_pct = dyn["target_pct"] / 100.0
        except Exception:
            # Si falla, usa los del modelo (fallback seguro)
            pass

        stop   = round(price * (1 - stop_pct), 6)
        target = round(price * (1 + target_pct), 6)
        return True, stop, target

    return False, None, None
