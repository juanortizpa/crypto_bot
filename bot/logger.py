"""Simple timestamped logger — writes to console and logs/crypto_bot.log"""
import os
from datetime import datetime

LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "crypto_bot.log")

def log(level, msg):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level:<5}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")
