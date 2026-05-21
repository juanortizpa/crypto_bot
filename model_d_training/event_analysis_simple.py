#!/usr/bin/env python3
"""
Simple event-driven analysis without sklearn.

Analiza los 4.6M klines para ver:
- Cuales eventos tuvieron mas volatilidad post-evento
- Cuales events tuvieron spike UP vs DOWN
- Win rate si hubieras entrado con entry_price pos-evento
"""
import pandas as pd
import os
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(ROOT, "state", "features_d.csv")

print("\n=== ANALISIS EVENT-DRIVEN (4.6M Klines) ===\n")

df = pd.read_csv(CSV).sort_values("ts")
df['dt_iso'] = pd.to_datetime(df['dt_iso'])

from global_events_2026 import GLOBAL_EVENTS_2026, POTENTIAL_CRISIS_EVENTS
events = GLOBAL_EVENTS_2026 + POTENTIAL_CRISIS_EVENTS

print(f"Analizing {len(events)} events against {len(df)} klines...\n")

event_results = []

for event in events:
    event_date = event.get('date')
    event_time = event.get('time', '13:30')
    event_name = event.get('event', '')
    impact = event.get('impact', 'MEDIUM')

    try:
        event_dt = pd.to_datetime(event_date + " " + event_time, utc=True)
    except:
        continue

    window_start = event_dt - timedelta(minutes=30)
    window_end = event_dt + timedelta(minutes=120)

    window = df[(df['dt_iso'] >= window_start) & (df['dt_iso'] <= window_end)]

    if len(window) < 10:
        continue

    after = window[window['dt_iso'] >= event_dt]

    if len(after) < 5:
        continue

    pre_atr = window[window['dt_iso'] < event_dt]['atr_pct'].mean()
    post_atr = after['atr_pct'].mean()
    volatility_increase = (post_atr / pre_atr - 1) * 100 if pre_atr > 0 else 0

    price_entry = after['entry_price'].iloc[0]
    price_final = after['entry_price'].iloc[-1]
    price_high = after['entry_price'].max()
    price_low = after['entry_price'].min()

    direction = "UP" if price_final > price_entry else "DOWN"
    move_pct = (price_final - price_entry) / price_entry * 100
    max_move = (price_high - price_entry) / price_entry * 100
    min_move = (price_low - price_entry) / price_entry * 100

    win = 1 if (price_high - price_entry) / price_entry > 0.03 else 0

    event_results.append({
        'date': event_date,
        'event': event_name[:40],
        'impact': impact,
        'direction': direction,
        'move_%': round(move_pct, 2),
        'max_%': round(max_move, 2),
        'min_%': round(min_move, 2),
        'vol_spike_%': round(volatility_increase, 1),
        'win': win
    })

result_df = pd.DataFrame(event_results)

print(f"Procesados: {len(result_df)} eventos con datos\n")

print("RESUMEN GENERAL:")
print(f"  Total eventos analizados: {len(result_df)}")
print(f"  Movimiento promedio: {result_df['move_%'].mean():.2f}%")
print(f"  Max movimiento promedio: {result_df['max_%'].mean():.2f}%")
print(f"  Volatilidad spike promedio: {result_df['vol_spike_%'].mean():.1f}%")
print(f"  Win rate (mov > 3%): {result_df['win'].sum()}/{len(result_df)} ({100*result_df['win'].mean():.1f}%)")

print("\nPOR TIPO DE IMPACTO:")
for imp in ['CRITICAL', 'HIGH', 'MEDIUM']:
    subset = result_df[result_df['impact'] == imp]
    if len(subset) > 0:
        print(f"\n  {imp} ({len(subset)} eventos):")
        print(f"    Avg move: {subset['move_%'].mean():.2f}%")
        print(f"    Win rate: {subset['win'].mean():.1%}")
        print(f"    Vol spike: {subset['vol_spike_%'].mean():.1f}%")

print("\nMEJORES EVENTOS (mayor movimiento UP):")
top = result_df.nlargest(5, 'max_%')[['date', 'event', 'move_%', 'max_%', 'impact']]
for idx, row in top.iterrows():
    print(f"  {row['date']} {row['event'][:35]:35} move={row['move_%']:+6.2f}% max={row['max_%']:+6.2f}% ({row['impact']})")

print("\nPEORES EVENTOS (mayor movimiento DOWN):")
worst = result_df.nsmallest(5, 'max_%')[['date', 'event', 'move_%', 'max_%', 'impact']]
for idx, row in worst.iterrows():
    print(f"  {row['date']} {row['event'][:35]:35} move={row['move_%']:+6.2f}% max={row['max_%']:+6.2f}% ({row['impact']})")

result_df.to_csv(os.path.join(ROOT, "results", "event_analysis.csv"), index=False)
print(f"\nGuardado: {ROOT}/results/event_analysis.csv")

print("\nCONCLUSION:")
if result_df['win'].mean() > 0.55:
    print("  Event-driven entries: VIABLE (>55% win rate)")
    print("  Recommendation: Train model on post-event patterns")
elif result_df['win'].mean() > 0.50:
    print("  Event-driven entries: BORDERLINE (50-55% win rate)")
    print("  Recommendation: Add filters (FNG, momentum)")
else:
    print("  Event-driven entries alone: NO (< 50% win rate)")
    print("  Recommendation: Combine with other signals")
