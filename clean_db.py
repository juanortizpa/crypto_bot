#!/usr/bin/env python3
"""
Script para limpiar las predicciones del DB directamente desde el bot.
Usa el mismo _conn() que el bot para evitar problemas de lock.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from bot.predictions import _conn, DB_PATH

def clean_all_predictions():
    """Elimina TODAS las predicciones manteniendo la estructura de la tabla."""
    print("\n" + "="*60)
    print("LIMPIANDO PREDICCIONES")
    print("="*60)

    try:
        con = _conn()  # Usar la función de conexión del bot
        cursor = con.cursor()

        # Obtener stats antes
        cursor.execute("SELECT COUNT(*) FROM predictions")
        before = cursor.fetchone()[0]
        print(f"✓ Conectado a: {DB_PATH}")
        print(f"  Predicciones antes: {before}")

        # Eliminar todas
        cursor.execute("DELETE FROM predictions")

        # Compactar BD
        cursor.execute("VACUUM")
        con.commit()

        # Stats después
        cursor.execute("SELECT COUNT(*) FROM predictions")
        after = cursor.fetchone()[0]

        con.close()

        print(f"\n✓ LIMPIEZA COMPLETADA")
        print(f"  Predicciones eliminadas: {before - after}")
        print(f"  Predicciones actuales: {after}")
        print(f"  Base de datos compactada (VACUUM)")
        print("\n✓ El bot está listo para nuevas predicciones.")
        print("="*60 + "\n")

        return True

    except Exception as e:
        print(f"\n✗ Error durante limpieza: {e}")
        print(f"  Tipo: {type(e).__name__}")
        return False

if __name__ == "__main__":
    success = clean_all_predictions()
    sys.exit(0 if success else 1)
