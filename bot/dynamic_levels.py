"""
Dynamic Levels — calcula stop y target adaptados a volatilidad real del activo.

Reemplaza los -2.5% / +4% fijos por niveles basados en ATR del activo.
Centraliza la formula para que features.py (entrenamiento) y
trade_monitor.py (runtime) compartan exactamente la misma logica.

Formula (perfil balance riesgo/retorno con $500):

    stop_dist_pct   = max(STOP_ATR_MULT * atr_pct, STOP_FLOOR_PCT)
    target_dist_pct = max(TGT_ATR_MULT  * atr_pct, TGT_FLOOR_PCT)

    # Asegurar R:R minimo
    if target_dist_pct / stop_dist_pct < MIN_RR:
        target_dist_pct = stop_dist_pct * MIN_RR

    # Cap absoluto (evita stops/targets ridiculamente amplios en altas vol)
    stop_dist_pct   = min(stop_dist_pct, STOP_CAP_PCT)
    target_dist_pct = min(target_dist_pct, TGT_CAP_PCT)

Defaults (configurable por env CRYPTO_*):
  STOP_ATR_MULT = 1.5  → stop esta a 1.5 ATR del entry
  TGT_ATR_MULT  = 2.5  → target a 2.5 ATR
  STOP_FLOOR_PCT = 1.2 → minimo absoluto 1.2% (debajo es ruido)
  TGT_FLOOR_PCT  = 2.5 → minimo absoluto 2.5%
  STOP_CAP_PCT  = 4.0  → maximo absoluto 4.0%
  TGT_CAP_PCT   = 8.0  → maximo absoluto 8.0%
  MIN_RR        = 1.7  → relacion riesgo/recompensa minima
"""
import os

STOP_ATR_MULT = float(os.environ.get("CRYPTO_STOP_ATR_MULT", "1.5"))
TGT_ATR_MULT = float(os.environ.get("CRYPTO_TGT_ATR_MULT", "2.5"))
STOP_FLOOR_PCT = float(os.environ.get("CRYPTO_STOP_FLOOR_PCT", "1.2"))
TGT_FLOOR_PCT = float(os.environ.get("CRYPTO_TGT_FLOOR_PCT", "2.5"))
STOP_CAP_PCT = float(os.environ.get("CRYPTO_STOP_CAP_PCT", "4.0"))
TGT_CAP_PCT = float(os.environ.get("CRYPTO_TGT_CAP_PCT", "8.0"))
MIN_RR = float(os.environ.get("CRYPTO_MIN_RR", "1.7"))


def dynamic_stop_target_pct(atr_pct: float) -> dict:
    """
    Dada la volatilidad del activo (ATR 1h como % del precio),
    calcula distancia de stop y target en porcentaje.

    Retorna dict con: stop_pct, target_pct, rr_ratio, atr_pct_input.
    """
    if atr_pct is None or atr_pct <= 0:
        # Fallback conservador: ATR desconocido → usar floors
        atr_pct = 1.0

    stop_pct = max(STOP_ATR_MULT * atr_pct, STOP_FLOOR_PCT)
    target_pct = max(TGT_ATR_MULT * atr_pct, TGT_FLOOR_PCT)

    # Asegurar R:R minimo
    if stop_pct > 0 and (target_pct / stop_pct) < MIN_RR:
        target_pct = stop_pct * MIN_RR

    # Caps absolutos
    stop_pct = min(stop_pct, STOP_CAP_PCT)
    target_pct = min(target_pct, TGT_CAP_PCT)

    return {
        "stop_pct":     round(stop_pct, 3),
        "target_pct":   round(target_pct, 3),
        "rr_ratio":     round(target_pct / stop_pct, 2) if stop_pct > 0 else 0,
        "atr_pct":      round(atr_pct, 3),
    }


def dynamic_levels(entry_price: float, atr_pct: float) -> dict:
    """
    Como `dynamic_stop_target_pct` pero devuelve tambien precios absolutos
    (LONG: stop por debajo, target por encima).
    """
    pcts = dynamic_stop_target_pct(atr_pct)
    stop_price = entry_price * (1 - pcts["stop_pct"] / 100)
    target_price = entry_price * (1 + pcts["target_pct"] / 100)
    return {
        **pcts,
        "entry_price":  entry_price,
        "stop_price":   round(stop_price, 8),
        "target_price": round(target_price, 8),
    }


def atr_pct_from_bars(bars: list, period: int = 14) -> float | None:
    """
    Helper: calcula ATR(period) sobre velas y lo expresa como % del ultimo close.
    Si no hay suficientes velas devuelve None.

    Las velas deben venir como list de dicts con keys: o, h, l, c (o open/high/low/close).
    """
    if not bars or len(bars) < period + 1:
        return None

    # tolerancia a ambos formatos
    def _h(b): return b.get("h", b.get("high"))
    def _l(b): return b.get("l", b.get("low"))
    def _c(b): return b.get("c", b.get("close"))

    trs = []
    for i in range(1, len(bars)):
        high = _h(bars[i]); low = _l(bars[i])
        prev_close = _c(bars[i-1])
        if None in (high, low, prev_close):
            continue
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)

    if len(trs) < period:
        return None
    atr_value = sum(trs[-period:]) / period
    last_close = _c(bars[-1])
    if not last_close or last_close <= 0:
        return None
    return atr_value / last_close * 100


def trailing_stop_pct(initial_stop_pct: float, pnl_pct: float) -> float | None:
    """
    Politica de trailing stop por hitos.
      pnl < +1R -> stop original
      +1R <= pnl < +2R -> stop a break-even (0%)
      +2R <= pnl < +3R -> stop a +1R (initial_stop_pct)
      pnl >= +3R -> stop sube siguiendo al precio a 50% del avance sobre +2R

    Devuelve la NUEVA distancia del stop al precio actual (no al entry).
    None si no hay cambio respecto al stop original.

    initial_stop_pct: distancia inicial entry->stop (positivo, p.ej. 2.5).
    pnl_pct: P&L actual del trade (positivo si en ganancia).
    """
    if initial_stop_pct <= 0:
        return None
    r = pnl_pct / initial_stop_pct  # cuantos R llevamos
    if r < 1.0:
        return None  # no mover stop todavia
    if r < 2.0:
        # break-even (incluir comisiones aproximadas: 0.2%)
        return pnl_pct + 0.2
    if r < 3.0:
        # asegurar +1R (entry + initial_stop_pct)
        return pnl_pct - initial_stop_pct + 0.2
    # >=3R: stop dinamico al 50% del avance sobre +2R
    locked = initial_stop_pct * 2 + (pnl_pct - initial_stop_pct * 2) * 0.5
    return pnl_pct - locked + 0.2


def should_extend_target(pnl_pct: float, target_pct: float,
                          momentum_strong: bool,
                          extensions_done: int = 0,
                          max_extensions: int = 2) -> dict:
    """
    Politica de extension de target.
    Si llegamos al target y el momentum sigue fuerte, extender +50% el target.
    Maximo 2 extensiones (target original x 2.25).
    """
    if extensions_done >= max_extensions:
        return {"extend": False, "reason": "max_extensions_reached"}
    if pnl_pct < target_pct * 0.97:
        return {"extend": False, "reason": "not_at_target"}
    if not momentum_strong:
        return {"extend": False, "reason": "momentum_weak"}
    new_target = target_pct * 1.5
    return {
        "extend": True,
        "new_target_pct": round(new_target, 3),
        "extensions_done": extensions_done + 1,
        "reason": "momentum_strong",
    }


if __name__ == "__main__":
    # Test con varios escenarios de volatilidad
    print(f"{'ATR%':<8} {'Stop%':<8} {'Target%':<10} {'R:R':<6}")
    for atr in [0.3, 0.5, 0.8, 1.0, 1.5, 2.0, 3.0, 5.0]:
        r = dynamic_stop_target_pct(atr)
        print(f"{atr:<8.2f} {r['stop_pct']:<8.2f} {r['target_pct']:<10.2f} {r['rr_ratio']:<6.2f}")
