"""
Macro Events Watcher — conecta global_events_2026.py al pipeline en vivo.

Funciones principales:
  upcoming_event(symbol, hours_ahead=4) -> dict | None
      Retorna el evento mas inminente que afecta al simbolo dentro de la ventana
      especificada (por defecto 4h). None si no hay evento relevante.

  is_blackout(symbol, hours_ahead=4) -> bool
      True si hay evento HIGH/CRITICAL en la ventana → bot debe evitar entrar.

  factor_color(symbol) -> tuple[str, str]
      Devuelve (color GREEN/YELLOW/RED, descripcion) para usar como factor M4
      del gate.

Implementacion: parsea date+time del calendario y compara con datetime.utcnow.
El calendario en global_events_2026.py usa horas EST (UTC-5). Convertimos a UTC.
"""
import os, sys
from datetime import datetime, timedelta, timezone
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

try:
    from model_d_training.global_events_2026 import (
        GLOBAL_EVENTS_2026, POTENTIAL_CRISIS_EVENTS,
    )
    _CALENDAR = GLOBAL_EVENTS_2026 + POTENTIAL_CRISIS_EVENTS
except Exception:
    _CALENDAR = []


# Tiempo EST (UTC-5) usado por el calendario; ignoramos DST por simplicidad
# (margen de 1h se compensa con la ventana de 4h por defecto).
EST_OFFSET = timedelta(hours=-5)

# Solo eventos con estos niveles activan veto
BLOCKING_IMPACTS = {"HIGH", "CRITICAL"}


def _parse_event_dt(event: dict) -> Optional[datetime]:
    """Convierte el (date, time) del evento a datetime UTC."""
    try:
        date_str = event.get("date", "")
        time_str = event.get("time", "00:00")
        local_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        # El calendario esta en EST → convertir a UTC restando EST_OFFSET
        utc_dt = local_dt - EST_OFFSET  # local = utc + offset; utc = local - offset
        return utc_dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _symbol_to_base(symbol: str) -> str:
    """BTCUSDT -> BTC, ETHUSDT -> ETH."""
    if symbol.endswith("USDT"):
        return symbol[:-4]
    return symbol


def _affects_symbol(event: dict, symbol: str) -> bool:
    """True si el evento lista al simbolo en affected_pairs (o no lo limita)."""
    base = _symbol_to_base(symbol)
    affected = event.get("affected_pairs", [])
    if not affected:
        return True
    return base in affected or symbol in affected


def upcoming_event(symbol: str, hours_ahead: float = 4.0) -> Optional[dict]:
    """
    Devuelve el evento mas cercano (en tiempo) que afecta a `symbol`
    dentro de los proximos `hours_ahead`. None si ninguno aplica.
    """
    if not _CALENDAR:
        return None
    now = datetime.now(timezone.utc)
    window_end = now + timedelta(hours=hours_ahead)

    candidates = []
    for ev in _CALENDAR:
        if ev.get("impact") not in BLOCKING_IMPACTS:
            continue
        if not _affects_symbol(ev, symbol):
            continue
        dt = _parse_event_dt(ev)
        if dt is None:
            continue
        if now <= dt <= window_end:
            candidates.append((dt, ev))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    dt, ev = candidates[0]
    return {
        **ev,
        "utc_datetime": dt.isoformat(),
        "hours_until": round((dt - now).total_seconds() / 3600, 2),
    }


def is_blackout(symbol: str, hours_ahead: float = 4.0) -> bool:
    """True si hay evento HIGH/CRITICAL en proximas N horas."""
    return upcoming_event(symbol, hours_ahead) is not None


def is_global_blackout(hours_ahead: float = 4.0) -> Optional[dict]:
    """
    True si hay evento CRITICAL global (FOMC, CPI, elecciones, etc.) que afecte
    al mercado entero, independiente del simbolo.
    Devuelve el evento o None.
    """
    if not _CALENDAR:
        return None
    now = datetime.now(timezone.utc)
    window_end = now + timedelta(hours=hours_ahead)
    candidates = []
    for ev in _CALENDAR:
        if ev.get("impact") != "CRITICAL":
            continue
        # eventos globales: tocan BTC o ETH (proxies del mercado entero)
        affected = ev.get("affected_pairs", [])
        if "BTC" not in affected and "ETH" not in affected:
            continue
        dt = _parse_event_dt(ev)
        if dt is None:
            continue
        if now <= dt <= window_end:
            candidates.append((dt, ev))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    dt, ev = candidates[0]
    return {
        **ev,
        "utc_datetime": dt.isoformat(),
        "hours_until": round((dt - now).total_seconds() / 3600, 2),
    }


def factor_color(symbol: str, hours_ahead: float = 4.0) -> tuple:
    """
    Genera (color, reason) para usar como factor M4 del gate.
      RED    -> CRITICAL en <= 2h o HIGH en <=1h
      YELLOW -> HIGH en 1-4h
      GREEN  -> nada relevante
    """
    ev = upcoming_event(symbol, hours_ahead)
    if ev is None:
        return ("GREEN", "Sin eventos macro proximos")

    impact = ev.get("impact", "")
    h = ev.get("hours_until", 99.0)
    name = ev.get("event", "evento")

    if impact == "CRITICAL" and h <= 2.0:
        return ("RED", f"{name} en {h:.1f}h ({impact})")
    if impact == "HIGH" and h <= 1.0:
        return ("RED", f"{name} en {h:.1f}h ({impact})")
    if impact in BLOCKING_IMPACTS:
        return ("YELLOW", f"{name} en {h:.1f}h ({impact})")

    return ("GREEN", f"Solo MEDIUM/{impact} a {h:.1f}h")


def get_active_regime_modifier() -> str:
    """
    Modificador de regimen global por proximidad a eventos criticos.
    Devuelve uno de:
      'NORMAL'  -> nada inusual
      'CAUTION' -> evento CRITICAL en proximas 6h
      'BLACKOUT'-> evento CRITICAL en proxima 1h (no abrir nada)
    """
    crit = is_global_blackout(hours_ahead=6.0)
    if not crit:
        return "NORMAL"
    h = crit.get("hours_until", 99)
    if h <= 1.0:
        return "BLACKOUT"
    return "CAUTION"


if __name__ == "__main__":
    print(f"Calendario cargado: {len(_CALENDAR)} eventos")
    for sym in ["BTCUSDT", "ETHUSDT", "DOGEUSDT"]:
        ev = upcoming_event(sym, 168)  # proxima semana
        color, reason = factor_color(sym)
        print(f"  {sym}: factor M4 = {color} ({reason})")
        if ev:
            print(f"     Proximo evento: {ev['event']} en {ev['hours_until']:.1f}h")
