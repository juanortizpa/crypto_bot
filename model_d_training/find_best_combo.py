#!/usr/bin/env python3
"""Find best stop/target combo independent of filters"""
import os, json, pandas as pd
ROOT = os.path.dirname(os.path.abspath(__file__))
csv = pd.read_csv(os.path.join(ROOT, "state", "features_d.csv")).sort_values("ts")

csv['year'] = csv['dt_iso'].str[:4]
is_df = csv[csv['year'] < '2026']
oos_df = csv[csv['year'] == '2026']

print(f"IS: {len(is_df)} rows | OOS: {len(oos_df)} rows\n")

# Find all combo columns
combos = set()
for col in csv.columns:
    if col.startswith("label_s"):
        combo = col.replace("label_", "")
        combos.add(combo)

combos = sorted(combos)
print(f"Found {len(combos)} combos: {combos}\n")

print("COMBO PERFORMANCE IN IS (2024-2025):")
print("Combo         | Trades | Win% | PF    | PnL%")
print("-" * 50)

results_is = []
for combo in combos:
    label_col = f"label_{combo}"
    pnl_col = f"pnl_{combo}"

    lab = is_df[label_col].values
    pnl = is_df[pnl_col].values - 0.10  # fee

    trades = (lab != "TIMEOUT").sum()
    wins = (lab == "WIN").sum()
    wr = wins / trades if trades > 0 else 0

    wpos = pnl[(lab == "WIN") & (pnl > 0)].sum()
    wneg = -pnl[(lab == "LOSS") & (pnl < 0)].sum()
    pf = wpos / wneg if wneg > 0 else 999
    total_pnl = pnl[lab != "TIMEOUT"].sum()

    print(f"{combo:13} | {trades:6.0f} | {wr:5.1%} | {pf:5.2f} | {total_pnl:6.2f}")
    results_is.append({"combo": combo, "trades": trades, "wr": wr, "pf": pf, "pnl": total_pnl})

print("\n\nCOMBO PERFORMANCE IN OOS (April-May 2026):")
print("Combo         | Trades | Win% | PF    | PnL%")
print("-" * 50)

results_oos = []
for combo in combos:
    label_col = f"label_{combo}"
    pnl_col = f"pnl_{combo}"

    lab = oos_df[label_col].values
    pnl = oos_df[pnl_col].values - 0.10

    trades = (lab != "TIMEOUT").sum()
    if trades == 0:
        print(f"{combo:13} | {0:6.0f} | 0.0% | 0.00  | 0.00")
        continue

    wins = (lab == "WIN").sum()
    wr = wins / trades

    wpos = pnl[(lab == "WIN") & (pnl > 0)].sum()
    wneg = -pnl[(lab == "LOSS") & (pnl < 0)].sum()
    pf = wpos / wneg if wneg > 0 else 999
    total_pnl = pnl[lab != "TIMEOUT"].sum()

    print(f"{combo:13} | {trades:6.0f} | {wr:5.1%} | {pf:5.2f} | {total_pnl:6.2f}")
    results_oos.append({"combo": combo, "trades": trades, "wr": wr, "pf": pf, "pnl": total_pnl})

if results_oos:
    best = max(results_oos, key=lambda x: (x["trades"], x["pf"]))
    print(f"\n>>> BEST OOS COMBO: {best['combo']}")
    s, t, h = int(best['combo'][1:4])/100, int(best['combo'][5:8])/100, int(best['combo'][10:])
    print(f">>> Parameters: stop={s:.2f}%, target={t:.2f}%, max_hours={h}")
    print(f">>> OOS: {best['trades']:.0f} trades, WR={best['wr']:.1%}, PF={best['pf']:.2f}, PnL={best['pnl']:.2f}%")
else:
    print("\n>>> NO COMBOS PRODUCED TRADES IN OOS")
    print(">>> This means the features alone aren't driving decisions")
    print(">>> The gate filters were the real signal generator")
