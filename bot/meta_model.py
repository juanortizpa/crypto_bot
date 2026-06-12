"""
Meta-Modelo — clasificador que aprende de TODOS los modelos (A-F).

En vez de descartar modelos con mal WR, el meta-modelo aprende
CUANDO cada modelo funciona bien segun las condiciones del mercado.

FEATURES (por cada prediccion):
  - 13 factores del gate codificados (GREEN=1, YELLOW=0, RED=-1)
  - gate_score (green_count)
  - red_count
  - modelo usado (one-hot: A, B, C, D, E, F)
  - hora del dia (ciclica: sin/cos para capturar patrones horarios)
  - fear_and_greed (extraido de M2 reason si disponible)

LABEL:
  1 = WIN, 0 = LOSS

USO:
  1. Correr varias sesiones de flex tests para acumular datos
  2. train_meta_model()  -> entrena y guarda state/meta_model.pkl
  3. predict_entry(gate, model_id, hour) -> P(WIN) entre 0 y 1
  4. Usar como filtro: solo abrir trade si P(WIN) > umbral

DIFERENCIA CON exit_model.py:
  - exit_model decide CUANDO CERRAR un trade abierto
  - meta_model decide SI ABRIR el trade en primer lugar
  - Se complementan: meta filtra entrada, exit optimiza salida
"""
import os, sys, json, re, pickle, math
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from bot.logger import log

DB_PATH = os.environ.get(
    "CRYPTO_DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "state", "crypto_predictions.db"),
)
MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "state", "meta_model.pkl"
)

MIN_SAMPLES      = 80    # minimo para entrenar
MIN_SAMPLES_WARN = 40
ALL_MODELS       = ["A", "B", "C", "D", "E", "F"]
GATE_FACTORS     = ["M1", "M2", "M3", "S1", "S2", "S3", "S4", "T1", "T2", "T3", "R1", "R2", "N1"]

# Orden fijo de features
FEATURE_COLS = (
    # 13 gate factors encoded
    [f"gate_{f}" for f in GATE_FACTORS]
    # gate aggregates
    + ["gate_score", "red_count"]
    # model one-hot
    + [f"model_{m}" for m in ALL_MODELS]
    # time features (cyclic)
    + ["hour_sin", "hour_cos"]
    # fear & greed (if available)
    + ["fear_greed"]
    # sentiment score continuo (-1.0 a +1.0)
    + ["sentiment_score"]
)


def _color_to_num(color: str) -> int:
    """GREEN=1, YELLOW=0, RED=-1"""
    if color == "GREEN":
        return 1
    elif color == "RED":
        return -1
    return 0


def _extract_fng(factors_dict: dict) -> float:
    """
    Intenta extraer el valor de Fear & Greed del reason de M2.
    Ejemplo: "F&G 50 (Neutral) — optimista" -> 50
    Si no puede, retorna 50 (neutral).
    """
    m2 = factors_dict.get("M2", {})
    reason = m2.get("reason", "") if isinstance(m2, dict) else str(m2)
    # Try to find "F&G XX" pattern
    match = re.search(r"F&G\s+(\d+)", reason)
    if match:
        return float(match.group(1))
    # If factors_json stores just colors, try the raw text
    match2 = re.search(r"(\d+)", reason)
    if match2:
        val = float(match2.group(1))
        if 0 <= val <= 100:
            return val
    return 50.0


def _conn():
    import sqlite3
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


# ── Feature extraction ───────────────────────────────────────────────

def extract_features(factors_json: str, model_id: str, predicted_at: str,
                     gate_score: int = None) -> dict:
    """
    Extrae features de una prediccion (nueva o historica).

    factors_json: string JSON con los colores del gate
                  puede ser {"M1": "GREEN", ...} o {"M1": {"color": "GREEN", "reason": "..."}, ...}
    model_id: "A" - "F"
    predicted_at: ISO datetime string
    gate_score: green_count (si None, se calcula de factors_json)
    """
    if isinstance(factors_json, str):
        factors = json.loads(factors_json)
    else:
        factors = factors_json

    features = {}

    # 1. Gate factors encoded
    green_count = 0
    red_count = 0
    for f in GATE_FACTORS:
        val = factors.get(f, "YELLOW")
        if isinstance(val, dict):
            color = val.get("color", "YELLOW")
        else:
            color = str(val)
        num = _color_to_num(color)
        features[f"gate_{f}"] = num
        if num == 1:
            green_count += 1
        elif num == -1:
            red_count += 1

    # 2. Gate aggregates
    features["gate_score"] = gate_score if gate_score is not None else green_count
    features["red_count"] = red_count

    # 3. Model one-hot
    for m in ALL_MODELS:
        features[f"model_{m}"] = 1 if m == model_id else 0

    # 4. Hour of day (cyclic encoding)
    try:
        hour = datetime.fromisoformat(predicted_at).hour
    except (ValueError, TypeError):
        hour = 12
    features["hour_sin"] = round(math.sin(2 * math.pi * hour / 24), 4)
    features["hour_cos"] = round(math.cos(2 * math.pi * hour / 24), 4)

    # 5. Fear & Greed
    features["fear_greed"] = _extract_fng(factors)

    # 6. Sentiment score (continuo, -1 a +1)
    features["sentiment_score"] = _extract_sentiment(factors)

    return features


def _extract_sentiment(factors_dict: dict) -> float:
    """
    Extrae score de sentimiento del reason de N1.
    Busca patrones como 'score: +0.250' o '(+0.250)' o simplemente el número.
    Si no puede, intenta obtener sentimiento en vivo.
    Retorna 0.0 como default (neutral).
    """
    n1 = factors_dict.get("N1", {})
    reason = n1.get("reason", "") if isinstance(n1, dict) else str(n1)

    # Buscar score numérico en el reason
    match = re.search(r"([+-]?\d+\.\d+)", reason)
    if match:
        val = float(match.group(1))
        if -1.0 <= val <= 1.0:
            return val

    # Inferir del color si no hay score
    color = n1.get("color", "YELLOW") if isinstance(n1, dict) else "YELLOW"
    if color == "GREEN":
        return 0.3
    elif color == "RED":
        return -0.3
    return 0.0


def extract_features_live(gate, model_id: str, symbol: str = None) -> dict:
    """
    Extrae features de un gate en vivo (GateResult object).
    Para usar en predict_entry() durante una sesion.
    """
    factors_dict = {}
    for name, info in gate.factors.items():
        factors_dict[name] = info  # {"color": ..., "reason": ...}

    features = {}

    # 1. Gate factors
    for f in GATE_FACTORS:
        info = factors_dict.get(f, {"color": "YELLOW"})
        color = info.get("color", "YELLOW") if isinstance(info, dict) else str(info)
        features[f"gate_{f}"] = _color_to_num(color)

    # 2. Aggregates
    features["gate_score"] = gate.green_count
    features["red_count"] = gate.red_count

    # 3. Model one-hot
    for m in ALL_MODELS:
        features[f"model_{m}"] = 1 if m == model_id else 0

    # 4. Hour
    hour = datetime.now().hour
    features["hour_sin"] = round(math.sin(2 * math.pi * hour / 24), 4)
    features["hour_cos"] = round(math.cos(2 * math.pi * hour / 24), 4)

    # 5. Fear & Greed
    features["fear_greed"] = _extract_fng(factors_dict)

    # 6. Sentiment score (en vivo)
    try:
        from bot.sentiment import get_sentiment
        sent = get_sentiment(symbol)
        features["sentiment_score"] = sent.get("score", 0.0)
    except Exception:
        features["sentiment_score"] = _extract_sentiment(factors_dict)

    return features


# ── Training data collection ────────────────────────────────────────

def collect_meta_training_data() -> list:
    """
    Extrae ejemplos de entrenamiento de todas las predicciones cerradas.
    Cada prediccion cerrada = 1 ejemplo (a diferencia del exit_model que
    genera multiples snapshots por trade).

    Retorna lista de dicts: [{"features": {...}, "label": 0|1, "pred_id": int, "model": str}, ...]
    """
    con = _conn()
    # Solo trades cerrados con la contabilidad honesta (post 2026-06-10).
    # Los anteriores tienen labels WIN inflados y contaminarian el modelo
    # (ver AUDITORIA_2026-06-10.md).
    closed = con.execute("""
        SELECT * FROM predictions
        WHERE outcome IN ('WIN', 'LOSS')
          AND factors_json IS NOT NULL
          AND model IS NOT NULL
          AND outcome_date >= ?
    """, (ACCOUNTING_FIX_DATE,)).fetchall()
    con.close()

    rows = []
    for pred in closed:
        label = 1 if pred["outcome"] == "WIN" else 0
        try:
            features = extract_features(
                factors_json=pred["factors_json"],
                model_id=pred["model"],
                predicted_at=pred["predicted_at"],
                gate_score=pred["gate_score"],
            )
        except Exception as e:
            log("WARN", f"meta_model: skip pred #{pred['id']}: {e}")
            continue

        rows.append({
            "features": features,
            "label": label,
            "pred_id": pred["id"],
            "model": pred["model"],
            "pnl_pct": pred["pnl_pct"],
        })

    log("INFO", f"collect_meta_training_data: {len(rows)} ejemplos de {len(closed)} trades")
    return rows


# ── Readiness check ─────────────────────────────────────────────────

def evaluate_meta_readiness() -> dict:
    """Verifica cuantos datos hay para entrenar el meta-modelo."""
    data = collect_meta_training_data()
    n = len(data)
    wins = sum(1 for d in data if d["label"] == 1)
    losses = n - wins

    # Per model breakdown
    model_counts = {}
    for d in data:
        m = d["model"]
        if m not in model_counts:
            model_counts[m] = {"total": 0, "wins": 0}
        model_counts[m]["total"] += 1
        if d["label"] == 1:
            model_counts[m]["wins"] += 1

    status = {
        "total_examples": n,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / n * 100, 1) if n > 0 else 0,
        "ready_to_train": n >= MIN_SAMPLES,
        "per_model": model_counts,
    }

    print(f"\n  ESTADO DEL META-MODELO")
    print(f"  Trades disponibles: {n}  (minimo recomendado: {MIN_SAMPLES})")
    if n > 0:
        print(f"  Wins: {wins}  |  Losses: {losses}  |  WR base: {status['win_rate']:.1f}%")
        print(f"\n  Por modelo:")
        for m in sorted(model_counts.keys()):
            mc = model_counts[m]
            wr = mc["wins"] / mc["total"] * 100 if mc["total"] > 0 else 0
            print(f"    [{m}]  {mc['total']:>4} trades  {wr:>5.1f}% WR")

    if n >= MIN_SAMPLES:
        print(f"\n  [LISTO] Suficientes datos — ejecuta: train_meta_model()")
    elif n >= MIN_SAMPLES_WARN:
        print(f"\n  [PRONTO] Faltan {MIN_SAMPLES - n} ejemplos mas.")
    else:
        print(f"\n  [RECOLECTANDO] Necesita {MIN_SAMPLES - n} ejemplos mas.")
    print()
    return status


# ── Training ────────────────────────────────────────────────────────

def train_meta_model(verbose=True) -> dict | None:
    """
    Entrena un RandomForestClassifier para predecir WIN/LOSS
    basado en condiciones del gate + modelo elegido.

    Usa GroupKFold agrupando por modelo para evitar que el modelo
    simplemente memorice "modelo D = bueno".
    Tambien prueba GroupKFold por pred_id para comparar.
    """
    try:
        from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
        from sklearn.model_selection import GroupKFold, StratifiedKFold
        from sklearn.metrics import accuracy_score, classification_report
        import numpy as np
    except ImportError:
        print("  Error: instala scikit-learn primero:")
        print("    pip install scikit-learn")
        return None

    data = collect_meta_training_data()
    if len(data) < MIN_SAMPLES_WARN:
        print(f"  Insuficientes datos: {len(data)} ejemplos (minimo {MIN_SAMPLES_WARN}).")
        return None

    X = np.array([[d["features"][col] for col in FEATURE_COLS] for d in data])
    y = np.array([d["label"] for d in data])

    # Usar StratifiedKFold para mantener proporcion WIN/LOSS en cada fold
    n_splits = min(5, len(data) // 10)
    if n_splits < 2:
        n_splits = 2
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)

    # Probar dos clasificadores y quedarse con el mejor
    classifiers = {
        "RandomForest": RandomForestClassifier(
            n_estimators=200,
            max_depth=8,
            min_samples_leaf=5,
            random_state=42,
            class_weight="balanced",
        ),
        "GradientBoosting": GradientBoostingClassifier(
            n_estimators=150,
            max_depth=4,
            min_samples_leaf=5,
            learning_rate=0.1,
            random_state=42,
        ),
    }

    best_name = None
    best_acc = 0
    best_results = None

    for clf_name, clf_template in classifiers.items():
        fold_accs = []
        all_y_test = []
        all_y_pred = []
        # OOF (out-of-fold) probabilities para simulacion honesta
        oof_proba = np.zeros(len(y))
        oof_mask  = np.zeros(len(y), dtype=bool)

        for train_idx, test_idx in skf.split(X, y):
            X_tr, X_te = X[train_idx], X[test_idx]
            y_tr, y_te = y[train_idx], y[test_idx]

            from sklearn.base import clone
            clf_fold = clone(clf_template)
            clf_fold.fit(X_tr, y_tr)
            y_pred_fold = clf_fold.predict(X_te)

            # Guardar probabilidades OOF (cada punto solo evaluado por
            # un modelo que NUNCA lo vio en entrenamiento)
            proba_fold = clf_fold.predict_proba(X_te)
            oof_proba[test_idx] = proba_fold[:, 1]
            oof_mask[test_idx] = True

            fold_accs.append(accuracy_score(y_te, y_pred_fold))
            all_y_test.extend(y_te)
            all_y_pred.extend(y_pred_fold)

        cv_acc = np.mean(fold_accs)
        if cv_acc > best_acc:
            best_acc = cv_acc
            best_name = clf_name
            best_results = {
                "fold_accs": fold_accs,
                "all_y_test": all_y_test,
                "all_y_pred": all_y_pred,
                "template": clf_template,
                "oof_proba": oof_proba.copy(),
                "oof_mask": oof_mask.copy(),
            }

    # Entrenar modelo final con todos los datos usando el mejor clasificador
    from sklearn.base import clone
    clf_final = clone(best_results["template"])
    clf_final.fit(X, y)

    cv_acc = best_acc
    cv_std = np.std(best_results["fold_accs"])
    fold_accs = best_results["fold_accs"]

    # Feature importances
    importances = sorted(
        zip(FEATURE_COLS, clf_final.feature_importances_),
        key=lambda x: -x[1],
    )

    # Analizar mejora potencial por modelo
    model_analysis = {}
    for d in data:
        m = d["model"]
        if m not in model_analysis:
            model_analysis[m] = {"total": 0, "wins": 0, "avg_pnl": []}
        model_analysis[m]["total"] += 1
        if d["label"] == 1:
            model_analysis[m]["wins"] += 1
        if d["pnl_pct"] is not None:
            model_analysis[m]["avg_pnl"].append(d["pnl_pct"])

    # Simular filtro con probabilidades OUT-OF-FOLD (honestas).
    # Cada trade es evaluado SOLO por un modelo que nunca lo vio.
    # Esto evita overfitting y da numeros realistas.
    oof_proba = best_results["oof_proba"]
    oof_mask  = best_results["oof_mask"]
    thresholds_analysis = {}
    for threshold in [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]:
        mask = (oof_proba >= threshold) & oof_mask
        if mask.sum() == 0:
            continue
        filtered_y = y[mask]
        filtered_wr = filtered_y.mean() * 100
        filtered_pnl = np.mean([data[i]["pnl_pct"] for i in range(len(data)) if mask[i] and data[i]["pnl_pct"] is not None])
        thresholds_analysis[threshold] = {
            "trades": int(mask.sum()),
            "win_rate": round(filtered_wr, 1),
            "avg_pnl": round(filtered_pnl, 4),
        }

    # Guardar
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump({
            "model": clf_final,
            "classifier_type": best_name,
            "features": FEATURE_COLS,
            "trained_at": datetime.now().isoformat(),
            "n_samples": len(data),
            "cv_accuracy": round(cv_acc, 4),
            "cv_std": round(cv_std, 4),
            "importances": importances,
            "thresholds": thresholds_analysis,
            "model_analysis": {m: {"total": v["total"], "wins": v["wins"],
                                   "wr": round(v["wins"]/v["total"]*100, 1) if v["total"] else 0,
                                   "avg_pnl": round(np.mean(v["avg_pnl"]), 4) if v["avg_pnl"] else 0}
                               for m, v in model_analysis.items()},
        }, f)

    if verbose:
        print(f"\n  META-MODELO ENTRENADO ({best_name}, {n_splits} folds)")
        print(f"  Trades: {len(data)}  |  WR base: {sum(y)/len(y)*100:.1f}%")
        print(f"  CV Accuracy: {cv_acc:.1%} (+/- {cv_std:.1%})")
        print(f"  Accuracy por fold: {', '.join(f'{a:.1%}' for a in fold_accs)}")

        print(f"\n  Top 10 features mas importantes:")
        for feat, imp in importances[:10]:
            bar = "#" * int(imp * 40)
            print(f"    {feat:<24}  {imp:.3f}  {bar}")

        print(f"\n  Reporte de clasificacion (cross-validated):")
        print(classification_report(
            best_results["all_y_test"],
            best_results["all_y_pred"],
            target_names=["LOSS", "WIN"],
        ))

        print(f"  SIMULACION DE FILTRO (out-of-fold, numeros honestos):")
        print(f"  {'Umbral':>8} {'Trades':>8} {'WR':>8} {'Avg P&L':>10}  vs base {sum(y)/len(y)*100:.1f}% WR")
        print(f"  {'-'*42}")
        for thr, info in sorted(thresholds_analysis.items()):
            delta_wr = info["win_rate"] - (sum(y)/len(y)*100)
            print(f"  {thr:>8.2f} {info['trades']:>8} {info['win_rate']:>7.1f}% {info['avg_pnl']:>+9.4f}%  ({delta_wr:+.1f}%)")

        print(f"\n  Modelo guardado en: {MODEL_PATH}")

        if cv_acc < 0.55:
            print(f"\n  [AVISO] Accuracy {cv_acc:.0%} es casi aleatorio.")
            print(f"  Necesita mas trades diversos.\n")
        elif cv_acc < 0.65:
            print(f"\n  [OK] Accuracy {cv_acc:.0%} aceptable. Usar umbral alto (0.60+).\n")
        else:
            print(f"\n  [BUENO] Accuracy {cv_acc:.0%} — listo para filtrar trades.\n")

    log("INFO", f"meta_model trained: {len(data)} trades, {best_name}, cv_acc={cv_acc:.1%}")
    return {
        "cv_accuracy": cv_acc,
        "n_samples": len(data),
        "classifier": best_name,
        "importances": importances,
        "thresholds": thresholds_analysis,
    }


# ── Inference ───────────────────────────────────────────────────────

# Fecha del fix de contabilidad (2026-06-10): antes de esto, los outcomes
# WIN/LOSS estaban inflados (expirado +0.01% = WIN, breakeven = WIN, sin
# path-check). Un modelo entrenado con esas etiquetas aprendio basura y
# NO debe usarse como filtro. Reentrenar con trades posteriores al fix.
ACCOUNTING_FIX_DATE = "2026-06-10"


def load_meta_model() -> dict | None:
    """Carga el meta-modelo entrenado (solo si es posterior al fix de labels)."""
    if not os.path.exists(MODEL_PATH):
        return None
    try:
        with open(MODEL_PATH, "rb") as f:
            data = pickle.load(f)
        trained_at = (data.get("trained_at") or "")[:10]
        if trained_at < ACCOUNTING_FIX_DATE:
            log("WARN", f"meta_model entrenado {trained_at} con labels contaminadas "
                        f"(pre-fix {ACCOUNTING_FIX_DATE}) — ignorado. Reentrena.")
            return None
        return data
    except Exception as e:
        log("WARN", f"meta_model load error: {e}")
        return None


def predict_entry(gate, model_id: str, threshold: float = 0.55,
                  symbol: str = None) -> tuple:
    """
    Predice si un trade sera WIN o LOSS basado en condiciones actuales.

    gate: GateResult object (del gate en vivo)
    model_id: "A" - "F"
    threshold: umbral para aprobar (default 0.55 = ligeramente selectivo)
    symbol: par de trading (para obtener sentimiento específico)

    Retorna (decision, probability):
      decision:    "APPROVE" | "REJECT" | "NO_MODEL"
      probability: float 0-1, P(WIN)
    """
    model_data = load_meta_model()
    if not model_data:
        return "NO_MODEL", 0.0

    clf = model_data["model"]
    feat_cols = model_data["features"]

    try:
        features = extract_features_live(gate, model_id, symbol=symbol)
        x = [[features.get(col, 0.0) for col in feat_cols]]
        proba = clf.predict_proba(x)[0]
        p_win = float(proba[1])  # P(label=1) = P(WIN)
        decision = "APPROVE" if p_win >= threshold else "REJECT"
        return decision, round(p_win, 3)
    except Exception as e:
        log("WARN", f"predict_entry error: {e}")
        return "NO_MODEL", 0.0


# ── Model info ──────────────────────────────────────────────────────

def show_meta_info():
    """Muestra informacion del meta-modelo entrenado."""
    m = load_meta_model()
    if not m:
        print("  No hay meta-modelo entrenado.")
        print("  Ejecuta: python run_flex_tests.py train-meta")
        return

    print(f"\n  META-MODELO DE ENTRADA")
    print(f"  Tipo:       {m.get('classifier_type', '?')}")
    print(f"  Entrenado:  {m['trained_at']}")
    print(f"  Trades:     {m['n_samples']}")
    if "cv_accuracy" in m:
        print(f"  CV Accuracy: {m['cv_accuracy']:.1%} (+/- {m.get('cv_std', 0):.1%})")

    print(f"\n  Top 5 features:")
    for feat, imp in m["importances"][:5]:
        bar = "#" * int(imp * 30)
        print(f"    {feat:<24}  {imp:.3f}  {bar}")

    if "thresholds" in m:
        print(f"\n  Umbrales de filtro:")
        for thr, info in sorted(m["thresholds"].items()):
            print(f"    P(WIN)>{thr:.2f}:  {info['trades']} trades  {info['win_rate']:.1f}% WR  {info['avg_pnl']:+.4f}%")

    if "model_analysis" in m:
        print(f"\n  WR base por modelo:")
        for mid, info in sorted(m["model_analysis"].items()):
            print(f"    [{mid}]  {info['total']:>4} trades  {info['wr']:>5.1f}% WR  {info['avg_pnl']:+.4f}%")
    print()
