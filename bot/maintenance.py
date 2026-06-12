"""
Mantenimiento programado para operación 24/7.

Tareas (cada una invocable por separado via `python bot_crypto.py maintain <tarea>`,
y orquestadas automáticamente por bot/forever.py entre sesiones):

  backup    — copia state/*.db a state/backups/ (retiene las últimas 10)
  data      — refresco incremental de datos de mercado:
                * model_d_training/state/data_2026.db   (klines 5m, reanudable)
                * model_d_training/state/data_extended.db (1m + macro DXY/SP500/VIX
                  que ml_inference usa EN VIVO — si esta DB está vieja, las
                  features macro del ensemble salen congeladas)
  models    — reentrena meta_model y exit_model si hay suficientes trades
              cerrados con la contabilidad honesta (post 2026-06-10)
  ensemble  — pipeline completo del Modelo D (features → grid/xgb/hybrid →
              compare) con QUALITY GATE: respalda los *_best.json y *.pkl
              actuales y SOLO adopta el resultado nuevo si compare lo marca
              deployable (WR y PF out-of-sample suficientes); si no, restaura.

Cada tarea corre en subprocess con timeout para que un cuelgue del pipeline
no congele el orquestador.
"""
import os
import sys
import json
import glob
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bot.logger import log

STATE_DIR = os.path.join(ROOT, "state")
BACKUP_DIR = os.path.join(STATE_DIR, "backups")
RESULTS_DIR = os.path.join(ROOT, "model_d_training", "results")
KEEP_BACKUPS = int(os.environ.get("CRYPTO_KEEP_BACKUPS", "10"))

# Timeouts (segundos) para subprocesos del pipeline
DATA_TIMEOUT = int(os.environ.get("CRYPTO_DATA_TIMEOUT_SEC", "5400"))      # 90 min
TRAIN_TIMEOUT = int(os.environ.get("CRYPTO_TRAIN_TIMEOUT_SEC", "10800"))   # 3 h


def _run_module(module: str, timeout: int, extra_args=None) -> bool:
    """Corre `python -m <module>` como subproceso. True si exit code 0."""
    cmd = [sys.executable, "-m", module] + (extra_args or [])
    log("INFO", f"maintenance: ejecutando {' '.join(cmd)} (timeout {timeout}s)")
    try:
        res = subprocess.run(cmd, cwd=ROOT, timeout=timeout)
        if res.returncode != 0:
            log("WARN", f"maintenance: {module} salio con codigo {res.returncode}")
            return False
        return True
    except subprocess.TimeoutExpired:
        log("WARN", f"maintenance: {module} excedio el timeout de {timeout}s — abortado")
        return False
    except Exception as e:
        log("WARN", f"maintenance: {module} fallo: {e}")
        return False


# ── 1. Backups de las bases de datos ─────────────────────────────────────

def backup_databases() -> list:
    """Copia segura (sqlite backup API) de las DBs operativas. Retorna paths."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    created = []
    for name in ("crypto_predictions.db", "ml_decisions.db"):
        src = os.path.join(STATE_DIR, name)
        if not os.path.exists(src):
            continue
        dst = os.path.join(BACKUP_DIR, f"{name}.{stamp}")
        try:
            src_con = sqlite3.connect(src)
            dst_con = sqlite3.connect(dst)
            with dst_con:
                src_con.backup(dst_con)
            src_con.close()
            dst_con.close()
            created.append(dst)
            log("INFO", f"maintenance: backup {name} -> {os.path.basename(dst)}")
        except Exception as e:
            log("WARN", f"maintenance: backup de {name} fallo: {e}")
    # Retencion: borrar los mas viejos
    for name in ("crypto_predictions.db", "ml_decisions.db"):
        old = sorted(glob.glob(os.path.join(BACKUP_DIR, f"{name}.*")))
        for path in old[:-KEEP_BACKUPS]:
            try:
                os.remove(path)
            except Exception:
                pass
    return created


# ── 2. Refresco incremental de datos de mercado ──────────────────────────

def refresh_market_data() -> bool:
    """
    Descarga incremental de klines + macro. Ambos scripts son reanudables:
    solo bajan lo nuevo desde el ultimo timestamp, asi que en regimen diario
    tarda minutos, no los 30-45 min de la descarga inicial.
    """
    ok1 = _run_module("model_d_training.download_data", DATA_TIMEOUT)
    ok2 = _run_module("model_d_training.download_extended", DATA_TIMEOUT)
    if not ok2:
        log("WARN", "maintenance: data_extended.db NO actualizada — las features "
                    "macro (DXY/SP500/VIX) del ML en vivo quedaran desactualizadas")
    return ok1 and ok2


def data_freshness() -> dict:
    """Edad (en horas) del ultimo dato en cada DB de entrenamiento/inferencia."""
    out = {}
    spec = {
        "data_2026.db": ("SELECT MAX(timestamp) FROM ohlcv", "iso"),
        "data_extended.db": ("SELECT MAX(ts_ms) FROM ohlcv_1m", "ms"),
    }
    for fname, (query, kind) in spec.items():
        path = os.path.join(ROOT, "model_d_training", "state", fname)
        age_h = None
        try:
            con = sqlite3.connect(path)
            val = con.execute(query).fetchone()[0]
            con.close()
            if val is not None:
                # Comparar SIEMPRE en UTC: los timestamps de las DBs son UTC
                # y datetime.now() local daba edades negativas (ej. UTC-5).
                if kind == "ms":
                    last = datetime.fromtimestamp(int(val) / 1000, tz=timezone.utc)
                else:
                    last = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
                    if last.tzinfo is None:
                        last = last.replace(tzinfo=timezone.utc)
                age_h = round((datetime.now(timezone.utc) - last).total_seconds() / 3600, 1)
        except Exception:
            pass
        out[fname] = age_h
    return out


# ── 3. Reentrenar meta_model y exit_model con trades vivos ──────────────

def retrain_live_models() -> dict:
    """
    Reentrena meta_model (eleccion de modelo/entrada) y exit_model (salida)
    SOLO si hay suficientes ejemplos post-fix de contabilidad. Si no hay,
    no hace nada y reporta cuanto falta — el runner sigue con P(WIN)=0.5.
    """
    result = {"meta": "SKIP", "exit": "SKIP"}

    try:
        from bot.meta_model import collect_meta_training_data, train_meta_model, MIN_SAMPLES as META_MIN
        n = len(collect_meta_training_data())
        if n >= META_MIN:
            log("INFO", f"maintenance: entrenando meta_model con {n} trades...")
            out = train_meta_model(verbose=False)
            result["meta"] = "TRAINED" if out else "FAILED"
        else:
            result["meta"] = f"SKIP ({n}/{META_MIN} trades)"
            log("INFO", f"maintenance: meta_model aun sin datos suficientes ({n}/{META_MIN})")
    except Exception as e:
        result["meta"] = f"ERROR: {e}"
        log("WARN", f"maintenance: meta_model retrain fallo: {e}")

    try:
        from bot.exit_model import collect_training_data, train_classifier, MIN_SAMPLES as EXIT_MIN
        n = len(collect_training_data())
        if n >= EXIT_MIN:
            log("INFO", f"maintenance: entrenando exit_model con {n} snapshots...")
            out = train_classifier(verbose=False)
            result["exit"] = "TRAINED" if out else "FAILED"
        else:
            result["exit"] = f"SKIP ({n}/{EXIT_MIN} ejemplos)"
            log("INFO", f"maintenance: exit_model aun sin datos suficientes ({n}/{EXIT_MIN})")
    except Exception as e:
        result["exit"] = f"ERROR: {e}"
        log("WARN", f"maintenance: exit_model retrain fallo: {e}")

    return result


# ── 4. Reentrenar ensemble del Modelo D con quality gate ────────────────

_ENSEMBLE_ARTIFACTS = [
    "xgb_best.json", "rf_best.json", "hybrid_best.json", "grid_best.json",
    "comparison.json", "winner_config.json",
]


def _snapshot_results(tag: str) -> str:
    """Respalda results/ (json + pkl) antes de reentrenar. Retorna dir."""
    dst = os.path.join(RESULTS_DIR, f"backup_{tag}")
    os.makedirs(dst, exist_ok=True)
    for pattern in ("*.json", "*.pkl"):
        for path in glob.glob(os.path.join(RESULTS_DIR, pattern)):
            shutil.copy2(path, dst)
    return dst


def _restore_results(backup_dir: str):
    for path in glob.glob(os.path.join(backup_dir, "*")):
        shutil.copy2(path, RESULTS_DIR)


def retrain_ensemble() -> str:
    """
    Pipeline offline completo del ensemble (Modelo D). Pasos de GUIA_DIARIA:
      features → train_grid → train_xgb → train_hybrid → compare

    QUALITY GATE: el resultado solo se adopta si comparison.json marca
    deployable=true (WR/PF out-of-sample suficientes). Si no, se restauran
    los artefactos anteriores: mejor un modelo viejo conocido que uno nuevo
    que la validacion ya marco como no operable.

    Retorna: 'ADOPTED' | 'REJECTED_RESTORED' | 'FAILED_RESTORED'
    """
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = _snapshot_results(stamp)
    log("INFO", f"maintenance: ensemble retrain — backup previo en {backup_dir}")

    steps = [
        "model_d_training.features",
        "model_d_training.train_grid",
        "model_d_training.train_xgb",
        "model_d_training.train_hybrid",
    ]
    for step in steps:
        if not _run_module(step, TRAIN_TIMEOUT):
            log("WARN", f"maintenance: ensemble retrain fallo en {step} — restaurando modelos previos")
            _restore_results(backup_dir)
            _reload_inference()
            return "FAILED_RESTORED"

    # Tercer votante del ensemble (RF), via train_full sobre features_extended.
    # No fatal: train_full tiene su propio quality gate (TRAIN_MIN_*) y si las
    # metricas no llegan no reemplaza nada — sin RF el ensemble vota con 2.
    if not _run_module("model_d_training.train_full", TRAIN_TIMEOUT,
                       extra_args=["--models", "rf"]):
        log("WARN", "maintenance: trainer RF no paso (no fatal) — "
                    "el ensemble seguira votando sin RF")

    if not _run_module("model_d_training.compare", TRAIN_TIMEOUT):
        log("WARN", "maintenance: ensemble retrain fallo en compare — restaurando modelos previos")
        _restore_results(backup_dir)
        _reload_inference()
        return "FAILED_RESTORED"

    # Quality gate sobre la validacion out-of-sample
    deployable = False
    try:
        with open(os.path.join(RESULTS_DIR, "comparison.json"), encoding="utf-8") as f:
            comp = json.load(f)
        deployable = bool(comp.get("deployable"))
        winner = comp.get("winner", {})
        log("INFO", f"maintenance: compare -> ganador={winner.get('name')} "
                    f"WR={winner.get('win_rate', 0)*100:.1f}% PF={winner.get('pf')} "
                    f"deployable={deployable}")
    except Exception as e:
        log("WARN", f"maintenance: no se pudo leer comparison.json: {e}")

    if not deployable:
        log("WARN", "maintenance: nuevo ensemble NO deployable out-of-sample — "
                    "se restauran los modelos anteriores")
        _restore_results(backup_dir)
        _reload_inference()
        return "REJECTED_RESTORED"

    _reload_inference()
    log("INFO", "maintenance: nuevo ensemble ADOPTADO (deployable OOS)")
    return "ADOPTED"


def _reload_inference():
    try:
        from bot.ml_inference import reload_models
        reload_models()
    except Exception:
        pass


# ── CLI ──────────────────────────────────────────────────────────────────

def main(task: str):
    if task == "backup":
        backup_databases()
    elif task == "data":
        refresh_market_data()
        print(f"\n  Frescura de datos: {data_freshness()}\n")
    elif task == "models":
        print(retrain_live_models())
    elif task == "ensemble":
        print(retrain_ensemble())
    else:
        print("  Uso: python bot_crypto.py maintain [backup|data|models|ensemble]")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")
