"""
Reversal Watchlist - monitoreo continuo de candidatos a reversion.

FLUJO:
  1. analyze_reversal() detecta un par bajando (DECLINING/BOTTOMING).
  2. Si score >= warm_threshold pero < entry_threshold -> WATCH.
  3. Cada nuevo scan: si el par confirma la senal, suma confirmaciones.
  4. Solo cuando se acumulan N confirmaciones consecutivas (default 2),
     el par se considera ENTRY_READY y se emite prediccion.

OBJETIVO:
  Evitar entradas falsas (single-scan flukes). Confirmar que el par
  realmente esta revirtiendo antes de gastar una prediccion.

PERSISTENCIA:
  El estado de la watchlist se guarda en state/reversal_watchlist.json
  para sobrevivir entre runs del bot (cron jobs).
"""
import os, json, time
from datetime import datetime, timezone

_WATCHLIST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "state",
    "reversal_watchlist.json"
)


def _load():
    try:
        with open(_WATCHLIST_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(data):
    os.makedirs(os.path.dirname(_WATCHLIST_PATH), exist_ok=True)
    with open(_WATCHLIST_PATH, "w") as f:
        json.dump(data, f, indent=2)


def update_watchlist(reversal_signals, warm_threshold=3, entry_threshold=4,
                     min_confirmations=2, ttl_hours=24):
    """
    Actualiza la watchlist con los resultados de un scan de reversion.

    reversal_signals: lista de ReversalSignal
    warm_threshold:   score minimo para entrar a watchlist
    entry_threshold:  score minimo para considerar 'caliente'
    min_confirmations: cuantos scans consecutivos con score>=entry para
                       considerar la entrada confirmada
    ttl_hours:        si un par no aparece en X horas se elimina

    Retorna lista de pares que pasaron a ENTRY_READY (listos para predecir).
    """
    wl = _load()
    now = datetime.now(timezone.utc).timestamp()
    confirmed = []

    seen_now = set()
    for sig in reversal_signals:
        sym = sig.symbol
        seen_now.add(sym)
        score = sig.net_score
        rec = wl.get(sym, {
            "first_seen": now,
            "scans": 0,
            "confirmations": 0,
            "max_score": 0,
            "last_score": 0,
            "last_phase": "",
            "status": "WATCH",
        })

        rec["scans"] += 1
        rec["last_seen"] = now
        rec["last_score"] = score
        rec["last_phase"] = sig.phase
        rec["max_score"] = max(rec["max_score"], score)

        if score >= entry_threshold:
            rec["confirmations"] += 1
        else:
            # Reset si pierde fuerza (drop > 1 punto)
            if rec.get("confirmations", 0) > 0 and score < entry_threshold - 1:
                rec["confirmations"] = max(0, rec["confirmations"] - 1)

        # Promociones de estado
        if rec["confirmations"] >= min_confirmations:
            rec["status"] = "ENTRY_READY"
            confirmed.append(sym)
        elif score >= entry_threshold:
            rec["status"] = "HOT"
        elif score >= warm_threshold:
            rec["status"] = "WATCH"
        else:
            rec["status"] = "COOLING"

        wl[sym] = rec

    # Limpiar entradas viejas
    cutoff = now - ttl_hours * 3600
    for sym in list(wl.keys()):
        if wl[sym].get("last_seen", 0) < cutoff:
            del wl[sym]

    _save(wl)
    return confirmed


def get_watchlist():
    """Retorna la watchlist actual."""
    return _load()


def mark_predicted(symbol):
    """Marca un par como ya predicho (resetea confirmaciones)."""
    wl = _load()
    if symbol in wl:
        wl[symbol]["status"] = "PREDICTED"
        wl[symbol]["confirmations"] = 0
        wl[symbol]["predicted_at"] = datetime.now(timezone.utc).timestamp()
        _save(wl)


def print_watchlist_report():
    """Imprime estado actual de la watchlist."""
    wl = _load()
    if not wl:
        print("\n  WATCHLIST: vacia\n")
        return

    sep = "=" * 64
    print(f"\n  {sep}")
    print(f"  REVERSAL WATCHLIST  ({len(wl)} pares en seguimiento)")
    print(f"  {sep}")
    print(f"  {'Par':<12} {'Status':<14} {'Score':<8} {'Conf':<6} {'Phase':<12} Scans")
    print(f"  {'-'*60}")

    items = sorted(wl.items(), key=lambda kv: -kv[1].get("last_score", 0))
    for sym, rec in items:
        status = rec.get("status", "?")
        score = rec.get("last_score", 0)
        conf = rec.get("confirmations", 0)
        phase = rec.get("last_phase", "?")
        scans = rec.get("scans", 0)
        marker = ">>" if status == "ENTRY_READY" else "  "
        print(f"  {marker}{sym:<10} {status:<14} {score:<8} {conf:<6} {phase:<12} {scans}")

    print(f"  {sep}\n")
