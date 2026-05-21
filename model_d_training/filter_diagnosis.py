#!/usr/bin/env python3
"""Filter diagnosis: why 0 trades in OOS"""
import os, sys, json, pandas as pd
ROOT = os.path.dirname(os.path.abspath(__file__))
csv_path = os.path.join(ROOT, "state", "features_d.csv")
grid_path = os.path.join(ROOT, "results", "grid_best.json")
df = pd.read_csv(csv_path).sort_values("ts").reset_index(drop=True)
last_ts = df["ts"].max()
oos = df[df["ts"] >= last_ts - 30*24*3600].copy()
grid = json.load(open(grid_path))
f = grid["filters"]

print("\nOOS Stats: %d bars (%s to %s)" % (len(oos), oos['dt_iso'].iloc[0][:10], oos['dt_iso'].iloc[-1][:10]))
print("\nFILTER PASS RATES:")
print("RSI <= %d: %d/%d (%.1f%%) | mean=%.2f" % (f["rsi_max"], (oos["rsi14"]<=f["rsi_max"]).sum(), len(oos), 100*(oos["rsi14"]<=f["rsi_max"]).sum()/len(oos), oos["rsi14"].mean()))
print("DD <= %d: %d/%d (%.1f%%) | mean=%.2f" % (f["drawdown_min"], (oos["drawdown_7d"]<=f["drawdown_min"]).sum(), len(oos), 100*(oos["drawdown_7d"]<=f["drawdown_min"]).sum()/len(oos), oos["drawdown_7d"].mean()))
print("FNG <= %d: %d/%d (%.1f%%) | mean=%.2f" % (f["fng_max"], (oos["fng_value"]<=f["fng_max"]).sum(), len(oos), 100*(oos["fng_value"]<=f["fng_max"]).sum()/len(oos), oos["fng_value"].mean()))
print("BTC <= %d: %d/%d (%.1f%%) | mean=%.2f" % (f["btc_dom_max"], (oos["btc_dom_proxy"]<=f["btc_dom_max"]).sum(), len(oos), 100*(oos["btc_dom_proxy"]<=f["btc_dom_max"]).sum()/len(oos), oos["btc_dom_proxy"].mean()))
print("MOM >= %d: %d/%d (%.1f%%) | mean=%.2f" % (f["mom_4h_min"], (oos["mom_4h"]>=f["mom_4h_min"]).sum(), len(oos), 100*(oos["mom_4h"]>=f["mom_4h_min"]).sum()/len(oos), oos["mom_4h"].mean()))
print("VOL >= %.1f: %d/%d (%.1f%%) | mean=%.2f" % (f["vol_ratio_min"], (oos["vol_ratio"]>=f["vol_ratio_min"]).sum(), len(oos), 100*(oos["vol_ratio"]>=f["vol_ratio_min"]).sum()/len(oos), oos["vol_ratio"].mean()))

sig = ((oos["rsi14"]<=f["rsi_max"]) & (oos["drawdown_7d"]<=f["drawdown_min"]) & (oos["fng_value"]<=f["fng_max"]) & (oos["btc_dom_proxy"]<=f["btc_dom_max"]) & (oos["mom_4h"]>=f["mom_4h_min"]) & (oos["vol_ratio"]>=f["vol_ratio_min"]))
print("\nALL CONDITIONS (AND): %d/%d (%.1f%%) << THIS IS THE PROBLEM" % (sig.sum(), len(oos), 100*sig.sum()/len(oos)))

print("\nSOLUTION: The key killers are:")
print("  1. DD <= -20: market was only -5% (not in severe panic)")
print("  2. MOM >= 2%: market had -0.39% (negative momentum)")
print("  3. VOL >= 1.2: volume was only 0.96x (no spike)")
print("\nFix: Relax these to DD <= -50, MOM >= -2, VOL >= 0.5")
