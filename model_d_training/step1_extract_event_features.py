#!/usr/bin/env python3
"""STEP 1: Extract features from 4.6M klines around 39 events"""
import pandas as pd, numpy as np, os
from datetime import timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(ROOT, "state", "features_d.csv")
OUT = os.path.join(ROOT, "results", "event_training_data.csv")

print("\n=== STEP 1: Extract Event Features ===\n")

df = pd.read_csv(CSV).sort_values("ts")
df['dt_iso'] = pd.to_datetime(df['dt_iso'])

from global_events_2026 import GLOBAL_EVENTS_2026, POTENTIAL_CRISIS_EVENTS
events = GLOBAL_EVENTS_2026 + POTENTIAL_CRISIS_EVENTS

training_data = []

for i, event in enumerate(events):
    date = event.get('date')
    time = event.get('time', '13:30')
    name = event.get('event', '')
    impact = event.get('impact', 'MEDIUM')
    
    try:
        event_dt = pd.to_datetime(date + " " + time, utc=True)
    except:
        continue
    
    w_start = event_dt - timedelta(minutes=30)
    w_end = event_dt + timedelta(minutes=120)
    
    window = df[(df['dt_iso'] >= w_start) & (df['dt_iso'] <= w_end)]
    if len(window) < 10:
        continue
    
    before = window[window['dt_iso'] < event_dt]
    after = window[window['dt_iso'] >= event_dt]
    
    if len(before) < 3 or len(after) < 5:
        continue
    
    # PRE-EVENT features
    f_rsi_pre = before['rsi14'].mean()
    f_mom_pre = before['mom_4h'].mean()
    f_atr_pre = before['atr_pct'].mean()
    f_vol_pre = before['vol_ratio'].mean()
    f_fng = before['fng_value'].iloc[-1]
    f_dom = before['btc_dom_proxy'].iloc[-1]
    
    # POST-EVENT reaction
    f_rsi_post = after['rsi14'].mean()
    f_mom_post = after['mom_4h'].mean()
    f_atr_post = after['atr_pct'].mean()
    f_vol_post = after['vol_ratio'].mean()
    
    # PRICE movement
    price_start = after['entry_price'].iloc[0]
    price_high = after['entry_price'].max()
    price_low = after['entry_price'].min()
    price_end = after['entry_price'].iloc[-1]
    
    move_pct = (price_end - price_start) / price_start
    move_abs = abs(move_pct)
    up_pct = (price_high - price_start) / price_start
    down_pct = (price_low - price_start) / price_start
    
    # LABELS for different models
    label_conservative = 1 if move_abs > 0.02 else 0
    label_aggressive = 1 if move_abs > 0.005 else 0
    label_spike = 1 if up_pct > 0.01 else 0
    label_dip = 1 if down_pct < -0.01 else 0
    
    row = {
        'event_date': date,
        'event_name': name[:30],
        'impact': impact,
        'hour': event_dt.hour,
        'day_week': event_dt.dayofweek,
        
        'rsi_pre': f_rsi_pre,
        'mom_pre': f_mom_pre,
        'atr_pre': f_atr_pre,
        'vol_pre': f_vol_pre,
        'fng': f_fng,
        'btc_dom': f_dom,
        
        'rsi_post': f_rsi_post,
        'mom_post': f_mom_post,
        'atr_post': f_atr_post,
        'vol_post': f_vol_post,
        
        'move_pct': move_pct * 100,
        'move_abs': move_abs * 100,
        'up_pct': up_pct * 100,
        'down_pct': down_pct * 100,
        
        'label_conservative': label_conservative,
        'label_aggressive': label_aggressive,
        'label_spike': label_spike,
        'label_dip': label_dip,
    }
    
    training_data.append(row)
    print(f"  [{i+1:2d}] {date} {name[:35]:35} - move {move_pct*100:+.2f}%")

result = pd.DataFrame(training_data)
os.makedirs(os.path.dirname(OUT), exist_ok=True)
result.to_csv(OUT, index=False)

print(f"\nExtracted {len(result)} event windows")
print(f"Saved to {OUT}")

print(f"\nTarget distribution:")
for label in ['conservative', 'aggressive', 'spike', 'dip']:
    col = f'label_{label}'
    pos = (result[col] == 1).sum()
    neg = len(result) - pos
    pct = 100 * pos / len(result) if len(result) > 0 else 0
    print(f"  {label:15}: {pos:2d} positive ({pct:5.1f}%), {neg:2d} negative")

print(f"\nReady for training!")
