"""
wipe_all_data.py — Borra TODOS los datos historicos del bot.

Limpia:
  - predictions (todas)
  - ml_decisions (todas)
  - risk_guard.json (reset a $1000)

Uso:
  python wipe_all_data.py
"""
import os, sqlite3, json

ROOT = os.path.dirname(__file__)
STATE = os.path.join(ROOT, "state")

print("=" * 55)
print("  WIPE ALL DATA — borrado completo de historico")
print("=" * 55)

# ── 1. crypto_predictions.db ──────────────────────────────
PRED_DB = os.path.join(STATE, "crypto_predictions.db")
print(f"\n[1/3] crypto_predictions.db")
try:
    con = sqlite3.connect(PRED_DB, timeout=10)
    n = con.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
    con.execute("DELETE FROM predictions")
    try:
        con.execute("DELETE FROM sqlite_sequence WHERE name='predictions'")
    except Exception:
        pass
    con.commit()
    con.close()
    print(f"  ✓ Borrados {n} registros. Tabla vacia.")
except Exception as e:
    print(f"  ERROR: {e}")
    print("  Asegurate de que el bot NO esta corriendo (Ctrl+C primero).")

# ── 2. ml_decisions.db ───────────────────────────────────
ML_DB = os.path.join(STATE, "ml_decisions.db")
print(f"\n[2/3] ml_decisions.db")
try:
    con2 = sqlite3.connect(ML_DB, timeout=10)
    n2 = con2.execute("SELECT COUNT(*) FROM ml_decisions").fetchone()[0]
    con2.execute("DELETE FROM ml_decisions")
    try:
        con2.execute("DELETE FROM sqlite_sequence WHERE name='ml_decisions'")
    except Exception:
        pass
    con2.commit()
    con2.close()
    print(f"  ✓ Borrados {n2} registros. Tabla vacia.")
except Exception as e:
    print(f"  ERROR: {e}")

# ── 3. risk_guard.json ────────────────────────────────────
RG_FILE = os.path.join(STATE, "risk_guard.json")
print(f"\n[3/3] risk_guard.json")
try:
    state = {
        "initial_capital": 1000.0,
        "high_water_mark": 1000.0,
        "consec_losses": 0,
        "daily": {},
        "tripped": False,
        "trip_reason": None,
        "trip_at": None,
        "current_balance": 1000.0,
        "current_dd_pct": 0.0
    }
    with open(RG_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    print(f"  ✓ Capital base: $1000.00 | TRIPPED: False | DD: 0.00%")
except Exception as e:
    print(f"  ERROR: {e}")

print()
print("=" * 55)
print("  ✓ Limpieza completa. Datos desde cero.")
print()
print("  Ahora ejecuta:")
print("    python bot_crypto.py run --dry-run")
print("=" * 55)
