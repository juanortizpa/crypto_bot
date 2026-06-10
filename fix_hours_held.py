"""
fix_hours_held.py — Rellena hours_held para trades cerrados sin ese valor.

Calcula (outcome_date - predicted_at) en horas para los 93 registros
que tienen hours_held = NULL o 0, causando que el reporte muestre AvgH: 0.1h.

Uso:
  python fix_hours_held.py
"""
import os, sqlite3
from datetime import datetime

DB = os.path.join(os.path.dirname(__file__), "state", "crypto_predictions.db")

print("=" * 55)
print("  FIX HOURS_HELD — rellenar tiempos de hold faltantes")
print("=" * 55)

con = sqlite3.connect(DB, timeout=15)
con.row_factory = sqlite3.Row

rows = con.execute("""
    SELECT id, predicted_at, outcome_date
    FROM predictions
    WHERE (hours_held IS NULL OR hours_held = 0)
      AND outcome IN ('WIN','LOSS')
      AND predicted_at IS NOT NULL
      AND outcome_date IS NOT NULL
""").fetchall()

print(f"\n  Registros a corregir: {len(rows)}")

updated = 0
skipped = 0
for r in rows:
    try:
        t_pred = datetime.fromisoformat(r["predicted_at"])
        t_out  = datetime.fromisoformat(r["outcome_date"])
        h = round((t_out - t_pred).total_seconds() / 3600, 4)
        if h < 0:
            h = 0.0
        con.execute("UPDATE predictions SET hours_held=? WHERE id=?", (h, r["id"]))
        updated += 1
    except Exception as e:
        print(f"  skip id={r['id']}: {e}")
        skipped += 1

con.commit()

# Verificación
res = con.execute("""
    SELECT
        COUNT(*) as n,
        SUM(CASE WHEN hours_held IS NULL OR hours_held = 0 THEN 1 ELSE 0 END) as nulls,
        ROUND(AVG(CASE WHEN hours_held > 0 THEN hours_held END), 2) as avg_real,
        ROUND(AVG(hours_held), 2) as avg_total
    FROM predictions WHERE outcome IN ('WIN','LOSS')
""").fetchone()

con.close()

print(f"  Actualizados: {updated}")
print(f"  Saltados:     {skipped}")
print(f"\n  Resultado:")
print(f"  Total trades:  {res['n']}")
print(f"  Siguen NULL/0: {res['nulls']}")
print(f"  AvgH real:     {res['avg_real']}h")
print(f"  AvgH en report:{res['avg_total']}h")
print()
print("=" * 55)
print("  Listo. Ahora 'python run_crypto_models.py report'")
print("  deberia mostrar el AvgH correcto.")
print("=" * 55)
