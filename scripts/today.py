"""Foto del dia: trades cerrados HOY con WR y P&L neto en USD.

P&L ponderado por el sizing real de cada trade (position_usd); los trades
legacy sin sizing usan el fallback de 5% del capital. BE no cuenta en el WR.
Uso: python scripts/today.py
"""
import sqlite3, os
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
con = sqlite3.connect(os.path.join(ROOT, "state", "crypto_predictions.db"))
con.row_factory = sqlite3.Row

today = date.today().isoformat()
try:
    rows = con.execute("""
        SELECT id, symbol, outcome, pnl_pct, hours_held, position_usd
        FROM predictions
        WHERE DATE(outcome_date) = ? AND outcome IN ('WIN','LOSS','BE')
        ORDER BY id
    """, (today,)).fetchall()
except sqlite3.OperationalError:
    print("\n  Sin base de datos de predicciones todavia (el bot aun no corrio).")
    raise SystemExit(0)

CAPITAL = float(os.environ.get("CRYPTO_PORTFOLIO",
                os.environ.get("CRYPTO_INITIAL_CAPITAL", "1000")))
POS_FALLBACK = 0.05
total_usd = 0.0
wins = losses = be = 0

print(f"\n  Trades del {today}:")
print(f"  {'ID':>3} {'Symbol':<12} {'Out':<5} {'P&L':>8}  {'USD':>7}  {'Hold':>6}")
print("  " + "-" * 50)
for r in rows:
    pnl = r['pnl_pct'] or 0.0
    pos = r['position_usd'] if r['position_usd'] is not None else CAPITAL * POS_FALLBACK
    usd = pos * (pnl / 100.0)
    total_usd += usd
    h = f"{r['hours_held']:.1f}h" if r['hours_held'] else "?"
    if r['outcome'] == 'WIN':
        wins += 1
    elif r['outcome'] == 'LOSS':
        losses += 1
    else:
        be += 1
    print(f"  {r['id']:>3} {r['symbol']:<12} {r['outcome']:<5} {pnl:>+7.3f}%  ${usd:>+6.2f}  {h:>6}")

print("  " + "-" * 50)
if wins + losses > 0:
    print(f"  Wins: {wins}  Losses: {losses}  BE: {be}  WR: {100*wins/(wins+losses):.1f}%")
else:
    print("  Sin trades cerrados hoy." + (f" (BE: {be})" if be else ""))
print(f"  P&L neto hoy: ${total_usd:+.2f}")
con.close()
