#!/usr/bin/env python3
"""Analyze actual feature distributions in IS vs OOS"""
import os, json, pandas as pd
ROOT = os.path.dirname(os.path.abspath(__file__))
csv_path = os.path.join(ROOT, "state", "features_d.csv")
df = pd.read_csv(csv_path).sort_values("ts").reset_index(drop=True)

df['year'] = df['dt_iso'].str[:4]
is_df = df[df['year'] < '2026'].copy()
oos_df = df[df['year'] == '2026'].copy()

print("FEATURE STATISTICS:\n")
features = ["rsi14", "drawdown_7d", "fng_value", "btc_dom_proxy", "mom_4h", "vol_ratio", "atr_pct"]

for feat in features:
    if feat not in df.columns:
        print(f"{feat}: NOT FOUND")
        continue
    print(f"\n{feat}:")
    print(f"  IS   (2024-2025): min={is_df[feat].min():.3f}, mean={is_df[feat].mean():.3f}, max={is_df[feat].max():.3f}, p95={is_df[feat].quantile(0.95):.3f}")
    print(f"  OOS  (2026):      min={oos_df[feat].min():.3f}, mean={oos_df[feat].mean():.3f}, max={oos_df[feat].max():.3f}, p95={oos_df[feat].quantile(0.95):.3f}")

print("\n\nCOLUMNS AVAILABLE:")
print([c for c in df.columns if not c.startswith("pnl_") and not c.startswith("label_")])

# Check grid_best filters
grid = json.load(open(os.path.join(ROOT, "results", "grid_best.json")))
print("\n\nGRID BEST FILTERS:")
for k, v in grid["filters"].items():
    print(f"  {k}: {v}")

# Check if any row passes all filters in IS
f = grid["filters"]
sig = (
    (is_df["rsi14"] <= f["rsi_max"]) &
    (is_df["drawdown_7d"] <= f["drawdown_min"]) &
    (is_df["fng_value"] <= f["fng_max"]) &
    (is_df["btc_dom_proxy"] <= f["btc_dom_max"]) &
    (is_df["mom_4h"] >= f["mom_4h_min"]) &
    (is_df["vol_ratio"] >= f["vol_ratio_min"])
)
print(f"\n\nRows passing ALL filters in IS: {sig.sum()} / {len(is_df)}")

# Try removing one filter at a time to see which is the blocker
print("\nFilters one at a time (IS):")
f1 = (is_df["rsi14"] <= f["rsi_max"]).sum()
f2 = (is_df["drawdown_7d"] <= f["drawdown_min"]).sum()
f3 = (is_df["fng_value"] <= f["fng_max"]).sum()
f4 = (is_df["btc_dom_proxy"] <= f["btc_dom_max"]).sum()
f5 = (is_df["mom_4h"] >= f["mom_4h_min"]).sum()
f6 = (is_df["vol_ratio"] >= f["vol_ratio_min"]).sum()
print(f"  rsi_max: {f1}/{len(is_df)} ({100*f1/len(is_df):.1f}%)")
print(f"  dd_min:  {f2}/{len(is_df)} ({100*f2/len(is_df):.1f}%)")
print(f"  fng_max: {f3}/{len(is_df)} ({100*f3/len(is_df):.1f}%)")
print(f"  btc_max: {f4}/{len(is_df)} ({100*f4/len(is_df):.1f}%)")
print(f"  mom_min: {f5}/{len(is_df)} ({100*f5/len(is_df):.1f}%)")
print(f"  vol_min: {f6}/{len(is_df)} ({100*f6/len(is_df):.1f}%)")
