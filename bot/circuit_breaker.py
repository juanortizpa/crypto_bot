"""
Circuit Breaker — frena la generacion de nuevas entradas cuando el sistema
esta perdiendo de forma sostenida.

Razon: cuando el regimen de mercado cambia, un bot long-only pierde en serie
(todos los modelos compran lo mismo). Sin freno, sigue abriendo trades en un
mercado que lo esta castigando. Esto es lo que paso cuando "no paraba de
perder": no habia ningun mecanismo que dijera BASTA.

Reglas (configurables por env):
  1. PnL acumulado de trades cerrados en las ultimas LOOKBACK_H horas
     <= MAX_ROLLING_LOSS_PCT  ->  bloquear COOLDOWN_H horas
  2. MAX_CONSEC_LOSSES perdidas consecutivas -> bloquear COOLDOWN_H horas

El bloqueo aplica SOLO a entradas nuevas. Los trades abiertos se siguen
monitoreando y cerrando con normalidad.
"""
import os, sys, sqlite3
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from bot.logger import log

DB_PATH = os.environ.get(
    "CRYPTO_DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "state", "crypto_predictions.db"),
)

LOOKBACK_H           = float(os.environ.get("CB_LOOKBACK_H", "24"))
MAX_ROLLING_LOSS_PCT = float(os.environ.get("CB_MAX_ROLLING_LOSS_PCT", "-5.0"))
MAX_CONSEC_LOSSES    = int(os.environ.get("CB_MAX_CONSEC_LOSSES", "4"))
COOLDOWN_H           = float(os.environ.get("CB_COOLDOWN_H", "12"))


def _closed_recent(con, hours):
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
    return con.execute("""
        SELECT outcome, pnl_pct, outcome_date FROM predictions
        WHERE outcome IN ('WIN','LOSS') AND outcome_date >= ?
        ORDER BY outcome_date ASC
    """, (cutoff,)).fetchall()


def check_circuit_breaker():
    """
    Retorna (blocked: bool, reason: str).
    Falla en abierto (no bloquea) si la BD no esta disponible.
    """
    try:
        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row

        # Regla 1: perdida acumulada rodante
        rows = _closed_recent(con, LOOKBACK_H)
        rolling = sum(r["pnl_pct"] or 0 for r in rows)
        if rows and rolling <= MAX_ROLLING_LOSS_PCT:
            last_close = rows[-1]["outcome_date"]
            unblock_at = datetime.fromisoformat(last_close) + timedelta(hours=COOLDOWN_H)
            if datetime.now() < unblock_at:
                con.close()
                reason = (f"PnL {rolling:+.1f}% en {LOOKBACK_H:.0f}h "
                          f"(limite {MAX_ROLLING_LOSS_PCT}%) — pausa hasta "
                          f"{unblock_at.strftime('%H:%M')}")
                return True, reason

        # Regla 2: racha de perdidas consecutivas (mirando mas atras, 72h)
        rows72 = _closed_recent(con, 72)
        streak = 0
        for r in reversed(rows72):
            if r["outcome"] == "LOSS":
                streak += 1
            else:
                break
        con.close()
        if streak >= MAX_CONSEC_LOSSES:
            last_close = rows72[-1]["outcome_date"]
            unblock_at = datetime.fromisoformat(last_close) + timedelta(hours=COOLDOWN_H)
            if datetime.now() < unblock_at:
                reason = (f"{streak} LOSS consecutivos — pausa hasta "
                          f"{unblock_at.strftime('%H:%M')}")
                return True, reason

        return False, "OK"

    except Exception as e:
        log("WARN", f"circuit_breaker: {e}")
        return False, f"check error: {type(e).__name__}"
