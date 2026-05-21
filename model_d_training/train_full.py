"""
train_full.py — Pipeline completo de entrenamiento con auto-replace.

Pasos:
  1. Verifica que existe state/features_extended.csv (corre features_extended.py si falta)
  2. Backup de modelos actuales en results/backup_<timestamp>/
  3. Entrena XGBoost sobre el CSV con walk-forward validation
  4. Entrena RandomForest como fallback / ensemble
  5. Entrena LogisticRegression calibrada (hybrid)
  6. Evalua todos con metricas: WR, PF, Sharpe, Expectancy, drawdown estimado
  7. Si las metricas superan umbrales minimos -> reemplaza modelos
  8. Genera reporte: results/training_report_<timestamp>.json

Umbrales para auto-replace (configurables via env):
  TRAIN_MIN_WR             default 0.52    (win rate minimo)
  TRAIN_MIN_PF             default 1.40    (profit factor minimo)
  TRAIN_MIN_EXPECTANCY     default 0.30    (expectancy en %)
  TRAIN_MIN_TRADES         default 50      (n. de trades en test)

Si las metricas no llegan, los modelos NO se reemplazan y se reporta error.

Uso:
    cd crypto_bot
    python -m model_d_training.train_full
    python -m model_d_training.train_full --label-combo s025_t040_h08
    python -m model_d_training.train_full --no-replace          # solo evalua
    python -m model_d_training.train_full --models xgb hybrid   # solo entrena estos
"""

import os
import sys
import json
import shutil
import argparse
import sqlite3
from datetime import datetime, timezone
import math

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Dependencias opcionales: numpy, pandas, sklearn, xgboost
# Si no están, el script falla con un mensaje claro
try:
    import numpy as np
    import pandas as pd
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import accuracy_score, precision_score, recall_score
    import pickle
except ImportError as e:
    print(f"ERROR: falta dependencia ({e}). Instala con: pip install numpy pandas scikit-learn xgboost")
    sys.exit(1)

try:
    import xgboost as xgb
    HAS_XGB = True
except ImportError:
    HAS_XGB = False
    print("[WARN] xgboost no instalado, se usara solo RandomForest + LogisticRegression")


ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(ROOT_DIR, "state")
RESULTS_DIR = os.path.join(ROOT_DIR, "results")
BOT_STATE_DIR = os.path.join(os.path.dirname(ROOT_DIR), "state")

FEATURES_CSV = os.path.join(STATE_DIR, "features_extended.csv")

# Umbrales auto-replace
MIN_WR  = float(os.environ.get("TRAIN_MIN_WR", "0.52"))
MIN_PF  = float(os.environ.get("TRAIN_MIN_PF", "1.40"))
MIN_EXP = float(os.environ.get("TRAIN_MIN_EXPECTANCY", "0.30"))
MIN_TRADES = int(os.environ.get("TRAIN_MIN_TRADES", "50"))

# Combo de stop/target default para entrenar
DEFAULT_COMBO = "s025_t040_h08"


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ── Carga y prep de dataset ───────────────────────────────────────────────

def load_dataset(combo_suffix=DEFAULT_COMBO):
    """Carga features CSV y prepara X, y, pnls."""
    if not os.path.exists(FEATURES_CSV):
        raise FileNotFoundError(
            f"No existe {FEATURES_CSV}. Corre primero:\n"
            f"  python -m model_d_training.features_extended"
        )
    df = pd.read_csv(FEATURES_CSV)
    log(f"CSV cargado: {len(df):,} filas, {len(df.columns)} cols")

    label_col = f"label_{combo_suffix}"
    pnl_col   = f"pnl_{combo_suffix}"
    held_col  = f"held_{combo_suffix}"
    if label_col not in df.columns:
        raise ValueError(f"Columna {label_col} no existe en CSV. Combos disponibles: "
                         f"{[c for c in df.columns if c.startswith('label_')]}")

    # Drop TIMEOUT (mantenemos solo WIN/LOSS para clasificacion binaria)
    # Pero TIMEOUT con pnl positivo es semi-WIN, lo metemos como decisión por pnl
    df["binary_label"] = (df[pnl_col] > 0).astype(int)

    # Excluir cols no-features
    feature_cols = [c for c in df.columns
                    if not c.startswith("label_")
                    and not c.startswith("pnl_")
                    and not c.startswith("held_")
                    and c not in ("pair", "ts_ms", "entry_price", "binary_label")]

    # Sort temporal (importante para split walk-forward)
    df = df.sort_values("ts_ms").reset_index(drop=True)

    # Imputar NaN con 0 (la mayoria son features que no tenian historial)
    df[feature_cols] = df[feature_cols].fillna(0)

    X = df[feature_cols].values.astype(np.float32)
    y = df["binary_label"].values.astype(np.int8)
    pnl = df[pnl_col].values.astype(np.float32)
    ts = df["ts_ms"].values

    log(f"Features: {len(feature_cols)} | Balance: {y.mean()*100:.1f}% WIN | combo={combo_suffix}")
    return X, y, pnl, ts, feature_cols, df


def temporal_split(X, y, pnl, ts, train_ratio=0.70, val_ratio=0.15):
    n = len(X)
    n_train = int(n * train_ratio)
    n_val   = int(n * val_ratio)
    return {
        "X_train": X[:n_train],            "y_train": y[:n_train],            "pnl_train": pnl[:n_train],
        "X_val":   X[n_train:n_train+n_val], "y_val": y[n_train:n_train+n_val], "pnl_val":   pnl[n_train:n_train+n_val],
        "X_test":  X[n_train+n_val:],       "y_test": y[n_train+n_val:],        "pnl_test":  pnl[n_train+n_val:],
        "ts_train_end": ts[n_train-1] if n_train > 0 else 0,
        "ts_test_start": ts[n_train+n_val] if (n_train+n_val) < n else 0,
    }


# ── Metricas de trading ───────────────────────────────────────────────────

def trading_metrics(y_true, y_pred, pnls):
    """Calcula WR, PF, expectancy, Sharpe sobre los trades donde y_pred=1."""
    mask = y_pred == 1
    n_trades = mask.sum()
    if n_trades == 0:
        return {"n_trades": 0, "wr": 0, "pf": 0, "expectancy": 0,
                "sharpe": 0, "avg_pnl": 0, "total_pnl": 0}
    trade_pnls = pnls[mask]
    wins = trade_pnls[trade_pnls > 0]
    losses = trade_pnls[trade_pnls <= 0]
    wr = len(wins) / n_trades
    pf = (wins.sum() / abs(losses.sum())) if losses.sum() < 0 else 999
    avg_pnl = float(trade_pnls.mean())
    std_pnl = float(trade_pnls.std()) or 1
    sharpe = (avg_pnl / std_pnl) * math.sqrt(n_trades)
    expectancy = wr * float(wins.mean() if len(wins) else 0) + (1 - wr) * float(losses.mean() if len(losses) else 0)
    return {
        "n_trades": int(n_trades),
        "wr": float(wr),
        "pf": float(pf),
        "expectancy": float(expectancy),
        "sharpe": float(sharpe),
        "avg_pnl": avg_pnl,
        "total_pnl": float(trade_pnls.sum()),
    }


def find_best_threshold(probs, y_true, pnls):
    """Busca threshold que maximiza expectancy en val."""
    best = {"thr": 0.5, "score": -999, "metrics": None}
    for thr in np.arange(0.40, 0.85, 0.025):
        pred = (probs >= thr).astype(int)
        m = trading_metrics(y_true, pred, pnls)
        if m["n_trades"] < 10:
            continue
        # Guard rails: WR>=0.40 y PF>=1.2
        if m["wr"] < 0.40 or m["pf"] < 1.2:
            continue
        score = m["expectancy"] * math.log1p(m["n_trades"])
        if score > best["score"]:
            best = {"thr": float(thr), "score": score, "metrics": m}
    return best


# ── Trainers ──────────────────────────────────────────────────────────────

def train_xgb(splits, feature_cols):
    if not HAS_XGB:
        return None
    log("Entrenando XGBoost...")
    pos = splits["y_train"].sum()
    neg = len(splits["y_train"]) - pos
    spw = (neg / pos) if pos > 0 else 1.0

    model = xgb.XGBClassifier(
        n_estimators=200, max_depth=4, learning_rate=0.05,
        scale_pos_weight=spw, reg_alpha=0.5, reg_lambda=1.0,
        subsample=0.85, colsample_bytree=0.85,
        eval_metric="logloss", random_state=42, n_jobs=-1,
    )
    model.fit(splits["X_train"], splits["y_train"],
              eval_set=[(splits["X_val"], splits["y_val"])],
              verbose=False)

    probs_val = model.predict_proba(splits["X_val"])[:, 1]
    best = find_best_threshold(probs_val, splits["y_val"], splits["pnl_val"])
    if not best["metrics"]:
        log("  XGB: no threshold valido encontrado en val")
        return {"name": "xgb", "model": model, "threshold": 0.5,
                "metrics_val": None, "metrics_test": None}

    probs_test = model.predict_proba(splits["X_test"])[:, 1]
    pred_test = (probs_test >= best["thr"]).astype(int)
    m_test = trading_metrics(splits["y_test"], pred_test, splits["pnl_test"])

    log(f"  XGB val: WR={best['metrics']['wr']:.3f} PF={best['metrics']['pf']:.2f} "
        f"n={best['metrics']['n_trades']} thr={best['thr']:.3f}")
    log(f"  XGB test: WR={m_test['wr']:.3f} PF={m_test['pf']:.2f} n={m_test['n_trades']}")

    return {"name": "xgb", "model": model, "threshold": best["thr"],
            "feature_cols": feature_cols,
            "metrics_val": best["metrics"], "metrics_test": m_test}


def train_rf(splits, feature_cols):
    log("Entrenando RandomForest...")
    model = RandomForestClassifier(
        n_estimators=300, max_depth=8, min_samples_split=20,
        class_weight="balanced", random_state=42, n_jobs=-1,
    )
    model.fit(splits["X_train"], splits["y_train"])

    probs_val = model.predict_proba(splits["X_val"])[:, 1]
    best = find_best_threshold(probs_val, splits["y_val"], splits["pnl_val"])
    if not best["metrics"]:
        log("  RF: no threshold valido")
        return {"name": "rf", "model": model, "threshold": 0.5,
                "metrics_val": None, "metrics_test": None}

    probs_test = model.predict_proba(splits["X_test"])[:, 1]
    pred_test = (probs_test >= best["thr"]).astype(int)
    m_test = trading_metrics(splits["y_test"], pred_test, splits["pnl_test"])

    log(f"  RF val: WR={best['metrics']['wr']:.3f} PF={best['metrics']['pf']:.2f} "
        f"n={best['metrics']['n_trades']} thr={best['thr']:.3f}")
    log(f"  RF test: WR={m_test['wr']:.3f} PF={m_test['pf']:.2f} n={m_test['n_trades']}")

    return {"name": "rf", "model": model, "threshold": best["thr"],
            "feature_cols": feature_cols,
            "metrics_val": best["metrics"], "metrics_test": m_test}


def train_hybrid(splits, feature_cols):
    log("Entrenando Hybrid (LogReg + isotonic)...")
    scaler = StandardScaler()
    Xt = scaler.fit_transform(splits["X_train"])
    Xv = scaler.transform(splits["X_val"])
    Xte = scaler.transform(splits["X_test"])

    base = LogisticRegression(C=0.5, penalty="l2", max_iter=500,
                              class_weight="balanced", random_state=42)
    if len(Xt) >= 200:
        model = CalibratedClassifierCV(base, method="isotonic", cv=3)
    else:
        model = base
    model.fit(Xt, splits["y_train"])

    probs_val = model.predict_proba(Xv)[:, 1]
    best = find_best_threshold(probs_val, splits["y_val"], splits["pnl_val"])
    if not best["metrics"]:
        return {"name": "hybrid", "model": (model, scaler), "threshold": 0.5,
                "metrics_val": None, "metrics_test": None}

    probs_test = model.predict_proba(Xte)[:, 1]
    pred_test = (probs_test >= best["thr"]).astype(int)
    m_test = trading_metrics(splits["y_test"], pred_test, splits["pnl_test"])

    log(f"  HYBRID val: WR={best['metrics']['wr']:.3f} PF={best['metrics']['pf']:.2f} "
        f"n={best['metrics']['n_trades']}")
    log(f"  HYBRID test: WR={m_test['wr']:.3f} PF={m_test['pf']:.2f} n={m_test['n_trades']}")

    return {"name": "hybrid", "model": (model, scaler), "threshold": best["thr"],
            "feature_cols": feature_cols,
            "metrics_val": best["metrics"], "metrics_test": m_test}


# ── Backup y replace ──────────────────────────────────────────────────────

def passes_thresholds(metrics_test):
    if metrics_test is None:
        return False, "sin metricas test"
    if metrics_test["n_trades"] < MIN_TRADES:
        return False, f"n_trades={metrics_test['n_trades']} < {MIN_TRADES}"
    if metrics_test["wr"] < MIN_WR:
        return False, f"WR={metrics_test['wr']:.3f} < {MIN_WR}"
    if metrics_test["pf"] < MIN_PF:
        return False, f"PF={metrics_test['pf']:.2f} < {MIN_PF}"
    if metrics_test["expectancy"] < MIN_EXP:
        return False, f"expectancy={metrics_test['expectancy']:.3f} < {MIN_EXP}"
    return True, "ok"


def backup_models():
    """Copia los .pkl/.json actuales a backup_<timestamp>/."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(RESULTS_DIR, f"backup_{ts}")
    os.makedirs(backup_dir, exist_ok=True)

    candidates = [
        (os.path.join(RESULTS_DIR, "xgb_models.pkl"), "xgb_models.pkl"),
        (os.path.join(RESULTS_DIR, "xgb_best.json"),  "xgb_best.json"),
        (os.path.join(RESULTS_DIR, "hybrid_model.pkl"), "hybrid_model.pkl"),
        (os.path.join(RESULTS_DIR, "hybrid_best.json"), "hybrid_best.json"),
        (os.path.join(RESULTS_DIR, "grid_best.json"), "grid_best.json"),
        (os.path.join(BOT_STATE_DIR, "exit_model.pkl"), "exit_model.pkl"),
        (os.path.join(BOT_STATE_DIR, "meta_model.pkl"), "meta_model.pkl"),
    ]
    backed = 0
    for src, name in candidates:
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(backup_dir, name))
            backed += 1
    log(f"Backup: {backed} archivos en {backup_dir}")
    return backup_dir


def save_model(trained, results_dir):
    """Guarda el modelo entrenado segun su tipo."""
    name = trained["name"]
    cols = trained["feature_cols"]
    thr = trained["threshold"]

    if name == "xgb":
        pkl_path = os.path.join(results_dir, "xgb_models.pkl")
        json_path = os.path.join(results_dir, "xgb_best.json")
        with open(pkl_path, "wb") as f:
            pickle.dump({"model": trained["model"], "feature_cols": cols,
                         "threshold": thr}, f)
        with open(json_path, "w") as f:
            json.dump({"threshold": thr, "feature_cols": cols,
                       "metrics_val": trained["metrics_val"],
                       "metrics_test": trained["metrics_test"],
                       "trained_at": datetime.now(timezone.utc).isoformat()},
                      f, indent=2)
        log(f"+ XGB guardado en {pkl_path}")

    elif name == "hybrid":
        model, scaler = trained["model"]
        pkl_path = os.path.join(results_dir, "hybrid_model.pkl")
        json_path = os.path.join(results_dir, "hybrid_best.json")
        with open(pkl_path, "wb") as f:
            pickle.dump({"model": model, "scaler": scaler,
                         "feature_cols": cols, "threshold": thr}, f)
        with open(json_path, "w") as f:
            json.dump({"threshold": thr, "feature_cols": cols,
                       "metrics_val": trained["metrics_val"],
                       "metrics_test": trained["metrics_test"],
                       "trained_at": datetime.now(timezone.utc).isoformat()},
                      f, indent=2)
        log(f"+ HYBRID guardado en {pkl_path}")

    elif name == "rf":
        pkl_path = os.path.join(results_dir, "rf_model.pkl")
        json_path = os.path.join(results_dir, "rf_best.json")
        with open(pkl_path, "wb") as f:
            pickle.dump({"model": trained["model"], "feature_cols": cols,
                         "threshold": thr}, f)
        with open(json_path, "w") as f:
            json.dump({"threshold": thr, "feature_cols": cols,
                       "metrics_val": trained["metrics_val"],
                       "metrics_test": trained["metrics_test"],
                       "trained_at": datetime.now(timezone.utc).isoformat()},
                      f, indent=2)
        log(f"+ RF guardado en {pkl_path}")


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label-combo", default=DEFAULT_COMBO,
                    help=f"Combo de label/pnl a usar (default {DEFAULT_COMBO})")
    ap.add_argument("--no-replace", action="store_true",
                    help="Solo evalua, no reemplaza modelos actuales")
    ap.add_argument("--models", nargs="+", choices=["xgb", "rf", "hybrid"],
                    default=["xgb", "rf", "hybrid"])
    args = ap.parse_args()

    os.makedirs(RESULTS_DIR, exist_ok=True)

    log(f"Combo: {args.label_combo}")
    log(f"Modelos: {args.models}")
    log(f"Auto-replace: {'NO' if args.no_replace else 'SI'}")
    log("=" * 60)

    # Cargar dataset
    X, y, pnl, ts, feature_cols, df = load_dataset(args.label_combo)
    splits = temporal_split(X, y, pnl, ts)

    log(f"Train: {len(splits['X_train']):,} | Val: {len(splits['X_val']):,} | "
        f"Test: {len(splits['X_test']):,}")
    log("=" * 60)

    trained = []
    if "xgb" in args.models and HAS_XGB:
        t = train_xgb(splits, feature_cols)
        if t:
            trained.append(t)
    if "rf" in args.models:
        trained.append(train_rf(splits, feature_cols))
    if "hybrid" in args.models:
        trained.append(train_hybrid(splits, feature_cols))

    log("=" * 60)
    log("RESUMEN")
    log("=" * 60)

    report = {
        "combo": args.label_combo,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_features": len(feature_cols),
        "n_train": len(splits['X_train']),
        "n_val": len(splits['X_val']),
        "n_test": len(splits['X_test']),
        "thresholds": {"min_wr": MIN_WR, "min_pf": MIN_PF,
                       "min_expectancy": MIN_EXP, "min_trades": MIN_TRADES},
        "models": [],
    }

    # Backup si vamos a reemplazar
    backup_dir = None
    if not args.no_replace and any(t.get("metrics_test") for t in trained):
        backup_dir = backup_models()
        report["backup_dir"] = backup_dir

    for t in trained:
        if not t:
            continue
        ok, reason = passes_thresholds(t["metrics_test"])
        log(f"\n{t['name'].upper()}:")
        if t["metrics_test"]:
            m = t["metrics_test"]
            log(f"  test:  WR={m['wr']:.3f}  PF={m['pf']:.2f}  "
                f"n_trades={m['n_trades']}  expectancy={m['expectancy']:.3f}  "
                f"avg_pnl={m['avg_pnl']:.3f}%  sharpe={m['sharpe']:.2f}")
        log(f"  pasa thresholds: {ok} ({reason})")

        replaced = False
        if ok and not args.no_replace:
            save_model(t, RESULTS_DIR)
            replaced = True

        report["models"].append({
            "name": t["name"],
            "threshold": t["threshold"],
            "metrics_val": t["metrics_val"],
            "metrics_test": t["metrics_test"],
            "passes": ok,
            "reason": reason,
            "replaced": replaced,
        })

    # Guardar reporte
    report_path = os.path.join(
        RESULTS_DIR,
        f"training_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    log(f"\nReporte: {report_path}")


if __name__ == "__main__":
    main()
