"""
fix_resync_pair.py — Resincroniza un par desde cero en data_extended.db.

Uso tipico: si un par quedo incompleto por un bug de resume (caso BTCUSDT
post-smoke), borrar su data y su marker de progreso para forzar redescarga
del rango completo.

Uso:
    python -m model_d_training.fix_resync_pair BTCUSDT
    python -m model_d_training.fix_resync_pair BTCUSDT ETHUSDT
    python -m model_d_training.fix_resync_pair BTCUSDT --download
    python -m model_d_training.fix_resync_pair BTCUSDT --download --features --train

Flags:
    --download   Lanza download_extended.py para los pares resincronizados.
    --features   Regenera el CSV (debe correr DESPUES de la descarga).
    --train      Re-entrena (debe correr DESPUES de features).
    --all        Equivale a --download --features --train.
"""
import os
import sys
import argparse
import sqlite3
import subprocess
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
CRYPTO_BOT_DIR = os.path.dirname(ROOT_DIR)
DB_PATH = os.environ.get(
    "EXTENDED_DB_PATH",
    os.path.join(ROOT_DIR, "state", "data_extended.db"),
)


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def reset_pair(pair):
    """Borra data y marker de progreso de un par en todas las tablas."""
    con = sqlite3.connect(DB_PATH)
    c = con.cursor()

    log(f"Reseteando {pair}...")

    # Antes: stats
    n_ohlcv_before = c.execute(
        "SELECT COUNT(*) FROM ohlcv_1m WHERE pair=?", (pair,)
    ).fetchone()[0]
    n_funding_before = c.execute(
        "SELECT COUNT(*) FROM funding_rates WHERE pair=?", (pair,)
    ).fetchone()[0]
    n_oi_before = c.execute(
        "SELECT COUNT(*) FROM open_interest WHERE pair=?", (pair,)
    ).fetchone()[0]

    # Borrado
    c.execute("DELETE FROM ohlcv_1m WHERE pair=?", (pair,))
    c.execute("DELETE FROM funding_rates WHERE pair=?", (pair,))
    c.execute("DELETE FROM open_interest WHERE pair=?", (pair,))
    c.execute("DELETE FROM download_progress WHERE pair=?", (pair,))
    con.commit()
    con.close()

    log(f"  borrado ohlcv_1m:      {n_ohlcv_before:,} filas")
    log(f"  borrado funding_rates: {n_funding_before} filas")
    log(f"  borrado open_interest: {n_oi_before} filas")
    log(f"  marker de progreso eliminado")


def run_cmd(cmd, label):
    log(f"### {label}")
    log(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=CRYPTO_BOT_DIR)
    if result.returncode != 0:
        log(f"!! {label} fallo (exit={result.returncode})")
        return False
    log(f"### {label} OK")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pairs", nargs="+", help="Pares a resincronizar (ej: BTCUSDT)")
    ap.add_argument("--download", action="store_true",
                    help="Despues de resetear, vuelve a bajar los pares")
    ap.add_argument("--features", action="store_true",
                    help="Regenera el CSV de features (corre tras --download)")
    ap.add_argument("--train", action="store_true",
                    help="Re-entrena (corre tras --features)")
    ap.add_argument("--all", action="store_true",
                    help="Equivale a --download --features --train")
    args = ap.parse_args()

    if args.all:
        args.download = args.features = args.train = True

    pairs = [p.upper() for p in args.pairs]

    log("=" * 60)
    log(f"RESYNC: {', '.join(pairs)}")
    log(f"DB:     {DB_PATH}")
    log("=" * 60)

    if not os.path.exists(DB_PATH):
        log(f"!! DB no existe: {DB_PATH}")
        sys.exit(1)

    for pair in pairs:
        reset_pair(pair)

    py = sys.executable

    if args.download:
        log("=" * 60)
        for pair in pairs:
            ok = run_cmd(
                [py, "-m", "model_d_training.download_extended", "--pair", pair],
                f"Descarga {pair}"
            )
            if not ok:
                log(f"!! Aborto: la descarga de {pair} fallo")
                sys.exit(1)

    if args.features:
        log("=" * 60)
        ok = run_cmd(
            [py, "-m", "model_d_training.features_extended"],
            "Features extended"
        )
        if not ok:
            log("!! Aborto: features fallaron")
            sys.exit(1)

    if args.train:
        log("=" * 60)
        ok = run_cmd(
            [py, "-m", "model_d_training.train_full",
             "--label-combo", "s025_t040_h08"],
            "Training + auto-replace"
        )
        if not ok:
            log("!! Aborto: training fallo")
            sys.exit(1)

    log("=" * 60)
    log("RESYNC COMPLETO")


if __name__ == "__main__":
    main()
