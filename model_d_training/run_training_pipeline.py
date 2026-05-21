"""
run_training_pipeline.py — Pipeline completo de UNA pasada.

Encadena:
  1. Smoke test (opcional, --skip-smoke para saltar)
  2. Descarga extendida: 1m + funding + OI + macro desde 2024
  3. Generacion de features (~80 variables sobre 1m + auxiliares)
  4. Entrenamiento: XGB + RF + Hybrid con auto-replace si pasa thresholds

Es la operacion principal cuando quieres reentrenar todo desde cero o desde
el ultimo checkpoint (las descargas tienen resume automatico).

Uso:
    cd crypto_bot
    python -m model_d_training.run_training_pipeline               # todo, full
    python -m model_d_training.run_training_pipeline --skip-smoke  # salta smoke
    python -m model_d_training.run_training_pipeline --skip-download
    python -m model_d_training.run_training_pipeline --skip-features
    python -m model_d_training.run_training_pipeline --start 2024-06-01

Estimaciones de tiempo (en una PC normal con buena conexion):
  - Smoke test:    1-2 minutos
  - Descarga full: 3-6 horas (20 pares x 2 anos x 1m + macro)
  - Features:      30-90 minutos (depende de RAM disponible)
  - Entrenamiento: 10-30 minutos
  - Total:         ~4-8 horas

Recomendacion: lanzar en una terminal de fondo (nohup o pythonw) y revisar
el log periodicamente. El runner del bot puede seguir operando en paralelo
con los modelos viejos hasta que el pipeline termine y reemplace los .pkl.
"""

import os
import sys
import argparse
import subprocess
import time
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
CRYPTO_BOT_DIR = os.path.dirname(ROOT_DIR)


def log(msg):
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n", flush=True)


def run_cmd(cmd, label):
    log(f"### {label}")
    log(f"$ {' '.join(cmd)}")
    t0 = time.time()
    result = subprocess.run(cmd, cwd=CRYPTO_BOT_DIR)
    elapsed = time.time() - t0
    log(f"### {label} terminado en {elapsed/60:.1f} min (exit={result.returncode})")
    return result.returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-smoke", action="store_true")
    ap.add_argument("--skip-download", action="store_true")
    ap.add_argument("--skip-features", action="store_true")
    ap.add_argument("--skip-training", action="store_true")
    ap.add_argument("--start", help="Fecha inicio YYYY-MM-DD (default 2024-01-01)")
    ap.add_argument("--no-replace", action="store_true",
                    help="Entrena pero NO reemplaza modelos actuales")
    ap.add_argument("--label-combo", default="s025_t040_h08")
    args = ap.parse_args()

    py = sys.executable

    log("PIPELINE DE ENTRENAMIENTO COMPLETO")
    log(f"Working dir: {CRYPTO_BOT_DIR}")
    log(f"Python:      {py}")

    # ---- 1. Smoke test ----
    if not args.skip_smoke:
        log("FASE 1: Smoke test (1 par, 7 dias)")
        ok = run_cmd([py, "-m", "model_d_training.download_extended", "--smoke"],
                     "Smoke test")
        if not ok:
            log("XX Smoke test fallo. Revisa la conexion a Binance. Aborto.")
            sys.exit(1)
    else:
        log("FASE 1: Smoke test SALTADO")

    # ---- 2. Descarga ----
    if not args.skip_download:
        log("FASE 2: Descarga completa (1m + funding + OI + macro)")
        cmd = [py, "-m", "model_d_training.download_extended"]
        if args.start:
            cmd += ["--start", args.start]
        ok = run_cmd(cmd, "Descarga extendida")
        if not ok:
            log("XX Descarga termino con errores. Continuar de todas formas? (Ctrl+C para abortar)")
            time.sleep(10)
    else:
        log("FASE 2: Descarga SALTADA")

    # ---- 3. Features ----
    if not args.skip_features:
        log("FASE 3: Generacion de features extendidas")
        ok = run_cmd([py, "-m", "model_d_training.features_extended"],
                     "Features extended")
        if not ok:
            log("XX Generacion de features fallo. Aborto.")
            sys.exit(1)
    else:
        log("FASE 3: Features SALTADAS")

    # ---- 4. Entrenamiento ----
    if not args.skip_training:
        log("FASE 4: Entrenamiento + auto-replace")
        cmd = [py, "-m", "model_d_training.train_full",
               "--label-combo", args.label_combo]
        if args.no_replace:
            cmd.append("--no-replace")
        ok = run_cmd(cmd, "Train full")
        if not ok:
            log("XX Entrenamiento fallo.")
            sys.exit(1)
    else:
        log("FASE 4: Entrenamiento SALTADO")

    log("PIPELINE COMPLETO. Revisa los archivos en model_d_training/results/")


if __name__ == "__main__":
    main()
