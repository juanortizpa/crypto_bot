#!/usr/bin/env python3
import pandas as pd, os
from datetime import timedelta
ROOT = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(ROOT, "state", "features_d.csv")
print("\n=== EVENT-DRIVEN ANALYSIS ===\n")
df = pd.read_csv(CSV).sort_values("ts")
df['dt_iso'] = pd.to_datetime(df['dt_iso'])
from global_events_2026 import GLOBAL_EVENTS_2026, POTENTIAL_CRISIS_EVENTS
events = GLOBAL_EVENTS_2026 + POTENTIAL_CRISIS_EVENTS
print(f"Analyzing {len(events)} events\n")
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
    vol_spike = (post_atr / pre_atr - 1) * 100 if pre_atr > 0 else 0
    price_entry = after['entry_price'].iloc[0]
    price_final = after['entry_price'].iloc[-1]
    price_high = after['entry_price'].max()
    direction = "UP" if price_final > price_entry else "DOWN"
    move_pct = (price_final - price_entry) / price_entry * 100
    max_move = (price_high - price_entry) / price_entry * 100
    win = 1 if (price_high - price_entry) / price_entry > 0.03 else 0
    event_results.append({'date': event_date, 'event': event_name[:35], 'impact': impact, 'dir': direction, 'move_%': round(move_pct, 2), 'max_%': round(max_move, 2), 'vol_%': round(vol_spike, 1), 'win': win})
result_df = pd.DataFrame(event_results)
print(f"Analyzed {len(result_df)} events\n")
print("SUMMARY:")
print(f"  Total events: {len(result_df)}")
print(f"  Avg move: {result_df['move_%'].mean():.2f}%")
print(f"  Avg max: {result_df['max_%'].mean():.2f}%")
print(f"  Vol spike: {result_df['vol_%'].mean():.1f}%")
print(f"  Win rate (>3%): {100*result_df['win'].mean():.1f}%\n")
for imp in ['CRITICAL', 'HIGH', 'MEDIUM']:
    subset = result_df[result_df['impact'] == imp]
    if len(subset) > 0:
        wr = 100*subset['win'].mean()
        avg_move = subset['move_%'].mean()
        print(f"  {imp}: {len(subset)} events, {wr:.0f}% win, {avg_move:+.2f}% avg move")
result_df.to_csv(os.path.join(ROOT, "results", "event_analysis.csv"), index=False)
