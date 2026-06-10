"""
Exit Model — clasificador ML para decision "cerrar vs mantener".

FASE 1: recolecta datos mientras el bot corre con reglas.
FASE 2: entrena RandomForest cuando hay >=100 ejemplos.
FASE 3: el modelo complementa las reglas (umbral conservador: p > 0.65).

Flujo:
  1. collect_training_data() -> lista de ejemplos con features + label
  2. evaluate_readiness()    -> cuantos datos hay y si ya es suficiente
  3. train_classifier()      -> entrena y guarda state/exit_model.pkl
  4. predict_exit(features)  -> P(cerrar ahora es mejor) entre 0 y 1

Label de entrenamiento (calculado en retrospectiva):
  Para el snapshot en hora t de un trade cerrado:
    label=1  si pnl_en_t > pnl_final_real  (era mejor cerrar ahi)
    label=0  si pnl_en_t <= pnl_final_real  (era mejor esperar)
"""
import os, sys, pickle
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from bot.logger import log

DB_PATH = os.environ.get(
    "CRYPTO_DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "state", "crypto_predictions.db"),
)
MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "state", "exit_model.pkl"
)

MIN_SAMPLES      = 100   # minimo recomendado para entrenar
MIN_SAMPLES_WARN = 50    # con menos de esto no intentar

# Orden fijo de features (debe mantenerse igual entre entrenamiento e inferencia)
FEATURE_COLS = [
    "elapsed_ratio",       # que tan avanzado esta el trade (0-1)
    "pnl_pct",             # P&L actual
    "pnl_velocity",        # cambio de P&L vs snapshot anterior
    "pnl_accel",           # cambio de velocity (segunda derivada)
    "mfe_drawdown",        # cuanto retrocedio desde el maximo (mfe - pnl)
    "mfe_so_far",          # maximo alcanzado hasta ahora
    "mae_so_far",          # minimo alcanzado hasta ahora
    "mfe_mae_ratio",       # mfe / |mae|  (perfil riesgo/recompensa)
    "consecutive_down",    # intervalos consecutivos bajando
    "time_positive_ratio", # fraccion del tiempo en positivo
    "pnl_vs_target",       # pnl / target_pct  (que tan cerca del objetivo)
]


def _conn():
    import sqlite3
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


# ── Recoleccion de datos ──────────────────────────────────────────────

def collect_training_data() -> list:
    """
    Extrae ejemplos de entrenamiento de todos los trades cerrados que
    tengan snapshots registrados.

    Retorna lista de dicts: [{"features": {...}, "label": 0|1, "pred_id": int}, ...]
    """
    con = _conn()

    closed = con.execute("""
        SELECT p.*,
               (SELECT COUNT(*) FROM trade_snapshots ts
                WHERE ts.prediction_id = p.id) AS snap_count
        FROM predictions p
        WHERE p.outcome IN ('WIN','LOSS')
          AND p.pnl_pct IS NOT NULL
          AND p.max_hours IS NOT NULL
    """).fetchall()

    rows = []
    for pred in closed:
        if pred["snap_count"] == 0:
            continue

        final_pnl  = pred["pnl_pct"]
        max_hours  = pred["max_hours"]
        entry      = pred["price_at_pred"] or 1
        target_raw = pred["target_price"]
        target_pct = (
            (target_raw - entry) / entry * 100
            if target_raw and entry else 3.0
        )
        target_pct = max(target_pct, 0.1)

        snaps = con.execute(
            "SELECT * FROM trade_snapshots WHERE prediction_id=? ORDER BY elapsed_h",
            (pred["id"],),
        ).fetchall()

        for i, s in enumerate(snaps):
            mfe = s["mfe_so_far"] or 0.0
            mae = s["mae_so_far"] or 0.0
            n   = i + 1

            features = {
                "elapsed_ratio":       round(s["elapsed_h"] / max_hours, 4) if max_hours > 0 else 1.0,
                "pnl_pct":             s["pnl_pct"],
                "pnl_velocity":        s["pnl_velocity"]  if s["pnl_velocity"]  is not None else 0.0,
                "pnl_accel":           s["pnl_accel"]     if s["pnl_accel"]     is not None else 0.0,
                "mfe_drawdown":        round(mfe - s["pnl_pct"], 4),
                "mfe_so_far":          mfe,
                "mae_so_far":          mae,
                "mfe_mae_ratio":       round(mfe / (abs(mae) + 0.001), 4),
                "consecutive_down":    s["consecutive_down"] or 0,
                "time_positive_ratio": round((s["time_positive_cnt"] or 0) / n, 4),
                "pnl_vs_target":       round(s["pnl_pct"] / target_pct, 4),
            }

            # Era mejor cerrar en este snapshot que en el resultado final?
            label = 1 if s["pnl_pct"] > final_pnl else 0

            rows.append({"features": features, "label": label, "pred_id": pred["id"]})

    con.close()
    log("INFO", f"collect_training_data: {len(rows)} ejemplos de {len(closed)} trades cerrados")
    return rows


# ── Estado del modelo ─────────────────────────────────────────────────

def evaluate_readiness() -> dict:
    """
    Verifica cuantos ejemplos de entrenamiento estan disponibles.
    Imprime un resumen y retorna dict con estado.
    """
    data = collect_training_data()
    n    = len(data)
    pos  = sum(1 for d in data if d["label"] == 1)
    neg  = n - pos

    status = {
        "total_examples":  n,
        "positive_labels": pos,
        "negative_labels": neg,
        "balance_ratio":   round(pos / n, 3) if n > 0 else 0,
        "ready_to_train":  n >= MIN_SAMPLES,
        "min_required":    MIN_SAMPLES,
    }

    print(f"\n  ESTADO DEL MODELO DE SALIDA")
    print(f"  Ejemplos disponibles: {n}  (minimo recomendado: {MIN_SAMPLES})")
    if n > 0:
        print(f"  Positivos (cerrar): {pos}  |  Negativos (mantener): {neg}")
        print(f"  Balance: {status['balance_ratio']:.1%} son 'cerrar'")

    if n >= MIN_SAMPLES:
        print(f"  [LISTO] Suficientes datos — ejecuta: train_classifier()")
    elif n >= MIN_SAMPLES_WARN:
        print(f"  [PRONTO] Faltan {MIN_SAMPLES - n} ejemplos mas.")
    else:
        print(f"  [RECOLECTANDO] Necesita {MIN_SAMPLES - n} ejemplos mas.")
    print()
    return status


# ── Entrenamiento ─────────────────────────────────────────────────────

def train_classifier(verbose=True) -> dict | None:
    """
    Entrena un RandomForestClassifier con los datos recolectados.
    Requiere: pip install scikit-learn

    IMPORTANTE: usa GroupKFold para que snapshots del mismo trade
    NUNCA esten en train y test a la vez. Esto evita data leakage
    y da metricas honestas (un train_test_split normal daba 100%
    porque memorizaba trades individuales).

    Guarda el modelo en state/exit_model.pkl.
    Retorna dict con metricas o None si no hay suficientes datos.
    """
    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import GroupKFold
        from sklearn.metrics import accuracy_score, classification_report
        import numpy as np
    except ImportError:
        print("  Error: instala scikit-learn primero:")
        print("    pip install scikit-learn")
        return None

    data = collect_training_data()
    if len(data) < MIN_SAMPLES_WARN:
        print(f"  Insuficientes datos: {len(data)} ejemplos (minimo {MIN_SAMPLES_WARN}).")
        return None

    X      = np.array([[d["features"][col] for col in FEATURE_COLS] for d in data])
    y      = np.array([d["label"] for d in data])
    groups = np.array([d["pred_id"] for d in data])

    n_trades = len(set(groups))
    if n_trades < 5:
        print(f"  Solo {n_trades} trades unicos — necesita minimo 5 para GroupKFold.")
        return None

    # GroupKFold: cada fold tiene trades completos, nunca parciales
    n_splits = min(5, n_trades)
    gkf = GroupKFold(n_splits=n_splits)

    # Evaluar con cross-validation para metricas honestas
    fold_accs = []
    all_y_test = []
    all_y_pred = []

    for train_idx, test_idx in gkf.split(X, y, groups):
        X_tr, X_te = X[train_idx], X[test_idx]
        y_tr, y_te = y[train_idx], y[test_idx]

        clf_fold = RandomForestClassifier(
            n_estimators=100,
            max_depth=6,
            min_samples_leaf=5,
            random_state=42,
            class_weight="balanced",
        )
        clf_fold.fit(X_tr, y_tr)
        y_pred_fold = clf_fold.predict(X_te)

        fold_accs.append(accuracy_score(y_te, y_pred_fold))
        all_y_test.extend(y_te)
        all_y_pred.extend(y_pred_fold)

    cv_acc     = np.mean(fold_accs)
    cv_acc_std = np.std(fold_accs)

    # Entrenar modelo final con TODOS los datos
    clf = RandomForestClassifier(
        n_estimators=100,
        max_depth=6,
        min_samples_leaf=5,
        random_state=42,
        class_weight="balanced",
    )
    clf.fit(X, y)

    importances = sorted(
        zip(FEATURE_COLS, clf.feature_importances_),
        key=lambda x: -x[1],
    )

    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump({
            "model":       clf,
            "features":    FEATURE_COLS,
            "trained_at":  datetime.now().isoformat(),
            "n_samples":   len(data),
            "n_trades":    n_trades,
            "cv_accuracy": round(cv_acc, 4),
            "cv_std":      round(cv_acc_std, 4),
            "importances": importances,
        }, f)

    if verbose:
        print(f"\n  MODELO DE SALIDA ENTRENADO (GroupKFold, {n_splits} folds)")
        print(f"  Muestras: {len(data)}  |  Trades unicos: {n_trades}")
        print(f"  CV Accuracy: {cv_acc:.1%} (+/- {cv_acc_std:.1%})")
        print(f"  Accuracy por fold: {', '.join(f'{a:.1%}' for a in fold_accs)}")
        print(f"\n  Feature importance:")
        for feat, imp in importances:
            bar = "#" * int(imp * 40)
            print(f"    {feat:<24}  {imp:.3f}  {bar}")
        print(f"\n  Reporte de clasificacion (cross-validated):")
        print(classification_report(all_y_test, all_y_pred, target_names=["HOLD", "EXIT"]))
        print(f"  Modelo guardado en: {MODEL_PATH}")

        if cv_acc < 0.55:
            print(f"\n  [AVISO] Accuracy {cv_acc:.0%} es casi aleatorio.")
            print(f"  El modelo necesita mas trades diversos para aprender patrones.")
            print(f"  Recomendacion: acumular 50+ trades y re-entrenar.\n")
        elif cv_acc < 0.65:
            print(f"\n  [OK] Accuracy {cv_acc:.0%} es aceptable pero mejorable.")
            print(f"  Usar con umbral alto (0.70+) para evitar falsos positivos.\n")
        else:
            print(f"\n  [BUENO] Accuracy {cv_acc:.0%} — listo para usar con --ml.\n")

    log("INFO", f"exit_model trained: {len(data)} muestras, {n_trades} trades, cv_acc={cv_acc:.1%}")
    return {"cv_accuracy": cv_acc, "n_samples": len(data), "n_trades": n_trades, "importances": importances}


# ── Inferencia ────────────────────────────────────────────────────────


# -- Inferencia --

# Ver meta_model.ACCOUNTING_FIX_DATE: outcomes previos al fix estaban inflados.
ACCOUNTING_FIX_DATE = "2026-06-10"


def load_model() -> dict | None:
    """Carga el modelo entrenado. Retorna None si no existe o si fue
    entrenado con las etiquetas contaminadas previas al fix de contabilidad."""
    if not os.path.exists(MODEL_PATH):
        return None
    try:
        with open(MODEL_PATH, "rb") as f:
            data = pickle.load(f)
        trained_at = (data.get("trained_at") or "")[:10]
        if trained_at < ACCOUNTING_FIX_DATE:
            log("WARN", f"exit_model entrenado {trained_at} con labels contaminadas "
                        f"(pre-fix {ACCOUNTING_FIX_DATE}) — ignorado. Reentrena.")
            return None
        return data
    except Exception as e:
        log("WARN", f"exit_model load error: {e}")
        return None


def predict_exit(features_dict: dict, threshold: float = 0.65) -> tuple:
    """
    Predice si cerrar el trade ahora es optimo.

    threshold: umbral conservador (default 0.65).
               Subir para ser mas permisivo (menos salidas tempranas).
               Bajar para ser mas agresivo (mas salidas tempranas).

    Retorna (decision, probability):
      decision:    "EXIT" | "HOLD" | "NO_MODEL"
      probability: float 0-1, P(cerrar ahora es mejor que esperar)
    """
    model_data = load_model()
    if not model_data:
        return "NO_MODEL", 0.0

    clf       = model_data["model"]
    feat_cols = model_data["features"]

    try:
        x = [[features_dict.get(col, 0.0) for col in feat_cols]]
        proba    = clf.predict_proba(x)[0]
        p_exit   = float(proba[1])          # P(label=1) = P(cerrar es mejor)
        decision = "EXIT" if p_exit >= threshold else "HOLD"
        return decision, round(p_exit, 3)
    except Exception as e:
        log("WARN", f"predict_exit error: {e}")
        return "NO_MODEL", 0.0


# -- Info del modelo cargado --

def show_model_info():
    """Muestra informacion del modelo actualmente entrenado."""
    m = load_model()
    if not m:
        print("  No hay modelo entrenado.")
        print("  Ejecuta: python run_flex_tests.py train")
        return

    print(f"\n  MODELO DE SALIDA")
    print(f"  Entrenado:  {m['trained_at']}")
    print(f"  Muestras:   {m['n_samples']}")
    print(f"  Trades:     {m.get('n_trades', '?')}")
    if "cv_accuracy" in m:
        print(f"  CV Accuracy: {m['cv_accuracy']:.1%} (+/- {m.get('cv_std', 0):.1%})")
    elif "accuracy" in m:
        print(f"  Accuracy:   {m['accuracy']:.1%}  (sin GroupKFold -- re-entrenar)")
    print(f"\n  Top 5 features mas importantes:")
    for feat, imp in m["importances"][:5]:
        bar = "#" * int(imp * 30)
        print(f"    {feat:<24}  {imp:.3f}  {bar}")
    print()
