"""
train_grid.py — Trainer A: Grid search heuristico sobre features_d.csv.

Optimiza thresholds del Modelo D buscando la combinacion con mejor
metrica compuesta. NO requiere libs externas (solo stdlib).

Hyperparams a explorar:
    rsi_max          [25, 30, 35, 40]
    drawdown_min     [-5, -8, -10, -15]      (drawdown ya es negativo)
    fng_max          [25, 35, 45, 60]
    btc_dom_max      [55, 60, 100]           (100 = no filtrar)
    mom_4h_min       [-100, -3, 0]           (-100 = no filtrar)
    combo            [los 5 de LABEL_COMBOS]

Metricas evaluadas:
    n_trades        — cuantas senales dio
    win_rate        — % de WIN
    avg_pnl         — pnl promedio por trade (incluyendo timeouts)
    profit_factor   — sum(WIN_pnl) / sum(LOSS_pnl)
    expectancy      — win_rate*avg_win + loss_rate*avg_loss
    score           — ranking compuesto

Salida: results/grid_top.json + grid_all.csv

Uso: python -m model_d_training.train_grid
"""
import os
import sys
import csv
import json
import math
import itertools
from collections import defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
IN_CSV   = os.path.join(ROOT, "state", "features_d.csv")
OUT_TOP  = os.path.join(ROOT, "results", "grid_top.json")
OUT_ALL  = os.path.join(ROOT, "results", "grid_all.csv")
OUT_BEST = os.path.join(ROOT, "results", "grid_best.json")  # config para live

# Espacio de busqueda
GRID = {
    "rsi_max":      [25, 30, 35, 40, 45],
    "drawdown_min": [-5, -8, -10, -15, -20],
    "fng_max":      [25, 35, 45, 60, 100],
    "btc_dom_max":  [55, 60, 100],
    "mom_4h_min":   [-100, -3, 0, 2],
    "vol_ratio_min":[0, 0.8, 1.2],
}

LABEL_COMBOS = [
    ("s020_t030_h6",  0.020, 0.030,  6),
    ("s025_t040_h8",  0.025, 0.040,  8),
    ("s030_t050_h12", 0.030, 0.050, 12),
    ("s035_t060_h16", 0.035, 0.060, 16),
    ("s040_t080_h24", 0.040, 0.080, 24),
]

MIN_TRADES         = 30    # minimo para incluir en ranking (display)
MIN_TRADES_WINNER  = 100   # minimo total para considerar winner
MIN_TRADES_HOLDOUT = 8     # minimo en holdout (~30 dias) para confirmar robustez
HOLDOUT_FRAC       = 0.30  # ultimas 30% del tiempo = holdout
FEE_PCT            = 0.10  # comision Binance round-trip aprox 0.1% total

# Filtros de calidad para winner deployable (perfil "calidad maxima")
QUALITY_TRAIN_PF_MIN   = 3.0
QUALITY_TRAIN_WR_MIN   = 0.55
QUALITY_HOLDOUT_PF_MIN = 1.5
QUALITY_HOLDOUT_WR_MIN = 0.40


def load_rows(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            # convertir tipos
            for k, v in list(r.items()):
                if k in ("pair", "dt_iso") or k.startswith("label_"):
                    continue
                try:
                    r[k] = float(v) if "." in v or "e" in v.lower() else int(v)
                except (ValueError, TypeError):
                    pass
            rows.append(r)
    return rows


def _metrics_from_subset(subset, combo_key):
    """Calcula metricas sobre una lista de filas ya filtradas."""
    n = len(subset)
    if n == 0:
        return {"n": 0, "win_rate": 0, "avg_pnl": 0, "pf": 0,
                "expectancy": 0, "total_pnl": 0, "sharpe": 0}

    pnl_col   = f"pnl_{combo_key}"
    label_col = f"label_{combo_key}"
    pnls   = [r[pnl_col] - FEE_PCT for r in subset]
    wins   = [p for p, r in zip(pnls, subset) if r[label_col] == "WIN"]
    losses = [p for p, r in zip(pnls, subset) if r[label_col] == "LOSS"]

    n_win    = len(wins)
    win_rate = n_win / n
    avg_pnl  = sum(pnls) / n
    avg_win  = sum(wins) / n_win if n_win else 0
    avg_loss = sum(losses) / len(losses) if losses else 0

    sum_win  = sum(wins)
    sum_loss = -sum(losses) if losses else 0
    pf = (sum_win / sum_loss) if sum_loss > 0 else (math.inf if sum_win > 0 else 0)

    expectancy = win_rate * avg_win + (1 - win_rate) * (avg_loss if avg_loss < 0 else 0)

    if n > 1:
        mean = avg_pnl
        var = sum((p - mean) ** 2 for p in pnls) / (n - 1)
        std = math.sqrt(var) if var > 0 else 1
        sharpe = (avg_pnl / std) * math.sqrt(n)
    else:
        sharpe = 0

    return {
        "n": n,
        "win_rate": round(win_rate, 4),
        "avg_pnl": round(avg_pnl, 4),
        "pf": round(pf, 3) if pf != math.inf else 999,
        "expectancy": round(expectancy, 4),
        "total_pnl": round(sum(pnls), 2),
        "sharpe": round(sharpe, 3),
    }


def evaluate_combo(rows, params, combo_key, holdout_ts):
    """
    Aplica filtros y calcula metricas TRAIN (ts<holdout_ts) y HOLDOUT (ts>=).
    Score robusto: requiere edge en AMBOS periodos.
    """
    filtered = [
        r for r in rows
        if r["rsi14"] <= params["rsi_max"]
        and r["drawdown_7d"] <= params["drawdown_min"]
        and r["fng_value"] <= params["fng_max"]
        and r["btc_dom_proxy"] <= params["btc_dom_max"]
        and r["mom_4h"] >= params["mom_4h_min"]
        and r["vol_ratio"] >= params["vol_ratio_min"]
    ]
    n = len(filtered)
    if n < MIN_TRADES:
        return None

    train_set   = [r for r in filtered if r["ts"] <  holdout_ts]
    holdout_set = [r for r in filtered if r["ts"] >= holdout_ts]

    train   = _metrics_from_subset(train_set,   combo_key)
    holdout = _metrics_from_subset(holdout_set, combo_key)
    total   = _metrics_from_subset(filtered,    combo_key)

    # Score: requiere edge en train Y en holdout
    if (train["pf"] < 1.0 or train["expectancy"] <= 0
        or holdout["pf"] < 1.0 or holdout["expectancy"] <= 0):
        score = (train["expectancy"] + holdout["expectancy"]) / 2
    else:
        train_pf_c   = min(train["pf"], 5.0)
        holdout_pf_c = min(holdout["pf"], 5.0)
        # Media armonica para penalizar desbalance entre train y holdout
        harm_pf = 2 * train_pf_c * holdout_pf_c / (train_pf_c + holdout_pf_c)
        score = harm_pf * 0.5 + (train["expectancy"] + holdout["expectancy"]) * 0.25 + math.log(n) * 0.05

    is_quality = (
        train["pf"]   >= QUALITY_TRAIN_PF_MIN   and
        train["win_rate"] >= QUALITY_TRAIN_WR_MIN   and
        holdout["pf"] >= QUALITY_HOLDOUT_PF_MIN and
        holdout["win_rate"] >= QUALITY_HOLDOUT_WR_MIN and
        holdout["n"]  >= MIN_TRADES_HOLDOUT and
        n             >= MIN_TRADES_WINNER
    )

    return {
        "n_trades":      total["n"],
        "win_rate":      total["win_rate"],
        "avg_pnl":       total["avg_pnl"],
        "profit_factor": total["pf"],
        "expectancy":    total["expectancy"],
        "total_pnl":     total["total_pnl"],
        "sharpe":        total["sharpe"],
        "train_n":       train["n"],
        "train_wr":      train["win_rate"],
        "train_pf":      train["pf"],
        "train_pnl":     train["total_pnl"],
        "train_exp":     train["expectancy"],
        "holdout_n":     holdout["n"],
        "holdout_wr":    holdout["win_rate"],
        "holdout_pf":    holdout["pf"],
        "holdout_pnl":   holdout["total_pnl"],
        "holdout_exp":   holdout["expectancy"],
        "is_quality":    bool(is_quality),
        "score":         round(score, 4),
    }


def main():
    if not os.path.exists(IN_CSV):
        print(f"X No existe {IN_CSV}. Corre primero: python -m model_d_training.features")
        sys.exit(1)

    print(f"Cargando {IN_CSV}...")
    rows = load_rows(IN_CSV)
    print(f"  {len(rows)} filas candidatas")

    # Compute holdout cutoff (ultimas 30% del tiempo)
    all_ts = sorted({r["ts"] for r in rows})
    if len(all_ts) < 10:
        print("X No hay suficientes timestamps unicos.")
        sys.exit(1)
    cut_idx = int(len(all_ts) * (1 - HOLDOUT_FRAC))
    holdout_ts = all_ts[cut_idx]
    from datetime import datetime, timezone
    h_iso  = datetime.fromtimestamp(holdout_ts, tz=timezone.utc).isoformat()
    t0_iso = datetime.fromtimestamp(all_ts[0], tz=timezone.utc).isoformat()
    t1_iso = datetime.fromtimestamp(all_ts[-1], tz=timezone.utc).isoformat()
    print(f"  Train: {t0_iso[:10]} → {h_iso[:10]}")
    print(f"  Holdout: {h_iso[:10]} → {t1_iso[:10]}")

    # Generar todas las combinaciones
    keys = list(GRID.keys())
    combos = list(itertools.product(*[GRID[k] for k in keys]))
    total_combos = len(combos) * len(LABEL_COMBOS)
    print(f"\nProbando {len(combos)} combinaciones de filtros × "
          f"{len(LABEL_COMBOS)} stop/target = {total_combos} variantes\n")

    results = []
    done = 0
    for combo_vals in combos:
        params = dict(zip(keys, combo_vals))
        for combo_key, stop_pct, target_pct, max_h in LABEL_COMBOS:
            metrics = evaluate_combo(rows, params, combo_key, holdout_ts)
            done += 1
            if metrics is None:
                continue
            entry = {**params,
                     "combo": combo_key,
                     "stop_pct": stop_pct,
                     "target_pct": target_pct,
                     "max_hours": max_h,
                     **metrics}
            results.append(entry)
            if done % 200 == 0:
                print(f"  ... {done}/{total_combos}", end="\r")

    print(f"\n  Total variantes validas (>= {MIN_TRADES} trades): {len(results)}\n")

    if not results:
        print("X Ninguna combinacion paso el minimo de trades.")
        return

    # Ranking
    results.sort(key=lambda x: x["score"], reverse=True)

    # Mostrar top 15 con breakdown train/holdout
    print("=" * 120)
    print(f"{'#':>3} {'Q':>1} {'score':>6} {'PF_tr':>6} {'WR_tr':>6} {'n_tr':>5} "
          f"{'PF_ho':>6} {'WR_ho':>6} {'n_ho':>5} {'pnl%':>7} {'combo':>16}")
    print("=" * 120)
    for i, r in enumerate(results[:15], 1):
        q = "*" if r.get("is_quality") else " "
        print(f"{i:>3} {q} {r['score']:>6.3f} "
              f"{r['train_pf']:>6.2f} {r['train_wr']*100:>5.1f}% {r['train_n']:>5d} "
              f"{r['holdout_pf']:>6.2f} {r['holdout_wr']*100:>5.1f}% {r['holdout_n']:>5d} "
              f"{r['total_pnl']:>+6.1f}% {r['combo']:>16}")
    print(f"\n  (Q=* = pasa filtros calidad: train PF>={QUALITY_TRAIN_PF_MIN}, "
          f"WR>={QUALITY_TRAIN_WR_MIN}; holdout PF>={QUALITY_HOLDOUT_PF_MIN}, "
          f"WR>={QUALITY_HOLDOUT_WR_MIN}, n>={MIN_TRADES_HOLDOUT})")

    # Guardar
    os.makedirs(os.path.dirname(OUT_TOP), exist_ok=True)
    with open(OUT_TOP, "w") as f:
        json.dump(results[:50], f, indent=2)

    # Winner deployable: PRIMERO buscar Q* (pasa calidad).
    quality = [r for r in results if r.get("is_quality")]
    if quality:
        best = quality[0]
        print(f"\n[+] Winner CALIDAD: n_tr={best['train_n']} WR_tr={best['train_wr']*100:.1f}% "
              f"PF_tr={best['train_pf']}  |  n_ho={best['holdout_n']} "
              f"WR_ho={best['holdout_wr']*100:.1f}% PF_ho={best['holdout_pf']}  |  "
              f"combo={best['combo']}")
    else:
        print(f"\n[!] NINGUN config pasa filtros de calidad "
              f"(train PF>={QUALITY_TRAIN_PF_MIN} y holdout PF>={QUALITY_HOLDOUT_PF_MIN}).")
        # Fallback: pedir minimo de robustez (PF>=1.5 en ambos)
        robust = [r for r in results
                  if r["train_pf"] >= 1.5 and r["holdout_pf"] >= 1.5
                  and r["holdout_n"] >= MIN_TRADES_HOLDOUT
                  and r["n_trades"] >= MIN_TRADES_WINNER]
        if robust:
            best = robust[0]
            print(f"[+] Winner ROBUSTO (no-calidad): train_PF={best['train_pf']} "
                  f"holdout_PF={best['holdout_pf']}  combo={best['combo']}")
        else:
            print(f"[X] NO HAY winner viable. NO se guarda grid_best.json.")
            print(f"    El mercado actual no tiene edge claro con estos filtros.")
            print(f"    Acciones: descarga mas data, expande GRID, o reentrena en semanas.")
            # NO escribir grid_best.json — fuerza al usuario a no operar
            sys.exit(0)

    # AVISO CRITICO redundante si el winner es perdedor
    if best["expectancy"] <= 0 or best["profit_factor"] < 1.0:
        print("\n" + "!"*72)
        print("! CUIDADO: NINGUNA configuracion del grid es rentable (PF<1 o exp<=0).")
        print("! El 'best' es solo el menos malo. NO LO USES EN LIVE.")
        print("! Posibles causas:")
        print("!   1) Datos insuficientes (descarga mas historico con download_data.py)")
        print("!   2) El mercado actual no favorece este tipo de estrategia")
        print("!   3) Los thresholds del GRID son muy restrictivos")
        print("!"*72 + "\n")
    best_config = {
        "model_id": "D_grid_v1",
        "filters": {
            "rsi_max":       best["rsi_max"],
            "drawdown_min":  best["drawdown_min"],
            "fng_max":       best["fng_max"],
            "btc_dom_max":   best["btc_dom_max"],
            "mom_4h_min":    best["mom_4h_min"],
            "vol_ratio_min": best["vol_ratio_min"],
        },
        "trade": {
            "stop_pct":   best["stop_pct"],
            "target_pct": best["target_pct"],
            "max_hours":  best["max_hours"],
        },
        "training_metrics": {
            "n_trades":      best["n_trades"],
            "win_rate":      best["win_rate"],
            "profit_factor": best["profit_factor"],
            "expectancy":    best["expectancy"],
            "total_pnl_pct": best["total_pnl"],
            "sharpe":        best["sharpe"],
        },
    }
    with open(OUT_BEST, "w") as f:
        json.dump(best_config, f, indent=2)

    # CSV con todo
    with open(OUT_ALL, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)

    print(f"\n✓ Top 50: {OUT_TOP}")
    print(f"✓ Best config (para live): {OUT_BEST}")
    print(f"✓ All results: {OUT_ALL}")
    print(f"\nSiguiente paso: python -m model_d_training.train_xgb")


if __name__ == "__main__":
    main()
