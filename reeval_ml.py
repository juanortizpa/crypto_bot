"""
reeval_ml.py — Borra las evaluaciones ML ya calculadas y las recalcula
usando los resultados REALES de los trades (no simulacion).

Uso:
  python reeval_ml.py
"""
import os, sqlite3

DB = os.path.join(os.path.dirname(__file__), "state", "ml_decisions.db")

con = sqlite3.connect(DB, timeout=10)
n = con.execute("SELECT COUNT(*) FROM ml_decisions WHERE eval_verdict IS NOT NULL").fetchone()[0]
con.execute("""
    UPDATE ml_decisions
    SET evaluated_at=NULL, eval_outcome=NULL, eval_pnl_pct=NULL,
        eval_max_pnl=NULL, eval_min_pnl=NULL, eval_verdict=NULL
    WHERE eval_verdict IS NOT NULL
""")
con.commit()
con.close()
print(f"Limpiadas {n} evaluaciones previas.")
print("Ahora corre:  python bot_crypto.py ml-eval")
