"""
train_hybrid.py — Trainer C: Hibrido grid + logistic regression.

Idea:
    1) Aplica los filtros del best grid (results/grid_best.json) para
       obtener un subset de candidatos "buenos por reglas".
    2) Sobre ese subset, entrena una logistic regression con calibracion
       isotonica que decide si TOMAR o SALTARSE la senal.
    3) Threshold elegido en validacion para maximizar expectancy.

Ventajas:
    * Interpretable (puedes ver coeficientes)
    * Combina criterio humano (reglas) con ML
    * Bajo overfit (LR es simple)

Salidas:
    results/hybrid_model.pkl
    results/hybrid_best.json

Uso: python -m model_d_training.train_hybrid
"""
import os
import sys
import json
import pickle

ROOT = os.path.dirname(os.path.abspath(__file__))
IN_CSV     = os.path.join(ROOT, "state", "features_d.csv")
GRID_BEST  = os.path.join(ROOT, "results", "grid_best.json")
GRID_TOP   = os.path.join(ROOT, "results", "grid_top.json")
OUT_PKL    = os.path.join(ROOT, "results", "hybrid_model.pkl")
OUT_BEST   = os.path.join(ROOT, "results", "hybrid_best.json")

MIN_FILAS_LR = 100  # minimo para entrenar logistic regression

FEATURE_COLS = [
    "rsi14", "drawdown_7d", "atr_pct", "vol_ratio",
    "mom_4h", "mom_12h", "mom_24h",
    "dist_ma20", "dist_ma50",
    "btc_trend_24h", "btc_dom_proxy", "fng_value",
    "hour_of_day",
]

FEE_PCT = 0.10


def main():
    try:
        import pandas as pd
        import numpy as np
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
        from sklearn.calibration import CalibratedClassifierCV
    except ImportError:
        print("X Necesitas: pip install pandas numpy scikit-learn")
        sys.exit(1)

    if not os.path.exists(IN_CSV):
        print(f"X Falta {IN_CSV}. Corre features.py primero.")
        sys.exit(1)
    if not os.path.exists(GRID_BEST):
        print(f"X Falta {GRID_BEST}. Corre train_grid.py primero.")
        sys.exit(1)

    grid = json.load(open(GRID_BEST))
    df = pd.read_csv(IN_CSV).sort_values("ts").reset_index(drop=True)

    def apply_filters(df_, filt):
        return (
            (df_["rsi14"]         <= filt["rsi_max"]) &
            (df_["drawdown_7d"]   <= filt["drawdown_min"]) &
            (df_["fng_value"]     <= filt["fng_max"]) &
            (df_["btc_dom_proxy"] <= filt["btc_dom_max"]) &
            (df_["mom_4h"]        >= filt["mom_4h_min"]) &
            (df_["vol_ratio"]     >= filt["vol_ratio_min"])
        )

    # Intento 1: filtros del grid winner
    f = grid["filters"]
    combo_key = grid["trade"]
    mask = apply_filters(df, f)
    sub = df[mask].copy()
    print(f"Intento 1 — filtros grid winner: {len(sub)}/{len(df)} filas")
    print(f"  filtros: {f}")
    print(f"  combo:   {combo_key}")

    # Intento 2: buscar cluster mas amplio en grid_top.json
    if len(sub) < MIN_FILAS_LR and os.path.exists(GRID_TOP):
        print(f"\n[!] Subset muy chico ({len(sub)} < {MIN_FILAS_LR}). Buscando alternativa en grid_top.json...")
        top = json.load(open(GRID_TOP))
        # Filtrar candidatos con expectancy positiva y mas trades
        candidates = sorted(
            [c for c in top if c.get("expectancy", 0) > 0 and c.get("profit_factor", 0) > 1.0],
            key=lambda c: -c["n_trades"]
        )
        for c in candidates:
            alt_f = {
                "rsi_max":       c["rsi_max"],
                "drawdown_min":  c["drawdown_min"],
                "fng_max":       c["fng_max"],
                "btc_dom_max":   c["btc_dom_max"],
                "mom_4h_min":    c["mom_4h_min"],
                "vol_ratio_min": c["vol_ratio_min"],
            }
            alt_mask = apply_filters(df, alt_f)
            n = int(alt_mask.sum())
            if n >= MIN_FILAS_LR:
                f = alt_f
                combo_key = {"stop_pct": c["stop_pct"], "target_pct": c["target_pct"], "max_hours": c["max_hours"]}
                sub = df[alt_mask].copy()
                print(f"  → Usando alt: n={n}  PF={c['profit_factor']}  combo={c['combo']}")
                print(f"  filtros alt: {f}")
                break

    # Intento 3: fallback Modelo D base (filtros laxos)
    if len(sub) < MIN_FILAS_LR:
        print(f"\n[!] Sin candidato del grid_top con N>={MIN_FILAS_LR}. Fallback a filtro Modelo D base.")
        f = {"rsi_max": 40, "drawdown_min": -5, "fng_max": 50,
             "btc_dom_max": 100, "mom_4h_min": -100, "vol_ratio_min": 0}
        combo_key = {"stop_pct": 0.025, "target_pct": 0.04, "max_hours": 8}
        mask = apply_filters(df, f)
        sub = df[mask].copy()
        print(f"  → fallback: {len(sub)} filas con filtros base")

    if len(sub) < 50:
        print(f"X Aun con fallback solo hay {len(sub)} filas. Necesitas mas datos historicos.")
        sys.exit(1)

    print(f"\n=== Entrenando hybrid con {len(sub)} filas ===")
    stop_pct  = combo_key["stop_pct"]
    tgt_pct   = combo_key["target_pct"]
    max_h     = combo_key["max_hours"]
    suffix = f"s{int(stop_pct*1000):03d}_t{int(tgt_pct*1000):03d}_h{max_h}"

    label_col = f"label_{suffix}"
    pnl_col   = f"pnl_{suffix}"

    sub["y"] = (sub[label_col] == "WIN").astype(int)

    # Split temporal
    n = len(sub)
    n_train = int(n * 0.70)
    n_val   = int(n * 0.15)
    train = sub.iloc[:n_train]
    val   = sub.iloc[n_train:n_train + n_val]
    test  = sub.iloc[n_train + n_val:]
    print(f"  Train {len(train)}  Val {len(val)}  Test {len(test)}")

    X_train = train[FEATURE_COLS].values
    X_val   = val[FEATURE_COLS].values
    X_test  = test[FEATURE_COLS].values
    y_train = train["y"].values
    y_val   = val["y"].values

    scaler = StandardScaler().fit(X_train)
    X_train_s = scaler.transform(X_train)
    X_val_s   = scaler.transform(X_val)
    X_test_s  = scaler.transform(X_test)

    # Logistic con regularizacion L2
    base = LogisticRegression(
        C=0.5, max_iter=1000, class_weight="balanced", random_state=42,
    )
    # Calibracion isotonica para que las probabilidades sean realistas
    if len(train) >= 200:
        model = CalibratedClassifierCV(base, method="isotonic", cv=3)
    else:
        model = base
    model.fit(X_train_s, y_train)

    p_val  = model.predict_proba(X_val_s)[:, 1]
    p_test = model.predict_proba(X_test_s)[:, 1]

    # Threshold optimo en val
    val_pnl = val[pnl_col].values - FEE_PCT
    best_thr, best_exp = 0.5, -999
    for thr in np.arange(0.30, 0.95, 0.05):
        m = p_val >= thr
        if m.sum() < 5: continue
        exp = val_pnl[m].mean()
        if exp > best_exp:
            best_exp = exp
            best_thr = thr
    print(f"\n  Threshold optimo (val): {best_thr:.2f}  expectancy {best_exp:+.3f}%")

    # Test
    test_pnl = test[pnl_col].values - FEE_PCT
    test_mask = p_test >= best_thr
    n_t = int(test_mask.sum())
    if n_t > 0:
        wins = ((test[label_col] == "WIN") & test_mask).sum()
        wr = float(wins) / n_t
        pnls = test_pnl[test_mask]
        total = float(pnls.sum())
        avg = float(pnls.mean())
        wpos = float(pnls[pnls > 0].sum())
        wneg = float(-pnls[pnls < 0].sum())
        pf = (wpos / wneg) if wneg > 0 else 999
    else:
        wr = total = avg = 0
        pf = 0

    print(f"  TEST: {n_t} trades  WR {wr*100:.1f}%  PF {pf:.2f}  PnL {total:+.2f}%  avg {avg:+.3f}%")

    # Coeficientes (interpretabilidad)
    if hasattr(model, "coef_"):
        coefs = dict(zip(FEATURE_COLS, model.coef_[0].tolist()))
    else:
        # CalibratedClassifierCV: tomar promedio de los inner LRs
        try:
            inner = [c.estimator if hasattr(c, "estimator") else c.base_estimator
                     for c in model.calibrated_classifiers_]
            coefs_list = [m.coef_[0] for m in inner if hasattr(m, "coef_")]
            if coefs_list:
                avg_coef = np.mean(coefs_list, axis=0)
                coefs = dict(zip(FEATURE_COLS, avg_coef.tolist()))
            else:
                coefs = {}
        except Exception:
            coefs = {}

    if coefs:
        print("\n  Coeficientes (post-scaling):")
        for k, v in sorted(coefs.items(), key=lambda x: -abs(x[1])):
            print(f"    {k:18s}  {v:+.3f}")

    # Guardar
    os.makedirs(os.path.dirname(OUT_PKL), exist_ok=True)
    pickle.dump({
        "model": model,
        "scaler": scaler,
        "threshold": float(best_thr),
        "feature_cols": FEATURE_COLS,
        "grid_filters": f,
        "trade": combo_key,
    }, open(OUT_PKL, "wb"))

    json.dump({
        "model_id": "D_hybrid_v1",
        "grid_filters": f,
        "trade": combo_key,
        "threshold": float(best_thr),
        "feature_cols": FEATURE_COLS,
        "coefficients": coefs,
        "test_metrics": {
            "n_trades": n_t,
            "win_rate": round(wr, 4),
            "profit_factor": round(pf, 3) if pf != 999 else 999,
            "total_pnl_pct": round(total, 3),
            "avg_pnl_pct": round(avg, 4),
        },
    }, open(OUT_BEST, "w"), indent=2)

    print(f"\n✓ Modelo: {OUT_PKL}")
    print(f"✓ Resumen: {OUT_BEST}")
    print("\nSiguiente paso: python -m model_d_training.compare")


if __name__ == "__main__":
    main()
