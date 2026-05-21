"""
compare.py — Walk-forward comparativo + ensemble de los 3 modelos.

Toma los 3 modelos entrenados:
    - grid_best.json    (Trainer A: solo reglas)
    - xgb_best.json     (Trainer B: ML puro)
    - hybrid_best.json  (Trainer C: reglas + LR)

Para los ULTIMOS 30 DIAS del dataset (out-of-sample para los 3),
calcula:
    - n_trades, win_rate, profit_factor, expectancy
    - total_pnl, max_drawdown, avg_hold_hours
    - correlacion de senales entre modelos

Y prueba ensembles:
    - majority_2of3  (al menos 2 modelos coinciden)
    - any_of_3       (cualquiera dispara — agresivo)
    - all_3          (los 3 coinciden — muy conservador)
    - prob_avg       (XGB + Hybrid: promedio de probs >= 0.55)

Salida final:
    results/comparison.json   — ranking + recomendacion
    results/winner_config.json — config para meter en live (best individual o ensemble)

Uso: python -m model_d_training.compare
"""
import os
import sys
import json
import pickle
import math

ROOT = os.path.dirname(os.path.abspath(__file__))
IN_CSV       = os.path.join(ROOT, "state", "features_d.csv")
GRID_BEST    = os.path.join(ROOT, "results", "grid_best.json")
XGB_BEST     = os.path.join(ROOT, "results", "xgb_best.json")
XGB_PKL      = os.path.join(ROOT, "results", "xgb_models.pkl")
HYBRID_BEST  = os.path.join(ROOT, "results", "hybrid_best.json")
HYBRID_PKL   = os.path.join(ROOT, "results", "hybrid_model.pkl")
OUT_COMP     = os.path.join(ROOT, "results", "comparison.json")
OUT_WINNER   = os.path.join(ROOT, "results", "winner_config.json")

FEE_PCT = 0.10

# Ultimos 30 dias = ~720 bars (1h)
HOURS_OOS = 30 * 24


def need(p):
    if not os.path.exists(p):
        print(f"X Falta {p}. Asegurate de correr todos los trainers primero.")
        sys.exit(1)

def have(p):
    return os.path.exists(p)


def main():
    try:
        import pandas as pd
        import numpy as np
    except ImportError:
        print("X pip install pandas numpy")
        sys.exit(1)

    # Required: grid + xgb + csv. Hybrid es opcional.
    need(IN_CSV); need(GRID_BEST); need(XGB_BEST); need(XGB_PKL)
    has_hybrid = have(HYBRID_BEST) and have(HYBRID_PKL)
    if not has_hybrid:
        print("[!] No se encontro hybrid_best.json/hybrid_model.pkl — corriendo sin Trainer C.")

    df = pd.read_csv(IN_CSV).sort_values("ts").reset_index(drop=True)

    # OOS = ultimas N horas
    last_ts = df["ts"].max()
    oos = df[df["ts"] >= last_ts - HOURS_OOS * 3600].copy()
    print(f"OOS window: {len(oos)} filas, "
          f"{oos['dt_iso'].iloc[0][:10]} → {oos['dt_iso'].iloc[-1][:10]}")

    if len(oos) < 50:
        print("X OOS muy chica. Necesitas mas datos descargados.")
        sys.exit(1)

    grid    = json.load(open(GRID_BEST))
    xgb_b   = json.load(open(XGB_BEST))
    xgb_models = pickle.load(open(XGB_PKL, "rb"))

    # XGB puede estar marcado como rejected (no cumplio calidad). En ese caso
    # corremos sin Trainer B.
    has_xgb = not xgb_b.get("rejected", False) and "feature_cols" in xgb_b
    if not has_xgb:
        reason = xgb_b.get("reason", "no_feature_cols")
        print(f"[!] XGB descartado ({reason}) — corriendo sin Trainer B.")

    if has_hybrid:
        hyb_b   = json.load(open(HYBRID_BEST))
        hyb_pkg = pickle.load(open(HYBRID_PKL, "rb"))
    else:
        hyb_b = None
        hyb_pkg = None

    # FEATURE_COLS: priorizar xgb (si valido), luego hybrid, luego default
    if has_xgb:
        FEATURE_COLS = xgb_b["feature_cols"]
    elif has_hybrid:
        FEATURE_COLS = hyb_pkg.get("feature_cols", [
            "rsi14","drawdown_7d","atr_pct","vol_ratio","mom_4h","mom_12h","mom_24h",
            "dist_ma20","dist_ma50","btc_trend_24h","btc_dom_proxy","fng_value","hour_of_day"
        ])
    else:
        FEATURE_COLS = ["rsi14","drawdown_7d","atr_pct","vol_ratio","mom_4h","mom_12h","mom_24h",
                        "dist_ma20","dist_ma50","btc_trend_24h","btc_dom_proxy","fng_value","hour_of_day"]

    # === Trainer A — Grid puro ===
    f = grid["filters"]
    sig_grid = (
        (oos["rsi14"]         <= f["rsi_max"]) &
        (oos["drawdown_7d"]   <= f["drawdown_min"]) &
        (oos["fng_value"]     <= f["fng_max"]) &
        (oos["btc_dom_proxy"] <= f["btc_dom_max"]) &
        (oos["mom_4h"]        >= f["mom_4h_min"]) &
        (oos["vol_ratio"]     >= f["vol_ratio_min"])
    )
    grid_combo = grid["trade"]
    grid_suffix = combo_suffix(grid_combo)
    grid_pnl = oos[f"pnl_{grid_suffix}"].values - FEE_PCT
    grid_lab = oos[f"label_{grid_suffix}"].values

    # === Trainer B — XGB (opcional) ===
    X = oos[FEATURE_COLS].values
    if has_xgb:
        xgb_combo_key = xgb_b["best_combo"]
        xgb_pkg = xgb_models[xgb_combo_key]
        p_xgb = xgb_pkg["model"].predict_proba(X)[:, 1]
        sig_xgb = pd.Series(p_xgb >= xgb_pkg["threshold"], index=oos.index)
        xgb_combo_dict = {"stop_pct": xgb_b["stop_pct"], "target_pct": xgb_b["target_pct"], "max_hours": xgb_b["max_hours"]}
        xgb_suffix = combo_suffix(xgb_combo_dict)
        xgb_pnl = oos[f"pnl_{xgb_suffix}"].values - FEE_PCT
        xgb_lab = oos[f"label_{xgb_suffix}"].values
    else:
        xgb_combo_key = None
        xgb_pkg = None
        p_xgb = np.zeros(len(oos))
        sig_xgb = pd.Series([False]*len(oos), index=oos.index)
        xgb_combo_dict = grid_combo
        xgb_pnl = grid_pnl
        xgb_lab = grid_lab

    # === Trainer C — Hybrid (opcional) ===
    if has_hybrid:
        hf = hyb_pkg["grid_filters"]
        sig_hyb_pre = (
            (oos["rsi14"]         <= hf["rsi_max"]) &
            (oos["drawdown_7d"]   <= hf["drawdown_min"]) &
            (oos["fng_value"]     <= hf["fng_max"]) &
            (oos["btc_dom_proxy"] <= hf["btc_dom_max"]) &
            (oos["mom_4h"]        >= hf["mom_4h_min"]) &
            (oos["vol_ratio"]     >= hf["vol_ratio_min"])
        )
        Xs = hyb_pkg["scaler"].transform(X)
        p_hyb_all = hyb_pkg["model"].predict_proba(Xs)[:, 1]
        p_hyb = pd.Series(p_hyb_all, index=oos.index)
        sig_hyb = sig_hyb_pre & (p_hyb >= hyb_pkg["threshold"])
        hyb_suffix = combo_suffix(hyb_pkg["trade"])
        hyb_pnl = oos[f"pnl_{hyb_suffix}"].values - FEE_PCT
        hyb_lab = oos[f"label_{hyb_suffix}"].values
    else:
        sig_hyb_pre = pd.Series([True]*len(oos), index=oos.index)
        sig_hyb     = pd.Series([False]*len(oos), index=oos.index)
        p_hyb_all   = np.zeros(len(oos))
        hyb_pnl     = grid_pnl  # placeholder
        hyb_lab     = grid_lab

    # === Calcular metricas ===
    def metrics(name, sig_array, pnl_array, lab_array, combo_used):
        sig = sig_array.values if hasattr(sig_array, "values") else sig_array
        n = int(sig.sum())
        if n == 0:
            return {"name": name, "n": 0, "win_rate": 0, "pf": 0, "total_pnl": 0,
                    "avg_pnl": 0, "max_dd": 0, "score": -999, "combo": combo_used}
        pnls = pnl_array[sig]
        wins = (lab_array[sig] == "WIN").sum()
        wr = wins / n
        wpos = pnls[pnls > 0].sum()
        wneg = -pnls[pnls < 0].sum()
        pf = (wpos / wneg) if wneg > 0 else 999
        total = float(pnls.sum())
        avg = float(pnls.mean())
        # Equity curve
        eq = pnls.cumsum()
        peak = np.maximum.accumulate(eq)
        dd = (eq - peak)
        max_dd = float(dd.min()) if len(dd) else 0
        score = total / max(abs(max_dd), 1) * math.log(max(n, 2))
        return {
            "name": name, "n": n,
            "win_rate": round(wr, 4),
            "pf": round(pf, 3) if pf != 999 else 999,
            "total_pnl": round(total, 3),
            "avg_pnl": round(avg, 4),
            "max_dd": round(max_dd, 3),
            "score": round(score, 3),
            "combo": combo_used,
        }

    print("\n" + "="*72)
    print(f"{'Modelo':<22} {'n':>4} {'WR%':>6} {'PF':>6} {'PnL%':>7} {'maxDD':>7} {'score':>7}")
    print("="*72)

    res = []
    res.append(metrics("A. Grid puro",  sig_grid, grid_pnl, grid_lab, grid_combo))
    if has_xgb:
        res.append(metrics("B. XGB ML", sig_xgb,  xgb_pnl,  xgb_lab,  xgb_combo_dict))
    if has_hybrid:
        res.append(metrics("C. Hybrid", sig_hyb,  hyb_pnl,  hyb_lab,  hyb_pkg["trade"]))

    # === Ensembles ===
    # Para ensemblar tenemos que usar el MISMO combo de stop/target para los 3.
    # Usamos el combo del mejor individual.
    individual_best = max(res, key=lambda r: r["score"])
    ens_combo = individual_best["combo"]
    ens_suffix = combo_suffix(ens_combo)
    ens_pnl = oos[f"pnl_{ens_suffix}"].values - FEE_PCT
    ens_lab = oos[f"label_{ens_suffix}"].values

    sig_grid_a = sig_grid.values if hasattr(sig_grid, "values") else sig_grid
    sig_xgb_a  = sig_xgb.values  if hasattr(sig_xgb, "values")  else sig_xgb
    sig_hyb_a  = sig_hyb.values  if hasattr(sig_hyb, "values")  else sig_hyb

    # Ensembles segun que modelos esten disponibles
    if has_xgb and has_hybrid:
        votes = sig_grid_a.astype(int) + sig_xgb_a.astype(int) + sig_hyb_a.astype(int)
        res.append(metrics("E1. Majority 2of3",  votes >= 2, ens_pnl, ens_lab, ens_combo))
        res.append(metrics("E2. Any of 3",       votes >= 1, ens_pnl, ens_lab, ens_combo))
        res.append(metrics("E3. All 3",          votes >= 3, ens_pnl, ens_lab, ens_combo))
        sig_prob = ((p_xgb + p_hyb_all) / 2 >= 0.55) & sig_hyb_pre.values
        res.append(metrics("E4. ProbAvg XGB+Hyb", sig_prob, ens_pnl, ens_lab, ens_combo))
    elif has_xgb:
        votes2 = sig_grid_a.astype(int) + sig_xgb_a.astype(int)
        res.append(metrics("E1. Both Grid+XGB",  votes2 >= 2, ens_pnl, ens_lab, ens_combo))
        res.append(metrics("E2. Any Grid+XGB",   votes2 >= 1, ens_pnl, ens_lab, ens_combo))
    elif has_hybrid:
        votes2 = sig_grid_a.astype(int) + sig_hyb_a.astype(int)
        res.append(metrics("E1. Both Grid+Hyb",  votes2 >= 2, ens_pnl, ens_lab, ens_combo))
        res.append(metrics("E2. Any Grid+Hyb",   votes2 >= 1, ens_pnl, ens_lab, ens_combo))
    # else: solo grid, sin ensemble

    for r in res:
        pf_s = f"{r['pf']:>6.2f}" if r['pf'] != 999 else "   inf"
        print(f"{r['name']:<22} {r['n']:>4d} {r['win_rate']*100:>5.1f}% {pf_s} "
              f"{r['total_pnl']:>+7.2f} {r['max_dd']:>+7.2f} {r['score']:>+7.2f}")

    # Correlacion de senales (entre los 3 base)
    import numpy as np
    def corr(a, b):
        a = np.asarray(a, dtype=float); b = np.asarray(b, dtype=float)
        if a.std() == 0 or b.std() == 0: return 0
        return float(np.corrcoef(a, b)[0,1])

    correlations = {}
    if has_xgb:
        correlations["grid_xgb"] = round(corr(sig_grid_a, sig_xgb_a), 3)
    if has_hybrid:
        correlations["grid_hybrid"] = round(corr(sig_grid_a, sig_hyb_a), 3)
    if has_xgb and has_hybrid:
        correlations["xgb_hybrid"]  = round(corr(sig_xgb_a, sig_hyb_a), 3)
    print("\nCorrelacion entre senales (1 = identicas):")
    for k, v in correlations.items():
        print(f"  {k:14s}  {v:+.3f}")

    # === Recomendacion ===
    # CRITERIOS DEPLOYABLE OOS:
    #   - n >= 5 (frecuencia minima)
    #   - WR >= 0.40 (psicologicamente viable con $10)
    #   - PF >= 1.5 (edge real, no marginal)
    #   - max_dd > -50 (no liquidacion casi segura)
    DEPLOY_MIN_N    = 5
    DEPLOY_MIN_WR   = 0.40
    DEPLOY_MIN_PF   = 1.5
    DEPLOY_MIN_DD   = -50.0

    deployable_res = [r for r in res
                      if r["n"] >= DEPLOY_MIN_N
                      and r["win_rate"] >= DEPLOY_MIN_WR
                      and r["pf"] >= DEPLOY_MIN_PF
                      and r["max_dd"] >= DEPLOY_MIN_DD]

    if deployable_res:
        winner = max(deployable_res, key=lambda r: (r["score"], r["total_pnl"]))
        deployable = True
    else:
        winner = max(res, key=lambda r: (r["score"], r["total_pnl"]))
        deployable = False

    print("\n" + "="*72)
    if deployable:
        print(f"GANADOR OOS (DEPLOYABLE): {winner['name']}")
    else:
        print(f"GANADOR OOS (NO DEPLOYABLE — informativo): {winner['name']}")
        print(f"  Ningun modelo cumple criterios live: n>={DEPLOY_MIN_N}, "
              f"WR>={DEPLOY_MIN_WR*100:.0f}%, PF>={DEPLOY_MIN_PF}, maxDD>={DEPLOY_MIN_DD}")
    print(f"  trades={winner['n']}  WR={winner['win_rate']*100:.1f}%  PF={winner['pf']}  "
          f"PnL={winner['total_pnl']:+.2f}%  maxDD={winner['max_dd']:+.2f}%")
    print("="*72)

    # Output
    json.dump({
        "oos_window_hours": HOURS_OOS,
        "oos_rows": len(oos),
        "rankings": sorted(res, key=lambda x: -x["score"]),
        "correlations": correlations,
        "winner": winner,
        "deployable": deployable,
        "deploy_criteria": {
            "min_n": DEPLOY_MIN_N, "min_wr": DEPLOY_MIN_WR,
            "min_pf": DEPLOY_MIN_PF, "min_dd": DEPLOY_MIN_DD,
        },
    }, open(OUT_COMP, "w"), indent=2, default=str)

    # No escribir winner_config si no es deployable — bloquea live_runner
    if not deployable:
        if os.path.exists(OUT_WINNER):
            os.remove(OUT_WINNER)
        print(f"\n[!] {OUT_WINNER} NO se escribio. live_runner no podra operar.")
        print(f"    Re-entrena, descarga mas data, o espera nuevas semanas de mercado.\n")
        print(f"✓ Comparacion guardada para diagnostico: {OUT_COMP}")
        return

    # Winner config para live (solo si deployable)
    winner_cfg = {
        "winner_name": winner["name"],
        "winner_metrics": {k: winner[k] for k in ["n", "win_rate", "pf", "total_pnl", "max_dd", "score"]},
        "trade": winner["combo"],
        "fee_pct_assumed": FEE_PCT,
    }
    if winner["name"].startswith("A."):
        winner_cfg["type"] = "grid"
        winner_cfg["filters"] = grid["filters"]
    elif winner["name"].startswith("B.") and has_xgb:
        winner_cfg["type"] = "xgb"
        winner_cfg["xgb_combo"] = xgb_combo_key
        winner_cfg["threshold"] = xgb_pkg["threshold"]
    elif winner["name"].startswith("C.") and has_hybrid:
        winner_cfg["type"] = "hybrid"
        winner_cfg["filters"] = hyb_pkg["grid_filters"]
        winner_cfg["threshold"] = hyb_pkg["threshold"]
    else:
        winner_cfg["type"] = "ensemble"
        winner_cfg["voting"] = winner["name"]
        winner_cfg["components"] = ["grid", "xgb", "hybrid"]

    json.dump(winner_cfg, open(OUT_WINNER, "w"), indent=2, default=str)

    print(f"\n✓ Comparacion: {OUT_COMP}")
    print(f"✓ Winner config: {OUT_WINNER}")
    print(f"\nSiguiente paso: python -m model_d_training.live_runner --dry-run")


def combo_suffix(combo):
    return f"s{int(combo['stop_pct']*1000):03d}_t{int(combo['target_pct']*1000):03d}_h{combo['max_hours']}"


if __name__ == "__main__":
    main()
