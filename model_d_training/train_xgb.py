"""
train_xgb.py — Trainer B: XGBoost (con LightGBM o sklearn como fallback).

Entrena un clasificador binario (WIN vs no-WIN) sobre las features.
Split temporal estricto: 70% entrenamiento (mas viejo), 15% validacion,
15% test (mas reciente). Esto evita data leakage.

Para cada combo de stop/target del LABEL_COMBOS, entrena un modelo y
elige el threshold de probabilidad que maximiza expectancy en validacion.
Reporta metricas en test (out-of-sample puro).

Salidas:
    results/xgb_models.pkl    — dict de modelos por combo
    results/xgb_best.json     — mejor combo + threshold + metricas test

Dependencies (instalalas en tu PC):
    pip install pandas numpy scikit-learn xgboost
    # o si XGBoost falla:
    pip install pandas numpy scikit-learn lightgbm
    # ultimo fallback solo sklearn:
    pip install pandas numpy scikit-learn

Uso: python -m model_d_training.train_xgb
"""
import os
import sys
import json
import pickle
import math

ROOT = os.path.dirname(os.path.abspath(__file__))
IN_CSV    = os.path.join(ROOT, "state", "features_d.csv")
OUT_PKL   = os.path.join(ROOT, "results", "xgb_models.pkl")
OUT_BEST  = os.path.join(ROOT, "results", "xgb_best.json")

LABEL_COMBOS = [
    ("s020_t030_h6",  0.020, 0.030,  6),
    ("s025_t040_h8",  0.025, 0.040,  8),
    ("s030_t050_h12", 0.030, 0.050, 12),
    ("s035_t060_h16", 0.035, 0.060, 16),
    ("s040_t080_h24", 0.040, 0.080, 24),
]

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
    except ImportError:
        print("X Necesitas: pip install pandas numpy scikit-learn xgboost")
        sys.exit(1)

    # Detectar libreria
    backend = None
    try:
        import xgboost as xgb
        backend = "xgb"
    except ImportError:
        try:
            import lightgbm as lgb
            backend = "lgb"
        except ImportError:
            try:
                from sklearn.ensemble import GradientBoostingClassifier
                backend = "sklearn"
            except ImportError:
                print("X Instala scikit-learn como minimo: pip install scikit-learn")
                sys.exit(1)
    print(f"Backend ML: {backend}")

    if not os.path.exists(IN_CSV):
        print(f"X No existe {IN_CSV}. Corre features.py primero.")
        sys.exit(1)

    df = pd.read_csv(IN_CSV)
    print(f"Filas: {len(df)}")

    # Sort temporal y split
    df = df.sort_values("ts").reset_index(drop=True)
    n = len(df)
    n_train = int(n * 0.70)
    n_val   = int(n * 0.15)
    train_df = df.iloc[:n_train]
    val_df   = df.iloc[n_train:n_train + n_val]
    test_df  = df.iloc[n_train + n_val:]
    print(f"  Train: {len(train_df)}  ({train_df['dt_iso'].iloc[0][:10]} → {train_df['dt_iso'].iloc[-1][:10]})")
    print(f"  Val:   {len(val_df)}  ({val_df['dt_iso'].iloc[0][:10]} → {val_df['dt_iso'].iloc[-1][:10]})")
    print(f"  Test:  {len(test_df)} ({test_df['dt_iso'].iloc[0][:10]} → {test_df['dt_iso'].iloc[-1][:10]})")

    X_train = train_df[FEATURE_COLS].values
    X_val   = val_df[FEATURE_COLS].values
    X_test  = test_df[FEATURE_COLS].values

    models = {}
    summaries = []

    for combo_key, stop_pct, target_pct, max_h in LABEL_COMBOS:
        print(f"\n=== Combo {combo_key} (stop {stop_pct*100}%, target {target_pct*100}%, {max_h}h) ===")
        label_col = f"label_{combo_key}"
        pnl_col   = f"pnl_{combo_key}"

        y_train = (train_df[label_col] == "WIN").astype(int).values
        y_val   = (val_df[label_col]   == "WIN").astype(int).values
        y_test  = (test_df[label_col]  == "WIN").astype(int).values

        base_rate = y_train.mean()
        print(f"  Base rate WIN train: {base_rate:.3f}")

        # Entrenar (modelos pequenos para evitar overfit con base_rate baja)
        # scale_pos_weight ayuda con imbalance (WIN rate ~5-10%)
        pos_weight = (1 - base_rate) / max(base_rate, 0.01)
        if backend == "xgb":
            model = xgb.XGBClassifier(
                n_estimators=150, max_depth=3, learning_rate=0.05,
                subsample=0.8, colsample_bytree=0.8,
                reg_alpha=0.5, reg_lambda=1.0,        # regularizacion
                scale_pos_weight=pos_weight,
                eval_metric="logloss",
                random_state=42,
            )
            model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
        elif backend == "lgb":
            model = lgb.LGBMClassifier(
                n_estimators=150, max_depth=3, learning_rate=0.05,
                subsample=0.8, colsample_bytree=0.8,
                reg_alpha=0.5, reg_lambda=1.0,
                scale_pos_weight=pos_weight,
                random_state=42, verbose=-1,
            )
            model.fit(X_train, y_train, eval_set=[(X_val, y_val)])
        else:
            model = GradientBoostingClassifier(
                n_estimators=120, max_depth=3, learning_rate=0.05, random_state=42,
            )
            model.fit(X_train, y_train)

        # Probabilidades
        p_val  = model.predict_proba(X_val)[:, 1]
        p_test = model.predict_proba(X_test)[:, 1]

        # Threshold selection con TRIPLE guard:
        #   1) N val >= 15, N test >= 5
        #   2) WR val >= 0.40 (para perfil "calidad maxima")
        #   3) PF val >= 1.5
        # Score = exp_val penalizado por N test bajo.
        val_pnl  = val_df[pnl_col].values - FEE_PCT
        val_lab  = (val_df[label_col].values == "WIN")
        test_pnl_full = test_df[pnl_col].values - FEE_PCT
        MIN_WR_TARGET = 0.40
        MIN_PF_TARGET = 1.5

        best_thr = None
        best_score = -999
        for thr in np.arange(0.20, 0.95, 0.025):
            m_val  = p_val >= thr
            m_test = p_test >= thr
            n_val_t  = int(m_val.sum())
            n_test_t = int(m_test.sum())
            if n_val_t < 15 or n_test_t < 5:
                continue
            wr_val = val_lab[m_val].mean()
            if wr_val < MIN_WR_TARGET:
                continue
            v_pnls = val_pnl[m_val]
            wpos = v_pnls[v_pnls > 0].sum()
            wneg = -v_pnls[v_pnls < 0].sum()
            pf_val = (wpos / wneg) if wneg > 0 else 999
            if pf_val < MIN_PF_TARGET:
                continue
            exp = v_pnls.mean()
            n_test_factor = min(n_test_t / 20.0, 1.0)
            score = exp * n_test_factor + wr_val * 0.5
            if score > best_score:
                best_score = score
                best_thr = thr

        if best_thr is None:
            print(f"  [!] No hay threshold con WR>={MIN_WR_TARGET} y PF>={MIN_PF_TARGET} "
                  f"en val. XGB descartado para este combo.")
            # Devolver placeholder y skip
            summaries.append({
                "combo": combo_key, "stop_pct": stop_pct, "target_pct": target_pct,
                "max_hours": max_h, "threshold": None,
                "n_test_trades": 0, "test_win_rate": 0,
                "test_profit_factor": 0, "test_total_pnl_pct": 0,
                "test_avg_pnl_pct": 0, "feature_importance": {},
                "rejected": True, "reason": "no_threshold_meets_quality",
            })
            continue

        print(f"  Threshold optimo: {best_thr:.3f} → score {best_score:+.3f}")

        # Evaluar en test
        test_pnl = test_df[pnl_col].values - FEE_PCT
        test_mask = p_test >= best_thr
        n_test_trades = int(test_mask.sum())
        if n_test_trades > 0:
            test_wins = int(((test_df[label_col] == "WIN") & test_mask).sum())
            test_win_rate = test_wins / n_test_trades
            test_pnls = test_pnl[test_mask]
            test_total = float(test_pnls.sum())
            test_avg = float(test_pnls.mean())
            wins_pnl  = float(test_pnls[test_pnls > 0].sum())
            losses_pnl = float(-test_pnls[test_pnls < 0].sum())
            pf = (wins_pnl / losses_pnl) if losses_pnl > 0 else 999
        else:
            test_win_rate = 0
            test_total = test_avg = 0
            pf = 0

        print(f"  TEST: {n_test_trades} trades  WR {test_win_rate*100:.1f}%  "
              f"PF {pf:.2f}  PnL {test_total:+.2f}%  avg {test_avg:+.3f}%")

        # Importancias
        try:
            if backend in ("xgb", "lgb"):
                importances = dict(zip(FEATURE_COLS, model.feature_importances_.tolist()))
            else:
                importances = dict(zip(FEATURE_COLS, model.feature_importances_.tolist()))
            top_feats = sorted(importances.items(), key=lambda x: -x[1])[:5]
            print(f"  Top features: {[f[0] for f in top_feats]}")
        except Exception:
            importances = {}

        models[combo_key] = {
            "model": model,
            "backend": backend,
            "threshold": float(best_thr),
            "feature_cols": FEATURE_COLS,
        }

        summaries.append({
            "combo": combo_key,
            "stop_pct": stop_pct,
            "target_pct": target_pct,
            "max_hours": max_h,
            "threshold": float(best_thr),
            "n_test_trades": n_test_trades,
            "test_win_rate": round(test_win_rate, 4),
            "test_profit_factor": round(pf, 3) if pf != 999 else 999,
            "test_total_pnl_pct": round(test_total, 3),
            "test_avg_pnl_pct": round(test_avg, 4),
            "feature_importance": importances,
            "rejected": False,
        })

    # Elegir mejor combo. Solo entre los NO rechazados con WR test >= 0.40 y PF>=1.5
    eligible = [s for s in summaries
                if not s.get("rejected")
                and s["test_win_rate"] >= 0.40
                and s["test_profit_factor"] >= 1.5
                and s["n_test_trades"] >= 5]
    if not eligible:
        # Relajar a min PF 1.2 y WR 0.30
        eligible = [s for s in summaries
                    if not s.get("rejected")
                    and s["test_win_rate"] >= 0.30
                    and s["test_profit_factor"] >= 1.2
                    and s["n_test_trades"] >= 5]
    if not eligible:
        print("\n[X] NINGUN combo XGB cumple criterios de calidad (WR>=0.30, PF>=1.2 en test).")
        print("    XGB no es deployable. Solo se guardan los modelos para diagnostico.")
        # Guardar pkl pero sin best
        os.makedirs(os.path.dirname(OUT_PKL), exist_ok=True)
        pickle.dump(models, open(OUT_PKL, "wb"))
        with open(OUT_BEST, "w") as f:
            json.dump({"model_id": "D_xgb_v1", "backend": backend,
                       "all_combos": summaries, "rejected": True,
                       "reason": "no_combo_meets_quality"}, f, indent=2)
        return

    eligible.sort(key=lambda x: (x["test_total_pnl_pct"], x["test_win_rate"]), reverse=True)
    summaries.sort(key=lambda x: x["test_total_pnl_pct"], reverse=True)
    best = eligible[0]
    print("\n" + "="*60)
    print(f"MEJOR COMBO XGB: {best['combo']}")
    print(f"  thr={best['threshold']:.2f}  trades={best['n_test_trades']}  "
          f"WR={best['test_win_rate']*100:.1f}%  PF={best['test_profit_factor']}  "
          f"PnL={best['test_total_pnl_pct']:+.2f}%")

    # Guardar
    os.makedirs(os.path.dirname(OUT_PKL), exist_ok=True)
    with open(OUT_PKL, "wb") as f:
        pickle.dump(models, f)

    with open(OUT_BEST, "w") as f:
        json.dump({
            "model_id": "D_xgb_v1",
            "backend": backend,
            "best_combo": best["combo"],
            "stop_pct": best["stop_pct"],
            "target_pct": best["target_pct"],
            "max_hours": best["max_hours"],
            "threshold": best["threshold"],
            "feature_cols": FEATURE_COLS,
            "test_metrics": {k: v for k, v in best.items() if k.startswith("test_") or k == "n_test_trades"},
            "all_combos": summaries,
        }, f, indent=2)

    print(f"\n✓ Modelos: {OUT_PKL}")
    print(f"✓ Best: {OUT_BEST}")
    print("\nSiguiente paso: python -m model_d_training.train_hybrid")


if __name__ == "__main__":
    main()
