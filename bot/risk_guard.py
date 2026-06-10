"""
Risk Guard — protecciones a nivel portfolio para el cap de $1000.

Detecta y bloquea operativa si:
  * Drawdown total acumulado supera 15% (default).
  * Perdida del dia supera 4% (default).
  * Numero de losses consecutivos >= 4.

Persiste estado en state/risk_guard.json para sobrevivir reinicios dentro
de la misma sesion / cuenta.
"""
import os
import json
from datetime import datetime, date
from typing import Optional

# Limites configurables por env
INITIAL_CAPITAL = float(os.environ.get("CRYPTO_INITIAL_CAPITAL",
                        os.environ.get("CRYPTO_PORTFOLIO", "1000")))
MAX_DRAWDOWN_PCT = float(os.environ.get("CRYPTO_MAX_DD_PCT", "15.0"))
MAX_DAILY_LOSS_PCT = float(os.environ.get("CRYPTO_MAX_DAILY_LOSS_PCT", "4.0"))
MAX_CONSEC_LOSSES = int(os.environ.get("CRYPTO_MAX_CONSEC_LOSSES", "4"))

STATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "state")
STATE_FILE = os.path.join(STATE_DIR, "risk_guard.json")


def _load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {
            "initial_capital": INITIAL_CAPITAL,
            "high_water_mark": INITIAL_CAPITAL,
            "consec_losses": 0,
            "daily": {},        # YYYY-MM-DD -> {start_balance, loss_pct}
            "tripped": False,
            "trip_reason": None,
            "trip_at": None,
        }
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "initial_capital": INITIAL_CAPITAL,
            "high_water_mark": INITIAL_CAPITAL,
            "consec_losses": 0,
            "daily": {},
            "tripped": False,
            "trip_reason": None,
            "trip_at": None,
        }


def _save_state(state: dict):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def _today_key() -> str:
    return date.today().isoformat()


def init_session(current_balance: Optional[float] = None):
    """
    Llamar al inicio de cada sesion del bot.
    Si es el primer arranque ever, fija initial_capital.
    Si ya existia, refresca high_water_mark si subio.
    Tambien inicializa el contador diario.
    """
    state = _load_state()
    if current_balance is None:
        current_balance = state.get("initial_capital", INITIAL_CAPITAL)

    # Primera vez
    if not state.get("daily"):
        state["initial_capital"] = current_balance
        state["high_water_mark"] = current_balance

    # Refrescar HWM
    if current_balance > state.get("high_water_mark", 0):
        state["high_water_mark"] = current_balance

    # Snapshot del balance al inicio del dia
    key = _today_key()
    if key not in state.get("daily", {}):
        state.setdefault("daily", {})[key] = {
            "start_balance": current_balance,
            "min_balance": current_balance,
            "loss_pct": 0.0,
        }

    _save_state(state)
    return state


def update_balance(current_balance: float) -> dict:
    """
    Actualizar al cierre de cada trade (o periodicamente desde el monitor).
    Devuelve el estado actualizado para inspeccion.
    """
    state = _load_state()

    # HWM
    if current_balance > state.get("high_water_mark", current_balance):
        state["high_water_mark"] = current_balance

    # Drawdown global
    hwm = state.get("high_water_mark", current_balance)
    dd_pct = (hwm - current_balance) / hwm * 100 if hwm > 0 else 0.0

    # Tracking diario
    key = _today_key()
    daily = state.setdefault("daily", {}).setdefault(key, {
        "start_balance": current_balance,
        "min_balance": current_balance,
        "loss_pct": 0.0,
    })
    if current_balance < daily.get("min_balance", current_balance):
        daily["min_balance"] = current_balance
    sb = daily.get("start_balance", current_balance)
    daily["loss_pct"] = max(0.0, (sb - current_balance) / sb * 100 if sb > 0 else 0.0)

    state["current_balance"] = current_balance
    state["current_dd_pct"] = round(dd_pct, 3)

    # Verificar disparos
    if dd_pct >= MAX_DRAWDOWN_PCT:
        state["tripped"] = True
        state["trip_reason"] = f"DRAWDOWN_{dd_pct:.2f}%"
        state["trip_at"] = datetime.now().isoformat()
    elif daily["loss_pct"] >= MAX_DAILY_LOSS_PCT:
        state["tripped"] = True
        state["trip_reason"] = f"DAILY_LOSS_{daily['loss_pct']:.2f}%"
        state["trip_at"] = datetime.now().isoformat()

    _save_state(state)
    return state


def register_trade_outcome(pnl_pct: float):
    """
    Registra el resultado de un trade cerrado para tracking de losses consecutivas.
    Un resultado de 0.0 (breakeven o MANUAL_RESET) no cuenta como loss.
    Solo dispara TRIPPED si el balance global tambien esta en drawdown real.
    """
    state = _load_state()

    if pnl_pct < -0.1:
        # Perdida real (mayor a 0.1% para ignorar slippage minimo)
        state["consec_losses"] = state.get("consec_losses", 0) + 1
        if state["consec_losses"] >= MAX_CONSEC_LOSSES:
            # Solo tripar si el drawdown real lo justifica
            current_bal = state.get("current_balance", 0)
            hwm = state.get("high_water_mark", current_bal)
            real_dd = (hwm - current_bal) / hwm * 100 if hwm > 0 else 0.0
            if real_dd >= 2.0:  # Solo si hay drawdown real de al menos 2%
                state["tripped"] = True
                state["trip_reason"] = f"CONSEC_LOSSES_{state['consec_losses']}"
                state["trip_at"] = datetime.now().isoformat()
    else:
        # Win o breakeven: resetear contador
        state["consec_losses"] = 0

    _save_state(state)
    return state


def is_tripped() -> bool:
    state = _load_state()
    return bool(state.get("tripped", False))


def trip_reason() -> Optional[str]:
    state = _load_state()
    return state.get("trip_reason") if state.get("tripped") else None


def reset(force: bool = False):
    """
    Resetea los disparos. Solo usar con consentimiento del operador.
    Si force=False, no resetea si current_dd_pct > MAX_DRAWDOWN_PCT.
    """
    state = _load_state()
    if not force and state.get("current_dd_pct", 0) >= MAX_DRAWDOWN_PCT:
        return False
    state["tripped"] = False
    state["trip_reason"] = None
    state["trip_at"] = None
    state["consec_losses"] = 0
    _save_state(state)
    return True


def report() -> str:
    state = _load_state()
    daily = state.get("daily", {}).get(_today_key(), {})
    return (
        f"\n  ==================================================\n"
        f"  RISK GUARD\n"
        f"  ==================================================\n"
        f"  Capital inicial:    ${state.get('initial_capital', 0):.2f}\n"
        f"  Balance actual:     ${state.get('current_balance', state.get('initial_capital', 0)):.2f}\n"
        f"  High-Water Mark:    ${state.get('high_water_mark', 0):.2f}\n"
        f"  Drawdown actual:    {state.get('current_dd_pct', 0):.2f}% / max {MAX_DRAWDOWN_PCT}%\n"
        f"  Perdida hoy:        {daily.get('loss_pct', 0):.2f}% / max {MAX_DAILY_LOSS_PCT}%\n"
        f"  Losses seguidas:    {state.get('consec_losses', 0)} / max {MAX_CONSEC_LOSSES}\n"
        f"  TRIPPED:            {state.get('tripped', False)}"
        + (f"  -> {state.get('trip_reason')}" if state.get('tripped') else "")
        + "\n  ==================================================\n"
    )
