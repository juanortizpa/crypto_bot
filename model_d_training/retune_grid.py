#!/usr/bin/env python3
"""
retune_grid.py — Find better hyperparameters for 5min klines.

The original grid was trained on 1h data with 2024-2025 panic conditions.
We need to relax filters to match April-May 2026 market reality.
"""
import os, sys, json, pandas as pd, numpy as np
ROOT = os.path.dirname(os.path.abspath(__file__))
csv_path = os.path.join(ROOT, "state", "features_d.csv")
df = pd.read_csv(csv_path).sort_values("ts").reset_index(drop=True)

# Split: 2024-2025 = IS, 2026 = OOS
df['year'] = df['dt_iso'].str[:4]
is_df = df[df['year'] < '2026'].copy()
oos_df = df[df['year'] == '2026'].copy()
print("Train (IS): %d | Test (OOS): %d" % (len(is_df), len(oos_df)))

def combo_suffix(s, t, h):
    return "s%03d_t%03d_h%02d" % (int(s*100), int(t*100), h)

def eval_combo(data, stop, tgt, hours, name=""):
    suf = combo_suffix(stop, tgt, hours)
    if suf not in data.columns:
        return None
    pnl = data[f"pnl_{suf}"].values - 0.10
    lab = data[f"label_{suf}"].values
    wins = (lab == "WIN").sum()
    n = len([x for x in lab if x in ["WIN", "LOSS"]])
    if n == 0:
        return None
    wr = wins / n
    wpos = pnl[pnl > 0].sum()
    wneg = -pnl[pnl < 0].sum()
    pf = wpos / wneg if wneg > 0 else 999
    total_pnl = pnl.sum()
    return {"n": n, "wr": wr, "pf": pf, "pnl": total_pnl, "suf": suf}

# Test grid parameter relaxation
configs = [
    {"dd": -100, "mom": 0, "vol": 0.8, "fng": 60, "rsi": 70},  # Relax everything
    {"dd": -50, "mom": -1, "vol": 0.8, "fng": 50, "rsi": 65},  # Medium relax
    {"dd": -30, "mom": 0, "vol": 1.0, "fng": 50, "rsi": 60},   # Light relax
]

print("\n=== TESTING RELAXED FILTERS ===\n")
for cfg in configs:
    sig = (
        (is_df["rsi14"] <= cfg["rsi"]) &
        (is_df["drawdown_7d"] <= cfg["dd"]) &
        (is_df["fng_value"] <= cfg["fng"]) &
        (is_df["btc_dom_proxy"] <= 60) &
        (is_df["mom_4h"] >= cfg["mom"]) &
        (is_df["vol_ratio"] >= cfg["vol"])
    )
    n_pass = sig.sum()
    pct = 100*n_pass/len(is_df)
    print("Config: DD<=%d, MOM>=%d, VOL>=%.1f, FNG<=%d, RSI<=%d" % (cfg["dd"], cfg["mom"], cfg["vol"], cfg["fng"], cfg["rsi"]))
    print("  Pass rate in IS: %d/%d (%.1f%%)" % (n_pass, len(is_df), pct))

# Find best combo from existing trained models
print("\n=== BEST COMBOS IN IS ===")
stop_list = [0.02, 0.03, 0.04, 0.05, 0.06]
target_list = [0.04, 0.05, 0.06, 0.08, 0.10]
hours_list = [6, 12, 24]
combos_is = []
for s in stop_list:
    for t in target_list:
        if t <= s:
            continue
        for h in hours_list:
            res = eval_combo(is_df, s, t, h)
            if res and res["n"] >= 30:
                combos_is.append(res)

combos_is.sort(key=lambda x: (x["pf"], x["wr"]), reverse=True)
print("Top 5 combos by profit factor in IS:")
for i, c in enumerate(combos_is[:5], 1):
    print(f"  {i}. {c['suf']}: {c['n']} trades, WR={c['wr']:.1%}, PF={c['pf']:.2f}, PnL={c['pnl']:.2f}%")

# Test top combos in OOS
print("\n=== TOP COMBOS IN OOS (April-May 2026) ===")
best_oos = []
for c in combos_is[:10]:
    suf = c["suf"]
    if suf not in oos_df.columns:
        continue
    pnl = oos_df[f"pnl_{suf}"].values - 0.10
    lab = oos_df[f"label_{suf}"].values
    wins = (lab == "WIN").sum()
    n = len([x for x in lab if x in ["WIN", "LOSS"]])
    if n == 0:
        continue
    wr = wins / n
    wpos = pnl[pnl > 0].sum()
    wneg = -pnl[pnl < 0].sum()
    pf = wpos / wneg if wneg > 0 else 999
    total = pnl.sum()
    best_oos.append({"suf": suf, "n": n, "wr": wr, "pf": pf, "pnl": total})

best_oos.sort(key=lambda x: (x["n"], x["pf"]), reverse=True)
print("Top combos by trade count in OOS:")
for i, c in enumerate(best_oos[:5], 1):
    print(f"  {i}. {c['suf']}: {c['n']} trades, WR={c['wr']:.1%}, PF={c['pf']:.2f}, PnL={c['pnl']:.2f}%")

if best_oos:
    winner = best_oos[0]
    s, t, h = int(winner["suf"][1:4])/100, int(winner["suf"][5:8])/100, int(winner["suf"][10:12])
    print(f"\n>>> RECOMMENDED CONFIG: stop={s:.2f}, target={t:.2f}, max_hours={h}")
    new_combo = {"stop_pct": s, "target_pct": t, "max_hours": h}
    print(f">>> Use this in compare.py or grid_best.json")
else:
    print("\nNo good combos found. Need to relax filters more aggressively.")
