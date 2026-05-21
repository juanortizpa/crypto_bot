"""
Position Sizing Dinamico — asigna capital DESPUES de generar predicciones.

FLUJO:
  1. generar_predicciones() crea trades sin sizing (qty=NULL)
  2. asignar_capital() reparte $10,000 entre todas las predicciones nuevas
  3. Cada trade recibe capital proporcional a su confianza

CONFIANZA = f(gate_score, model_win_rate)
  - gate_score alto  → mas capital (el mercado esta a favor)
  - model con mejor WR historico → mas capital
  - Normalizado para que la suma no exceda el portfolio

EJEMPLO con $10,000 y 20 predicciones:
  - Base uniforme: $500 cada una
  - Pred con gate=9 y modelo WR=40%: confianza alta → $700
  - Pred con gate=4 y modelo WR=15%: confianza baja → $300
  - Total sigue siendo <= $10,000
"""

import os
import sqlite3
from datetime import datetime
from bot.capital_profile import get_profile

PORTFOLIO_USD = float(os.environ.get("CRYPTO_PORTFOLIO", "10000"))
# Limites por trade (seguridad) — pueden ser overrideados por el perfil
MIN_POSITION_USD = float(os.environ.get("CRYPTO_MIN_POS", "5"))     # min Binance = $5
MAX_POSITION_PCT = float(os.environ.get("CRYPTO_MAX_POS_PCT", "0.10"))  # max 10% del portfolio
# Hard cap absoluto (para capital pequeno tipo $500)
HARD_CAP_USD = float(os.environ.get("CRYPTO_HARD_CAP_USD", "50"))   # max $50 por trade
# Activar hard cap automaticamente si capital <= este umbral
SMALL_CAPITAL_THRESHOLD = float(os.environ.get("CRYPTO_SMALL_CAP_THRESHOLD", "1000"))


def _get_model_win_rates(con) -> dict:
    """
    Calcula win rate historico por modelo desde la DB.
    Retorna dict {model_id: win_rate_float} (0.0 a 1.0).
    Modelos sin historial reciben WR neutral de 0.25.
    """
    rows = con.execute("""
        SELECT model, outcome, COUNT(*) as cnt
        FROM predictions
        WHERE outcome IN ('WIN', 'LOSS')
        GROUP BY model, outcome
    """).fetchall()

    stats = {}
    for r in rows:
        m = r["model"] or "A"
        if m not in stats:
            stats[m] = {"wins": 0, "total": 0}
        stats[m]["total"] += r["cnt"]
        if r["outcome"] == "WIN":
            stats[m]["wins"] += r["cnt"]

    result = {}
    for m, s in stats.items():
        if s["total"] >= 5:  # minimo 5 trades para ser significativo
            result[m] = s["wins"] / s["total"]
        else:
            result[m] = 0.25  # neutral si pocos datos
    return result


def _confidence_score(gate_score: int, model_wr: float) -> float:
    """
    Score de confianza 0.3 - 2.0 basado en gate y WR del modelo.

    gate_score (0-13):
      - 3-4: factor 0.6
      - 5-6: factor 0.8
      - 7-8: factor 1.0
      - 9+:  factor 1.3

    model_wr (0.0-1.0):
      - <15%:  factor 0.5
      - 15-25%: factor 0.8
      - 25-35%: factor 1.0
      - 35-50%: factor 1.3
      - >50%:  factor 1.5

    Score final = gate_factor * wr_factor
    """
    # Factor por gate score
    if gate_score >= 9:
        gate_f = 1.3
    elif gate_score >= 7:
        gate_f = 1.0
    elif gate_score >= 5:
        gate_f = 0.8
    else:
        gate_f = 0.6

    # Factor por win rate historico
    if model_wr > 0.50:
        wr_f = 1.5
    elif model_wr > 0.35:
        wr_f = 1.3
    elif model_wr > 0.25:
        wr_f = 1.0
    elif model_wr > 0.15:
        wr_f = 0.8
    else:
        wr_f = 0.5

    return round(gate_f * wr_f, 2)


def asignar_capital(con, pred_ids: list, portfolio: float = None) -> list:
    """
    Asigna capital a un lote de predicciones basado en confianza.
    Respeta el perfil de capital activo (SURVIVAL/GROWTH/STANDARD).

    Pasos:
      1. Calcula WR por modelo (historico)
      2. Para cada pred: confidence = f(gate_score, model_wr)
      3. Base por trade = portfolio / num_preds (o fijo si perfil lo indica)
      4. Ajusta base * confidence
      5. Normaliza para que total <= portfolio
      6. Aplica limites min/max por trade
      7. Actualiza DB con quantity, position_usd, risk_usd

    Retorna lista de dicts con sizing asignado.
    """
    profile = get_profile()
    portfolio = portfolio or profile.get("balance", 0) or PORTFOLIO_USD
    max_pct = profile.get("max_portfolio_pct", MAX_POSITION_PCT)
    max_per_trade = portfolio * max_pct
    fixed_position = profile.get("position_usd")  # None = dinamico
    max_trades = profile.get("max_trades", 10)

    # Hard cap absoluto para cuentas pequenas ($500)
    use_hard_cap = portfolio <= SMALL_CAPITAL_THRESHOLD
    if use_hard_cap:
        # Aplicar el menor entre % cap y hard cap absoluto
        max_per_trade = min(max_per_trade, HARD_CAP_USD)

    # Risk guard a nivel portfolio
    try:
        from bot.risk_guard import is_tripped, trip_reason
        if is_tripped():
            # Bot pausado por DD/daily/consec losses → 0 capital asignado
            for pid in pred_ids:
                con.execute(
                    "UPDATE predictions SET quantity=0, position_usd=0, risk_usd=0 WHERE id=?",
                    (pid,),
                )
            con.commit()
            return [{"id": pid, "position_usd": 0, "quantity": 0,
                     "risk_usd": 0, "skipped": True,
                     "skip_reason": f"RISK_GUARD_TRIPPED: {trip_reason()}"}
                    for pid in pred_ids]
    except Exception:
        pass

    # Veto por sesion 12h: si no podemos abrir nuevas entradas, asignar 0
    try:
        from bot.session_manager import SessionManager
        sm = SessionManager.current()
        if sm is not None and not sm.can_open_new_trades():
            for pid in pred_ids:
                con.execute(
                    "UPDATE predictions SET quantity=0, position_usd=0, risk_usd=0 WHERE id=?",
                    (pid,),
                )
            con.commit()
            return [{"id": pid, "position_usd": 0, "quantity": 0,
                     "risk_usd": 0, "skipped": True,
                     "skip_reason": f"SESSION_STATE_{sm.state()}"}
                    for pid in pred_ids]
    except Exception:
        pass

    if not pred_ids:
        return []

    # Obtener predicciones
    placeholders = ",".join("?" * len(pred_ids))
    preds = con.execute(
        f"SELECT * FROM predictions WHERE id IN ({placeholders})",
        pred_ids,
    ).fetchall()

    if not preds:
        return []

    # Win rates historicos
    model_wrs = _get_model_win_rates(con)

    # Calcular confianza por prediccion
    scores = []
    for p in preds:
        gate = p["gate_score"] or 4
        model = p["model"] or "A"
        wr = model_wrs.get(model, 0.25)
        conf = _confidence_score(gate, wr)
        scores.append({
            "id":         p["id"],
            "price":      p["price_at_pred"],
            "stop":       p["stop_price"],
            "model":      model,
            "gate":       gate,
            "wr":         wr,
            "confidence": conf,
        })

    # Limitar a max_trades del perfil (los de mayor confianza primero)
    if len(scores) > max_trades:
        scores.sort(key=lambda s: s["confidence"], reverse=True)
        scores = scores[:max_trades]

    # Distribuir capital proporcionalmente a confianza
    total_conf = sum(s["confidence"] for s in scores)
    if total_conf <= 0:
        total_conf = len(scores)  # fallback uniforme

    results = []
    total_assigned = 0

    # Ajuste por drawdown actual (mas DD -> sizing reducido)
    dd_mult = 1.0
    try:
        from bot.risk_guard import _load_state as _risk_state
        rs = _risk_state()
        dd = rs.get("current_dd_pct", 0.0) or 0.0
        if dd >= 10.0:
            dd_mult = 0.5
        elif dd >= 5.0:
            dd_mult = 0.7
        # <5% DD -> 1.0
    except Exception:
        pass

    for s in scores:
        # Posicion fija (SURVIVAL/GROWTH) o proporcional (STANDARD)
        if fixed_position:
            pos_usd = fixed_position
        else:
            share = s["confidence"] / total_conf
            pos_usd = portfolio * share

        # Aplicar reduccion por drawdown
        pos_usd = pos_usd * dd_mult

        # Limites
        pos_usd = max(pos_usd, MIN_POSITION_USD)
        pos_usd = min(pos_usd, max_per_trade)

        # Si la posicion queda demasiado chica (Binance min + comisiones inviables)
        # → marcar como skipped en lugar de comprar algo poco rentable
        # Con $500: mantener un piso de $10 para que el round-trip de 0.20% no domine
        if portfolio <= SMALL_CAPITAL_THRESHOLD and pos_usd < 10.0:
            pos_usd = 0  # skip

        price = s["price"]
        stop = s["stop"]

        if not price or price <= 0:
            results.append({"id": s["id"], "position_usd": 0, "quantity": 0, "risk_usd": 0})
            continue

        quantity = pos_usd / price

        stop_distance = abs(price - stop) if stop else price * 0.02
        if stop_distance <= 0:
            stop_distance = price * 0.02

        risk_usd = quantity * stop_distance
        risk_pct = risk_usd / portfolio * 100

        # Actualizar DB
        con.execute("""
            UPDATE predictions
            SET quantity = ?, position_usd = ?, risk_usd = ?
            WHERE id = ?
        """, (round(quantity, 8), round(pos_usd, 2), round(risk_usd, 2), s["id"]))

        total_assigned += pos_usd
        results.append({
            "id":               s["id"],
            "model":            s["model"],
            "gate":             s["gate"],
            "wr":               round(s["wr"] * 100, 1),
            "confidence":       s["confidence"],
            "position_usd":     round(pos_usd, 2),
            "quantity":         round(quantity, 8),
            "risk_usd":         round(risk_usd, 2),
            "risk_pct_portfolio": round(risk_pct, 2),
        })

    con.commit()

    return results


def calculate_position(entry_price: float, stop_price: float,
                       portfolio: float = None, **kwargs) -> dict:
    """
    Calculo de posicion individual (usado como fallback).
    Para el flujo normal, usar asignar_capital() despues de generar todas las preds.
    """
    portfolio = portfolio or PORTFOLIO_USD
    # Fallback: 5% del portfolio por trade si se llama individualmente
    pos_usd = portfolio * 0.05

    if not entry_price or entry_price <= 0:
        return {"quantity": 0, "position_usd": 0, "risk_usd": 0, "risk_pct_portfolio": 0}

    quantity = pos_usd / entry_price

    stop_distance = abs(entry_price - stop_price)
    if stop_distance <= 0:
        stop_distance = entry_price * 0.02

    risk_usd = quantity * stop_distance
    risk_pct = risk_usd / portfolio * 100

    return {
        "quantity":          round(quantity, 8),
        "position_usd":     round(pos_usd, 2),
        "risk_usd":         round(risk_usd, 2),
        "risk_pct_portfolio": round(risk_pct, 2),
    }


def format_quantity(quantity: float, price: float) -> str:
    """Formatea cantidad legible segun el precio del asset."""
    if price >= 1000:
        return f"{quantity:.6f}"
    elif price >= 1:
        return f"{quantity:.2f}"
    elif price >= 0.01:
        return f"{quantity:.0f}"
    else:
        return f"{quantity:,.0f}"


def format_usd(amount: float) -> str:
    """Formatea dolares de forma legible."""
    if abs(amount) >= 1000:
        return f"${amount:,.0f}"
    elif abs(amount) >= 1:
        return f"${amount:,.2f}"
    else:
        return f"${amount:.4f}"


def portfolio_summary(open_positions: list) -> dict:
    """Resumen del portfolio con posiciones abiertas."""
    portfolio = PORTFOLIO_USD
    total_invested = sum(p.get("position_usd", 0) for p in open_positions)
    total_risk     = sum(p.get("risk_usd", 0) for p in open_positions)

    return {
        "portfolio_usd":   portfolio,
        "total_invested":  round(total_invested, 2),
        "total_risk":      round(total_risk, 2),
        "available":       round(portfolio - total_invested, 2),
        "utilization_pct": round(total_invested / portfolio * 100, 1),
        "risk_pct":        round(total_risk / portfolio * 100, 1),
        "open_trades":     len(open_positions),
    }
