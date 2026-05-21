#!/usr/bin/env python3
"""
Script para limpiar las predicciones de la BD sin perder estructura.
"""
import sqlite3
import os
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent / "state" / "crypto_predictions.db"

def clean_predictions():
    try:
        # Conectar con timeout largo
        con = sqlite3.connect(str(DB_PATH), timeout=20)
        con.isolation_level = None  # Autocommit mode

        cursor = con.cursor()

        # Obtener count antes
        cursor.execute("SELECT COUNT(*) FROM predictions")
        before = cursor.fetchone()[0]
        print(f"  Predicciones antes: {before}")

        # Limpiar
        cursor.execute("DELETE FROM predictions")
        cursor.execute("VACUUM")

        # Obtener count después
        cursor.execute("SELECT COUNT(*) FROM predictions")
        after = cursor.fetchone()[0]

        con.close()

        print(f"✓ LIMPIEZA EXITOSA")
        print(f"  Predicciones después: {after}")
        print(f"  Eliminadas: {before - after}")
        return True

    except Exception as e:
        print(f"✗ Error: {e}")
        return False

if __name__ == "__main__":
    clean_predictions()
