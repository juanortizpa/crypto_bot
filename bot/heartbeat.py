"""
Heartbeat — latido del bot para vigilancia externa en operación 24/7.

El runner (y el orquestador forever) escriben state/heartbeat.json en cada
ciclo. Cualquier proceso externo (o `python bot_crypto.py health`) puede
verificar que el bot sigue vivo: si el latido tiene más de
CRYPTO_HEARTBEAT_STALE_MIN minutos (default 5), algo está colgado.
"""
import os
import json
from datetime import datetime

HEARTBEAT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "state", "heartbeat.json")
STALE_MINUTES = float(os.environ.get("CRYPTO_HEARTBEAT_STALE_MIN", "5"))


def beat(phase: str, **extra):
    """Escribe el latido. Nunca lanza excepción (no tumbar el bot por esto)."""
    try:
        os.makedirs(os.path.dirname(HEARTBEAT_PATH), exist_ok=True)
        payload = {"ts": datetime.now().isoformat(), "phase": phase}
        payload.update(extra)
        tmp = HEARTBEAT_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, HEARTBEAT_PATH)
    except Exception:
        pass


def status() -> dict:
    """Lee el último latido y calcula si está fresco."""
    try:
        with open(HEARTBEAT_PATH, encoding="utf-8") as f:
            hb = json.load(f)
        age_min = (datetime.now() - datetime.fromisoformat(hb["ts"])).total_seconds() / 60.0
        hb["age_minutes"] = round(age_min, 1)
        hb["stale"] = age_min > STALE_MINUTES
        return hb
    except FileNotFoundError:
        return {"ts": None, "phase": "NONE", "age_minutes": None, "stale": True}
    except Exception as e:
        return {"ts": None, "phase": f"ERROR:{type(e).__name__}", "age_minutes": None, "stale": True}
