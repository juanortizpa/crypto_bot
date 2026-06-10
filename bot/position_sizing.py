"""
Position Sizing Dinámico — $1000 capital, cap 50% total expuesto.

LÓGICA:
  Cada trade recibe un % del capital según qué tan seguro es.
  El total invertido nunca supera el 50% del capital ($500).

TIERS por (gate_green + ml_decision):
  PREMIUM  — gate >= 12  +  ML=FULL          → 15% = $150
  ALTO     — gate >= 10  +  ML=FULL          → 12% = $120
  MEDIO    — gate >= 10  +  ML=HALF          →  8% = $80
  CAUTELOSO— gate >= 10  +  ML=WATCH/ABORT   →  5% = $50
  MINIMO   — gate < 10   (no deberia pasar)  →  3% = $30

Ajustes adicionales:
  - Drawdown > 5%  → reducir tiers al 70%
  - Drawdown > 10% → reducir tiers al 50%
  - WR histórico > 60% del modelo → bonus +20%
  - WR histórico < 40% del modelo → penalizacion -20%

Cap total:
  - Suma de posiciones abiertas + nuevas <= 50% del capital
  - Máximo 5 posiciones simultáneas
"""

import os
import sqlite3
from bot.capital_profile import get_profile

# ── Constantes ────────────────────────────────────────────────────────────
MAX_EXPOSURE_PCT  = 0.50   # nunca más del 50% expuesto
MAX_TRADES        = 5      # máximo 5 posiciones simultáneas
MIN_POSITION_USD  = 10.0   # mínimo viable para cubrir comisiones

# Tiers de sizing como % del capital
TIERS = {
    "PREMIUM":   0.15,   # gate>=12 + ML=FULL
    "ALTO":      0.12,   # gate>=10 + ML=FULL
    "MEDIO":     0.08,   # gate>=10 + ML=HALF
    "CAUTELOSO": 0.05,   # gate>=10 + ML=WATCH/ABORT
    "MINIMO":    0.03,   # gate<10
}


def _get_tier(gate_green: int, ml_decision: str) -> str:
    """Determina el tier de sizing según gate y decisión ML."""
    ml = (ml_decision or "UNKNOWN").upper()

    if gate_green >= 12 and ml == "FULL":
        return "PREMIUM"
    if gate_green >= 10 and ml == "FULL":
        return "ALTO"
    if gate_green >= 10 and ml == "HALF":
        return "MEDIO"
    if gate_green >= 10:
        return "CAUTELOSO"
    return "MINIMO"


def _get_model_win_rate(con, model: str) -> float:
    """Win rate histórico del modelo (mínimo 10 trades para ser válido)."""
    row = con.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) as wins
        FROM predictions
        WHERE model=? AND outcome IN ('WIN','LOSS')
    """, (model,)).fetchone()

    if row and row["total"] >= 10:
        return row["wins"] / row["total"]
    return 0.45  # neutral si pocos datos


def _get_current_exposure(con, portfolio: float) -> float:
    """Capital actualmente expuesto en posiciones abiertas."""
    row = con.execute("""
        SELECT COALESCE(SUM(position_usd), 0) as total
        FROM predictions
        WHERE outcome='PENDING' AND position_usd > 0
    """).fetchone()
    return float(row["total"]) if row else 0.0


def _get_ml_decision_for_pred(pred_id: int) -> str:
    """Lee la decisión ML desde ml_decisions.db para el pred dado."""
    try:
        ml_db = os.path.join(os.path.dirname(os.path.dirname(__file__)), "state", "ml_decisions.db")
        con = sqlite3.connect(ml_db)
        row = con.execute(
            "SELECT ml_decision FROM ml_decisions WHERE opened_pred_id=?",
            (pred_id,)
        ).fetchone()
        con.close()
        return row[0] if row and row[0] else "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def asignar_capital(con, pred_ids: list, portfolio: float = None) -> list:
    """
    Asigna capital a predicciones nuevas respetando:
      - Tier de confianza (gate + ML)
      - Cap total 50% del capital
      - Máximo 5 posiciones simultáneas
      - Ajuste por drawdown y WR histórico
    """
    if not pred_ids:
        return []

    # Garantizar acceso por nombre de columna
    con.row_factory = sqlite3.Row

    # Capital base
    profile = get_profile()
    portfolio = portfolio or profile.get("balance", 0) or float(os.environ.get("CRYPTO_PORTFOLIO", "1000"))

    # ── Veto por risk_guard ───────────────────────────────────────────────
    try:
        from bot.risk_guard import is_tripped, trip_reason
        if is_tripped():
            for pid in pred_ids:
                con.execute("UPDATE predictions SET quantity=0, position_usd=0, risk_usd=0 WHERE id=?", (pid,))
            con.commit()
            return [{"id": pid, "position_usd": 0, "quantity": 0, "risk_usd": 0,
                     "skipped": True, "skip_reason": f"RISK_GUARD: {trip_reason()}"} for pid in pred_ids]
    except Exception:
        pass

    # ── Veto por sesión ───────────────────────────────────────────────────
    try:
        from bot.session_manager import SessionManager
        sm = SessionManager.current()
        if sm is not None and not sm.can_open_new_trades():
            for pid in pred_ids:
                con.execute("UPDATE predictions SET quantity=0, position_usd=0, risk_usd=0 WHERE id=?", (pid,))
            con.commit()
            return [{"id": pid, "position_usd": 0, "quantity": 0, "risk_usd": 0,
                     "skipped": True, "skip_reason": f"SESSION_{sm.state()}"} for pid in pred_ids]
    except Exception:
        pass

    # ── Multiplicador por drawdown ────────────────────────────────────────
    dd_mult = 1.0
    try:
        from bot.risk_guard import _load_state as _risk_state
        dd = (_risk_state().get("current_dd_pct") or 0.0)
        if dd >= 10.0:
            dd_mult = 0.50
        elif dd >= 5.0:
            dd_mult = 0.70
    except Exception:
        pass

    # ── Exposición actual ─────────────────────────────────────────────────
    current_exposure = _get_current_exposure(con, portfolio)
    max_exposure_usd = portfolio * MAX_EXPOSURE_PCT   # $500 con $1000
    available_usd    = max(0.0, max_exposure_usd - current_exposure)

    # ── Contar posiciones abiertas ────────────────────────────────────────
    open_count = con.execute(
        "SELECT COUNT(*) FROM predictions WHERE outcome='PENDING' AND position_usd > 0"
    ).fetchone()[0]

    # ── Obtener predicciones ──────────────────────────────────────────────
    placeholders = ",".join("?" * len(pred_ids))
    preds = con.execute(
        f"SELECT * FROM predictions WHERE id IN ({placeholders})", pred_ids
    ).fetchall()

    results = []

    for p in preds:
        pid    = p["id"]
        price  = p["price_at_pred"]
        stop   = p["stop_price"]
        model  = p["model"] or "D"
        gate   = p["gate_score"] or 0

        # Verificar cupo de posiciones simultáneas
        if open_count >= MAX_TRADES:
            con.execute("UPDATE predictions SET quantity=0, position_usd=0, risk_usd=0 WHERE id=?", (pid,))
            results.append({"id": pid, "position_usd": 0, "quantity": 0, "risk_usd": 0,
                             "skipped": True, "skip_reason": f"MAX_TRADES_{MAX_TRADES}"})
            continue

        # Leer ML decision
        ml_dec = _get_ml_decision_for_pred(pid)

        # Determinar tier
        tier     = _get_tier(gate, ml_dec)
        base_pct = TIERS[tier]

        # Ajuste por WR histórico del modelo
        wr = _get_model_win_rate(con, model)
        if wr > 0.60:
            wr_mult = 1.20
        elif wr < 0.40:
            wr_mult = 0.80
        else:
            wr_mult = 1.00

        # Posición en USD
        pos_usd = portfolio * base_pct * wr_mult * dd_mult

        # No exceder capital disponible (cap 50%)
        pos_usd = min(pos_usd, available_usd)

        # Límite mínimo
        if pos_usd < MIN_POSITION_USD:
            con.execute("UPDATE predictions SET quantity=0, position_usd=0, risk_usd=0 WHERE id=?", (pid,))
            results.append({"id": pid, "position_usd": 0, "quantity": 0, "risk_usd": 0,
                             "skipped": True, "skip_reason": "BELOW_MIN_POSITION"})
            continue

        if not price or price <= 0:
            results.append({"id": pid, "position_usd": 0, "quantity": 0, "risk_usd": 0})
            continue

        quantity     = pos_usd / price
        stop_dist    = abs(price - stop) if stop else price * 0.02
        stop_dist    = max(stop_dist, price * 0.001)
        risk_usd     = quantity * stop_dist
        risk_pct     = risk_usd / portfolio * 100

        con.execute("""
            UPDATE predictions SET quantity=?, position_usd=?, risk_usd=? WHERE id=?
        """, (round(quantity, 8), round(pos_usd, 2), round(risk_usd, 2), pid))

        available_usd -= pos_usd
        open_count    += 1

        results.append({
            "id":                pid,
            "model":             model,
            "gate":              gate,
            "ml_decision":       ml_dec,
            "tier":              tier,
            "wr":                round(wr * 100, 1),
            "position_usd":      round(pos_usd, 2),
            "quantity":          round(quantity, 8),
            "risk_usd":          round(risk_usd, 2),
            "risk_pct_portfolio": round(risk_pct, 2),
        })

    con.commit()
    return results


def calculate_position(entry_price: float, stop_price: float,
                       portfolio: float = None, **kwargs) -> dict:
    """Fallback individual (5% fijo)."""
    portfolio = portfolio or float(os.environ.get("CRYPTO_PORTFOLIO", "1000"))
    pos_usd  = portfolio * 0.05
    if not entry_price or entry_price <= 0:
        return {"quantity": 0, "position_usd": 0, "risk_usd": 0, "risk_pct_portfolio": 0}
    quantity     = pos_usd / entry_price
    stop_dist    = abs(entry_price - stop_price) if stop_price else entry_price * 0.02
    risk_usd     = quantity * stop_dist
    return {
        "quantity":           round(quantity, 8),
        "position_usd":       round(pos_usd, 2),
        "risk_usd":           round(risk_usd, 2),
        "risk_pct_portfolio": round(risk_usd / portfolio * 100, 2),
    }


def format_quantity(quantity: float, price: float) -> str:
    if price >= 1000:  return f"{quantity:.6f}"
    elif price >= 1:   return f"{quantity:.2f}"
    elif price >= 0.01: return f"{quantity:.0f}"
    else:              return f"{quantity:,.0f}"


def format_usd(amount: float) -> str:
    if abs(amount) >= 1000: return f"${amount:,.0f}"
    elif abs(amount) >= 1:  return f"${amount:,.2f}"
    else:                   return f"${amount:.4f}"
