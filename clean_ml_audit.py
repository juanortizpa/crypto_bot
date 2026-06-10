"""
clean_ml_audit.py — Limpia datos de ML previos a las correcciones del bot.

Elimina:
  * ml_decisions ABORT/basura del 19-22 Mayo (antes de las correcciones ML)
  * predictions antiguas resueltas anteriores a las correcciones (antes de id=29)
  * NO toca predicciones PENDING ni las del 23-24 Mayo en adelante

Uso:
  python clean_ml_audit.py          -> preview (sin borrar)
  python clean_ml_audit.py --apply  -> aplica el borrado real

IMPORTANTE: corre esto cuando el bot NO este activo, o entre sesiones.
"""
import sys, os, sqlite3
from datetime import datetime

DRY_RUN = "--apply" not in sys.argv

print("=" * 60)
print("  CLEAN ML AUDIT — limpieza de datos pre-correcciones")
print(f"  Modo: {'PREVIEW (sin cambios)' if DRY_RUN else '*** APLICANDO BORRADO REAL ***'}")
print("=" * 60)

STATE_DIR = os.path.join(os.path.dirname(__file__), "state")

# ── 1. ml_decisions.db ────────────────────────────────────────
ML_DB = os.path.join(STATE_DIR, "ml_decisions.db")
print(f"\n[1/2] ml_decisions.db")

if not os.path.exists(ML_DB):
    print("  Archivo no encontrado, saltando.")
else:
    try:
        con = sqlite3.connect(ML_DB)
        con.row_factory = sqlite3.Row

        # Contar lo que vamos a borrar (pre-23-Mayo o solo ABORT sin pred abierta)
        total = con.execute("SELECT COUNT(*) FROM ml_decisions").fetchone()[0]
        to_delete = con.execute(
            "SELECT COUNT(*) FROM ml_decisions "
            "WHERE DATE(decided_at) < '2026-05-23'"
        ).fetchone()[0]
        to_keep = total - to_delete

        print(f"  Total registros:    {total}")
        print(f"  A borrar (< 23-May): {to_delete}  (ABORT/basura pre-correcciones)")
        print(f"  A conservar:        {to_keep}  (May 23+ con trades reales)")

        # Muestra resumen de lo que se conserva
        rows = con.execute(
            "SELECT DATE(decided_at) as d, COUNT(*), "
            "GROUP_CONCAT(DISTINCT ml_decision) as decs "
            "FROM ml_decisions "
            "WHERE DATE(decided_at) >= '2026-05-23' "
            "GROUP BY d ORDER BY d"
        ).fetchall()
        print()
        print("  Registros conservados por dia:")
        for r in rows:
            print(f"    {r['d']}: {r[1]} evals — decisions: {r['decs']}")

        if not DRY_RUN:
            con.execute(
                "DELETE FROM ml_decisions WHERE DATE(decided_at) < '2026-05-23'"
            )
            # Reset autoincrement counter
            con.execute(
                "DELETE FROM sqlite_sequence WHERE name='ml_decisions'"
            )
            con.commit()
            after = con.execute("SELECT COUNT(*) FROM ml_decisions").fetchone()[0]
            print(f"\n  ✓ Borrados: {to_delete} registros. Quedan: {after}")
        else:
            print(f"\n  (preview) Ejecuta con --apply para borrar.")

        con.close()
    except Exception as e:
        print(f"  ERROR: {e}")

# ── 2. predictions (crypto_predictions.db) ─────────────────────
PRED_DB = os.path.join(STATE_DIR, "crypto_predictions.db")
print(f"\n[2/2] crypto_predictions.db")

if not os.path.exists(PRED_DB):
    print("  Archivo no encontrado, saltando.")
else:
    try:
        con2 = sqlite3.connect(PRED_DB, timeout=5)
        con2.row_factory = sqlite3.Row

        total_p = con2.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
        # Predicciones viejas = las de antes del 23 Mayo (pre-correcciones)
        # o con id < 29 (primeras con trades reales = Mayo 23)
        old_resolved = con2.execute(
            "SELECT COUNT(*) FROM predictions "
            "WHERE DATE(predicted_at) < '2026-05-23' "
            "AND outcome IN ('WIN','LOSS','ABORT')"
        ).fetchone()[0]
        pending_old = con2.execute(
            "SELECT COUNT(*) FROM predictions "
            "WHERE DATE(predicted_at) < '2026-05-23' "
            "AND outcome = 'PENDING'"
        ).fetchone()[0]

        print(f"  Total predicciones: {total_p}")
        print(f"  Pre-23-May resueltas: {old_resolved}  (a borrar)")
        if pending_old:
            print(f"  Pre-23-May PENDING:   {pending_old}  (¡OJO! hay pendientes antiguas, NO se borran)")

        # Lo que se conserva
        keep_rows = con2.execute(
            "SELECT DATE(predicted_at) as d, COUNT(*), "
            "GROUP_CONCAT(DISTINCT outcome) as outs "
            "FROM predictions "
            "WHERE DATE(predicted_at) >= '2026-05-23' "
            "GROUP BY d ORDER BY d"
        ).fetchall()
        print()
        print("  Predicciones conservadas por dia:")
        for r in keep_rows:
            print(f"    {r['d']}: {r[1]} preds — outcomes: {r['outs']}")

        if not DRY_RUN:
            con2.execute(
                "DELETE FROM predictions "
                "WHERE DATE(predicted_at) < '2026-05-23' "
                "AND outcome IN ('WIN','LOSS','ABORT')"
            )
            con2.commit()
            after_p = con2.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
            print(f"\n  ✓ Borradas: {old_resolved} predicciones antiguas. Quedan: {after_p}")
        else:
            print(f"\n  (preview) Ejecuta con --apply para borrar.")

        con2.close()
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower():
            print("  DB bloqueada por el bot en ejecucion.")
            print("  Detén el bot primero (Ctrl+C) y luego corre este script con --apply.")
        else:
            print(f"  ERROR: {e}")
    except Exception as e:
        print(f"  ERROR: {e}")

# ── Resumen ────────────────────────────────────────────────────
print()
print("=" * 60)
if DRY_RUN:
    print("  PREVIEW completado. Para aplicar cambios:")
    print()
    print("    1. Detén el bot (Ctrl+C si está corriendo)")
    print("    2. python clean_ml_audit.py --apply")
    print("    3. Reinicia: python bot_crypto.py run --dry-run")
else:
    print("  ✓ Limpieza completada. Base de datos lista.")
    print()
    print("  Ahora el bot evaluará desde cero con datos limpios.")
    print("  Ejecuta: python bot_crypto.py run --dry-run")
print("=" * 60)
