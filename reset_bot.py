"""
reset_bot.py — Resetea el bot para empezar sesion limpia.

Hace:
  1. Cierra todas las predicciones PENDING al precio actual
  2. Resetea el risk guard (desbloquea TRIPPED)
  3. Muestra estado final listo para operar

Uso:
  python reset_bot.py
"""
import sys, os, json, sqlite3
from datetime import datetime, date

sys.path.insert(0, os.path.dirname(__file__))

print("=" * 55)
print("  RESET BOT — limpieza para nueva sesion")
print("=" * 55)

# ── 1. Cerrar predicciones PENDING ────────────────────────
print("\n[1/3] Cerrando predicciones PENDING al precio actual...")

try:
    from bot.crypto_data import get_price
    from bot.predictions import _conn

    con = _conn()
    pending = con.execute(
        "SELECT id, symbol, price_at_pred FROM predictions WHERE outcome='PENDING'"
    ).fetchall()

    if not pending:
        print("  Sin predicciones pendientes.")
    else:
        for p in pending:
            sym   = p["symbol"]
            entry = p["price_at_pred"]
            try:
                price = get_price(sym)
            except Exception:
                price = None

            if not price:
                # Sin precio: marcar como LOSS(0) con nota
                con.execute(
                    "UPDATE predictions SET outcome='LOSS', pnl_pct=0, "
                    "outcome_date=?, price_at_outcome=?, error_flags='MANUAL_RESET_NO_PRICE' "
                    "WHERE id=?",
                    (datetime.now().isoformat(), entry, p["id"])
                )
                print(f"  #{p['id']:>3} {sym:<14} sin precio -> LOSS(0%)")
            else:
                pnl     = (price - entry) / entry * 100
                outcome = "WIN" if pnl > 0 else "LOSS"
                con.execute(
                    "UPDATE predictions SET outcome=?, pnl_pct=?, "
                    "outcome_date=?, price_at_outcome=?, error_flags='MANUAL_RESET' "
                    "WHERE id=?",
                    (outcome, round(pnl, 4), datetime.now().isoformat(), price, p["id"])
                )
                icon = "✓" if outcome == "WIN" else "✗"
                print(f"  {icon} #{p['id']:>3} {sym:<14} entry=${entry:.4f} -> ${price:.4f} {pnl:+.3f}% [{outcome}]")

        con.commit()
        print(f"\n  {len(pending)} predicciones cerradas.")
    con.close()

except Exception as e:
    print(f"  ERROR cerrando predicciones: {e}")

# ── 2. Resetear Risk Guard ─────────────────────────────────
print("\n[2/3] Reseteando Risk Guard...")

STATE_DIR  = os.path.join(os.path.dirname(__file__), "state")
STATE_FILE = os.path.join(STATE_DIR, "risk_guard.json")

try:
    # Leer balance actual si existe
    # Fallback: leer del .env (CRYPTO_PORTFOLIO o CRYPTO_INITIAL_CAPITAL)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    _env_capital = (
        os.environ.get("CRYPTO_INITIAL_CAPITAL") or
        os.environ.get("CRYPTO_PORTFOLIO") or
        "1000"
    )
    current_balance = float(_env_capital)
    try:
        from bot.capital_profile import _get_usdt_balance
        bal = _get_usdt_balance()
        if bal and bal > 0:
            current_balance = bal
    except Exception:
        pass

    today = date.today().isoformat()
    state = {
        "initial_capital": current_balance,
        "high_water_mark": current_balance,
        "consec_losses": 0,
        "daily": {
            today: {
                "start_balance": current_balance,
                "min_balance": current_balance,
                "loss_pct": 0.0,
            }
        },
        "tripped": False,
        "trip_reason": None,
        "trip_at": None,
        "current_balance": current_balance,
        "current_dd_pct": 0.0,
    }
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

    print(f"  Risk Guard reseteado. Capital base: ${current_balance:.2f}")
    print(f"  TRIPPED: False | Losses seguidas: 0 | DD: 0.00%")

except Exception as e:
    print(f"  ERROR reseteando risk guard: {e}")

# ── 3. Estado final ────────────────────────────────────────
print("\n[3/3] Estado final...")

try:
    con2 = sqlite3.connect(os.path.join(STATE_DIR, "crypto_predictions.db"))
    n_pending = con2.execute(
        "SELECT COUNT(*) FROM predictions WHERE outcome='PENDING'"
    ).fetchone()[0]
    con2.close()
    print(f"  Predicciones PENDING: {n_pending}")
except Exception:
    print("  (no se pudo verificar DB)")

print()
print("=" * 55)
print("  ✓ Bot listo. Ahora ejecuta:")
print()
print("    python bot_crypto.py run --dry-run")
print()
print("  Eso abre sesion de 12h con ML + gate + monitor.")
print("=" * 55)
