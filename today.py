import sqlite3, os
from datetime import date

con = sqlite3.connect(os.path.join(os.path.dirname(__file__), "state", "crypto_predictions.db"))
con.row_factory = sqlite3.Row

today = date.today().isoformat()
rows = con.execute("""
    SELECT id, symbol, outcome, pnl_pct, hours_held
    FROM predictions
    WHERE DATE(outcome_date) = ?
    ORDER BY id
""", (today,)).fetchall()

CAPITAL = 1000.0
POS = 0.05
total_usd = 0.0
wins = losses = 0

print(f"\n  Trades del {today}:")
print(f"  {'ID':>3} {'Symbol':<12} {'Out':<5} {'P&L':>8}  {'USD':>7}  {'Hold':>6}")
print("  " + "-" * 50)
for r in rows:
    pnl = r['pnl_pct'] or 0.0
    usd = CAPITAL * POS * (pnl / 100.0)
    total_usd += usd
    h = f"{r['hours_held']:.1f}h" if r['hours_held'] else "?"
    if r['outcome'] == 'WIN': wins += 1
    else: losses += 1
    print(f"  {r['id']:>3} {r['symbol']:<12} {r['outcome']:<5} {pnl:>+7.3f}%  ${usd:>+6.2f}  {h:>6}")

print("  " + "-" * 50)
print(f"  Wins: {wins}  Losses: {losses}  WR: {100*wins/(wins+losses):.1f}%")
print(f"  P&L neto hoy: ${total_usd:+.2f}")
con.close()
