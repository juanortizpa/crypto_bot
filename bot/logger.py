"""Simple timestamped logger — writes to console and logs/crypto_bot.log

Con rotación por tamaño para operación 24/7: cuando el log supera
CRYPTO_LOG_MAX_MB (default 10MB) se rota a crypto_bot.log.1 ... .5
y se empieza uno nuevo. Sin esto, un mes corriendo llena el disco.
"""
import os
from datetime import datetime

LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "crypto_bot.log")
MAX_BYTES = int(float(os.environ.get("CRYPTO_LOG_MAX_MB", "10")) * 1024 * 1024)
KEEP_ROTATED = int(os.environ.get("CRYPTO_LOG_KEEP", "5"))


def _rotate_if_needed():
    try:
        if not os.path.exists(LOG_FILE) or os.path.getsize(LOG_FILE) < MAX_BYTES:
            return
        # crypto_bot.log.4 -> .5, .3 -> .4, ..., .log -> .1
        oldest = f"{LOG_FILE}.{KEEP_ROTATED}"
        if os.path.exists(oldest):
            os.remove(oldest)
        for i in range(KEEP_ROTATED - 1, 0, -1):
            src = f"{LOG_FILE}.{i}"
            if os.path.exists(src):
                os.replace(src, f"{LOG_FILE}.{i+1}")
        os.replace(LOG_FILE, f"{LOG_FILE}.1")
    except Exception:
        pass  # nunca tumbar el bot por un problema de rotacion


def log(level, msg):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    _rotate_if_needed()
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level:<5}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass  # disco lleno / archivo bloqueado: no matar el proceso por loguear
