"""
diagnose_filters.py — Diagnóstico: qué filtros están bloqueando señales en OOS.

Analiza cada filtro por separado para identificar cuál está siendo demasiado restrictivo
en el periodo out-of-sample (abril-mayo 2026).
"""
import os
import sys
import json
import pandas as pd
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
IN_CSV = os.path.join(ROOT, "state", "features_d.csv")
GRID_BEST = os.path.join(ROOT, "results", "grid_best.json")

HOURS_OOS = 30 * 24

def main():
    # Cargar datos
    df = pd.read_csv(IN_CSV).sort_values("ts").reset_index(drop=True)
    last_ts = df["ts"].max()
    oos = df[df["ts"] >= last_ts - HOURS_OOS * 3600].copy()

    print(f"\n📊 OOS Window: {len(oos)} rows ({oos['dt_iso'].iloc[0][:10]} → {oos['dt_iso'].iloc[-1][:10]})")
    print(f"   Total bars in OOS: {len(oos)}")

    # Cargar grid_best.json
    grid = json.load(open(GRID_BEST))
    f = grid["filters"]

    print(f"\n🔍 FILTRO ANALYSIS:")
    print(f"{'Filtro':<25} {'Límite':<15} {'% Pasar':<12} {'Detalle'}")
    print("=" * 80)

    # RSI <= rsi_max
    rsi_pass = (oos["rsi14"] <= f["rsi_max"]).sum()
    rsi_pct = 100 * rsi_pass / len(oos)
    rsi_stats = f"(mean={oos['rsi14'].mean():.2f}, min={oos['rsi14'].min():.2f}, max={oos['rsi14'].max():.2f})"
    print(f"RSI <= {f['rsi_max']:<18} {rsi_pass:<12} {rsi_pct:>5.1f}%   {rsi_stats}")

    # Drawdown <= drawdown_min (note: drawdown_min is usually negative, like -20)
    dd_pass = (oos["drawdown_7d"] <= f["drawdown_min"]).sum()
    dd_pct = 100 * dd_pass / len(oos)
    dd_stats = f"(mean={oos['drawdown_7d'].mean():.2f}, min={oos['drawdown_7d'].min():.2f}, max={oos['drawdown_7d'].max():.2f})"
    print(f"DD7d <= {f['drawdown_min']:<18} {dd_pass:<12} {dd_pct:>5.1f}%   {dd_stats}")

    # FNG <= fng_max
    fng_pass = (oos["fng_value"] <= f["fng_max"]).sum()
    fng_pct = 100 * fng_pass / len(oos)
    fng_stats = f"(mean={oos['fng_value'].mean():.2f}, min={oos['fng_value'].min():.2f}, max={oos['fng_value'].max():.2f})"
    print(f"FNG <= {f['fng_max']:<18} {fng_pass:<12} {fng_pct:>5.1f}%   {fng_stats}")

    # BTC Dominance <= btc_dom_max
    btc_pass = (oos["btc_dom_proxy"] <= f["btc_dom_max"]).sum()
    btc_pct = 100 * btc_pass / len(oos)
    btc_stats = f"(mean={oos['btc_dom_proxy'].mean():.2f}, min={oos['btc_dom_proxy'].min():.2f}, max={oos['btc_dom_proxy'].max():.2f})"
    print(f"BTC_DOM <= {f['btc_dom_max']:<14} {btc_pass:<12} {btc_pct:>5.1f}%   {btc_stats}")

    # Mom 4h >= mom_4h_min
    mom_pass = (oos["mom_4h"] >= f["mom_4h_min"]).sum()
    mom_pct = 100 * mom_pass / len(oos)
    mom_stats = f"(mean={oos['mom_4h'].mean():.2f}, min={oos['mom_4h'].min():.2f}, max={oos['mom_4h'].max():.2f})"
    print(f"MOM4h >= {f['mom_4h_min']:<18} {mom_pass:<12} {mom_pct:>5.1f}%   {mom_stats}")

    # Vol ratio >= vol_ratio_min
    vol_pass = (oos["vol_ratio"] >= f["vol_ratio_min"]).sum()
    vol_pct = 100 * vol_pass / len(oos)
    vol_stats = f"(mean={oos['vol_ratio'].mean():.2f}, min={oos['vol_ratio'].min():.2f}, max={oos['vol_ratio'].max():.2f})"
    print(f"VOL_RATIO >= {f['vol_ratio_min']:<15} {vol_pass:<12} {vol_pct:>5.1f}%   {vol_stats}")

    # AND combination (all filters)
    sig_all = (
        (oos["rsi14"] <= f["rsi_max"]) &
        (oos["drawdown_7d"] <= f["drawdown_min"]) &
        (oos["fng_value"] <= f["fng_max"]) &
        (oos["btc_dom_proxy"] <= f["btc_dom_max"]) &
        (oos["mom_4h"] >= f["mom_4h_min"]) &
        (oos["vol_ratio"] >= f["vol_ratio_min"])
    )
    all_pass = sig_all.sum()
    all_pct = 100 * all_pass / len(oos)
    print(f"\n🎯 ALL FILTERS (AND): {all_pass:<12} {all_pct:>5.1f}%   ← THIS IS WHY 0 TRADES")

    # Recommendations
    print(f"\n💡 RECOMMENDATIONS:")
    print(f"   • Loosen FNG from {f['fng_max']} → 50 (allow normal fear levels)")
    print(f"   • Loosen RSI from {f['rsi_max']} → 60 (allow more momentum)")
    print(f"   • Loosen Drawdown from {f['drawdown_min']} → -50 (less stringent)")
    print(f"   • Increase momentum min from {f['mom_4h_min']} → 0.5")

    # Test with relaxed filters
    print(f"\n🧪 TESTING RELAXED PARAMETERS:")
    relax_configs = [
        {"fng_max": 50, "rsi_max": 60, "drawdown_min": -50, "mom_4h_min": 0.5, "vol_ratio_min": 1.0, "btc_dom_max": 60},
        {"fng_max": 60, "rsi_max": 70, "drawdown_min": -100, "mom_4h_min": 0, "vol_ratio_min": 0.8, "btc_dom_max": 70},
        {"fng_max": 75, "rsi_max": 75, "drawdown_min": -150, "mom_4h_min": -2, "vol_ratio_min": 0.5, "btc_dom_max": 80},
    ]

    for i, config in enumerate(relax_configs, 1):
        sig = (
            (oos["rsi14"] <= config["rsi_max"]) &
            (oos["drawdown_7d"] <= config["drawdown_min"]) &
            (oos["fng_value"] <= config["fng_max"]) &
            (oos["btc_dom_proxy"] <= config["btc_dom_max"]) &
            (oos["mom_4h"] >= config["mom_4h_min"]) &
            (oos["vol_ratio"] >= config["vol_ratio_min"])
        )
        n = sig.sum()
        pct = 100 * n / len(oos)
        d = config
        s = f"Config {i}: FNG<={d['fng_max']}, RSI<={d['rsi_max']}, DD<={d['drawdown_min']}"
        print(f"   {s}, MOM>={d['mom_4h_min']}, VOL>={d['vol_ratio_min']}")
        print(f"   -> {n} signals ({pct:.1f}%)")

if __name__ == "__main__":
    main()
