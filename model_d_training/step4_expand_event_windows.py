#!/usr/bin/env python3
"""
step4_expand_event_windows.py - Solve the data limitation problem.

Problem: Only 6/39 events produced usable windows (15.4% success rate)
Root cause: Strict time window, timezone issues, data gaps

Solutions:
  1. SYNTHETIC EVENTS: Identify high-volatility spikes in klines
  2. RELAXED WINDOWS: Expand time window from ±150 min to ±300 min
  3. PARTIAL DATA: Lower threshold from 10 pre/post bars to 3
  4. CALENDAR FUSION: Combine real events with momentum peaks

This creates 50-100+ training windows instead of 6.
"""
import pandas as pd
import numpy as np
import sqlite3
import os
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(ROOT, "state", "features_d.csv")
RESULTS_DIR = os.path.join(ROOT, "results")

print("\n" + "="*80)
print("STEP 4: Expand Event Windows for Better Training Data")
print("="*80 + "\n")

# ════════════════════════════════════════════════════════════════════════════
# LOAD FEATURES DATA
# ════════════════════════════════════════════════════════════════════════════

df = pd.read_csv(CSV_PATH)
df['dt_iso'] = pd.to_datetime(df['dt_iso'])
df = df.sort_values('dt_iso').reset_index(drop=True)

print(f"Loaded {len(df):,} 5-min klines")
print(f"Date range: {df['dt_iso'].min()} to {df['dt_iso'].max()}\n")

# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 1: SYNTHETIC EVENTS - High Volatility Spikes
# ════════════════════════════════════════════════════════════════════════════

print("="*80)
print("Strategy 1: Extract Synthetic Events (High Volatility Spikes)")
print("="*80 + "\n")

# Identify periods where volatility spiked significantly
df['atr_zscore'] = (df['atr_pct'] - df['atr_pct'].rolling(100, min_periods=1).mean()) / (df['atr_pct'].rolling(100, min_periods=1).std() + 0.01)
df['rsi_extreme'] = (df['rsi14'] < 25) | (df['rsi14'] > 75)

# Find volatility spikes (top 5% ATR z-scores)
atr_threshold = df['atr_zscore'].quantile(0.95)
vol_spikes = df[df['atr_zscore'] > atr_threshold].copy()

print(f"High volatility spikes (top 5% ATR): {len(vol_spikes)}")
print(f"Sample spikes:")
for idx, row in vol_spikes.head(5).iterrows():
    print(f"  {row['dt_iso']} ATR_z={row['atr_zscore']:.2f} RSI={row['rsi14']:.1f}")

synthetic_events = []
for idx, row in vol_spikes.iterrows():
    synthetic_events.append({
        'date': row['dt_iso'].strftime('%Y-%m-%d'),
        'time': row['dt_iso'].strftime('%H:%M'),
        'event': f"Volatility Spike (ATR_z={row['atr_zscore']:.1f})",
        'impact': 'HIGH' if row['atr_zscore'] > df['atr_zscore'].quantile(0.98) else 'MEDIUM',
        'affected_pairs': ['BTC/USDT', 'ETH/USDT'],  # Generic
        'source': 'synthetic_volatility',
    })

print(f"\nExtracted {len(synthetic_events)} synthetic volatility events\n")

# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 2: MOMENTUM EXTREMES - RSI/Momentum peaks
# ════════════════════════════════════════════════════════════════════════════

print("="*80)
print("Strategy 2: Momentum Extremes (RSI < 25 or > 75)")
print("="*80 + "\n")

rsi_extremes = df[df['rsi_extreme']].copy()
print(f"RSI extreme events (< 25 or > 75): {len(rsi_extremes)}")

# Cluster nearby extremes (same day)
momentum_events = []
processed_dates = set()

for idx, row in rsi_extremes.iterrows():
    date_str = row['dt_iso'].strftime('%Y-%m-%d')
    if date_str in processed_dates:
        continue

    processed_dates.add(date_str)
    event_type = "Extreme Fear" if row['rsi14'] < 25 else "Extreme Greed"

    momentum_events.append({
        'date': date_str,
        'time': row['dt_iso'].strftime('%H:%M'),
        'event': f"{event_type} (RSI={row['rsi14']:.1f})",
        'impact': 'HIGH',
        'affected_pairs': ['BTC/USDT', 'ETH/USDT'],
        'source': 'synthetic_momentum',
    })

print(f"Extracted {len(momentum_events)} momentum extreme events\n")

# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 3: RELAXED CALENDAR EVENTS - Original 39 with wider windows
# ════════════════════════════════════════════════════════════════════════════

print("="*80)
print("Strategy 3: Original Calendar Events (Relaxed Windows)")
print("="*80 + "\n")

from global_events_2026 import GLOBAL_EVENTS_2026, POTENTIAL_CRISIS_EVENTS
calendar_events = GLOBAL_EVENTS_2026 + POTENTIAL_CRISIS_EVENTS

print(f"Original calendar events: {len(calendar_events)}")
print(f"Now trying relaxed matching (±300 min, lower data thresholds)\n")

# ════════════════════════════════════════════════════════════════════════════
# EXTRACT WINDOWS WITH RELAXED CRITERIA
# ════════════════════════════════════════════════════════════════════════════

print("="*80)
print("Extracting Event Windows (Relaxed Criteria)")
print("="*80 + "\n")

def extract_relaxed_window(df, event_date, event_time="13:30", event_name="", impact=""):
    """
    Extract features with relaxed criteria:
    - Wider window: ±300 min (5 hours before/after)
    - Lower data threshold: 3 pre/post bars instead of 10
    - Partial data OK
    """
    try:
        event_dt = pd.to_datetime(event_date + " " + event_time, utc=True)
    except:
        return None

    # Wider window
    window_start = event_dt - timedelta(minutes=300)
    window_end = event_dt + timedelta(minutes=300)

    mask = (df['dt_iso'] >= window_start) & (df['dt_iso'] <= window_end)
    window = df[mask].copy()

    if len(window) < 6:  # Relaxed from 15
        return None

    # Split before/after
    before = window[window['dt_iso'] < event_dt]
    after = window[window['dt_iso'] >= event_dt]

    if len(before) < 2 or len(after) < 2:  # Relaxed from 5
        return None

    # Pre features
    pre_rsi = before['rsi14'].mean() if len(before) > 0 else 50
    pre_mom = before['mom_4h'].mean() if len(before) > 0 else 0
    pre_atr = before['atr_pct'].mean() if len(before) > 0 else 1.0
    pre_vol = before['vol_ratio'].mean() if len(before) > 0 else 1.0
    pre_fng = before['fng_value'].iloc[-1] if len(before) > 0 else 50
    btc_dom = before['btc_dominance'].iloc[-1] if len(before) > 0 and 'btc_dominance' in before.columns else 40

    # Post features
    post_rsi = after['rsi14'].mean()
    post_mom = after['mom_4h'].mean()
    post_atr = after['atr_pct'].mean()
    post_vol = after['vol_ratio'].mean()

    # Price movement
    entry_price = after['entry_price'].iloc[0]
    exit_price = after['entry_price'].iloc[-1]
    high_price = after['entry_price'].max()
    low_price = after['entry_price'].min()

    move_pct = (exit_price - entry_price) / entry_price * 100
    move_abs = abs(move_pct)
    up_pct = (high_price - entry_price) / entry_price * 100
    down_pct = (low_price - entry_price) / entry_price * 100

    # Labels
    label_conservative = 1 if move_abs > 2.0 else 0
    label_aggressive = 1 if move_abs > 0.5 else 0
    label_spike = 1 if up_pct > 1.0 else 0
    label_dip = 1 if down_pct < -1.0 else 0

    return {
        'event_date': event_date,
        'event_name': event_name,
        'impact': impact,
        'hour': event_dt.hour,
        'day_week': event_dt.dayofweek,
        'rsi_pre': pre_rsi,
        'mom_pre': pre_mom,
        'atr_pre': pre_atr,
        'vol_pre': pre_vol,
        'fng': pre_fng,
        'btc_dom': btc_dom,
        'rsi_post': post_rsi,
        'mom_post': post_mom,
        'atr_post': post_atr,
        'vol_post': post_vol,
        'move_pct': move_pct,
        'move_abs': move_abs,
        'up_pct': up_pct,
        'down_pct': down_pct,
        'label_conservative': label_conservative,
        'label_aggressive': label_aggressive,
        'label_spike': label_spike,
        'label_dip': label_dip,
    }

# Extract from all sources
all_extracted = []

print("Extracting from calendar events...")
for event in calendar_events:
    feat = extract_relaxed_window(
        df,
        event.get('date'),
        event.get('time', '13:30'),
        event.get('event', ''),
        event.get('impact', 'MEDIUM')
    )
    if feat:
        all_extracted.append(feat)

print(f"  Calendar: {len(all_extracted)} windows\n")

print("Extracting from synthetic volatility events...")
vol_count = 0
for event in synthetic_events:
    feat = extract_relaxed_window(
        df,
        event.get('date'),
        event.get('time', '13:30'),
        event.get('event', ''),
        event.get('impact', 'MEDIUM')
    )
    if feat:
        all_extracted.append(feat)
        vol_count += 1

print(f"  Synthetic volatility: {vol_count} windows")
print(f"  Total so far: {len(all_extracted)} windows\n")

print("Extracting from momentum extremes...")
mom_count = 0
for event in momentum_events:
    feat = extract_relaxed_window(
        df,
        event.get('date'),
        event.get('time', '13:30'),
        event.get('event', ''),
        event.get('impact', 'MEDIUM')
    )
    if feat:
        all_extracted.append(feat)
        mom_count += 1

print(f"  Momentum extremes: {mom_count} windows\n")

# ════════════════════════════════════════════════════════════════════════════
# SAVE EXPANDED DATASET
# ════════════════════════════════════════════════════════════════════════════

print("="*80)
print("Summary: Expanded Event Windows")
print("="*80 + "\n")

result_df = pd.DataFrame(all_extracted)
print(f"Total windows extracted: {len(result_df)}")
print(f"Improvement: {len(result_df)} vs 6 original ({100*len(result_df)/6:.0f}x increase)\n")

if len(result_df) > 0:
    print("Label distribution:")
    for label in ['label_conservative', 'label_aggressive', 'label_spike', 'label_dip']:
        positive = (result_df[label] == 1).sum()
        pct = 100 * positive / len(result_df)
        print(f"  {label}: {positive}/{len(result_df)} ({pct:.1f}%)")

    # Save
    out_path = os.path.join(RESULTS_DIR, "event_training_data_expanded.csv")
    result_df.to_csv(out_path, index=False)
    print(f"\n✅ Saved to: {out_path}")

    print(f"\n{'='*80}")
    print("Next Step: Re-train models with expanded dataset")
    print(f"{'='*80}")
    print(f"""
    python model_d_training/step5_train_with_expanded_data.py

    This will:
    - Load {len(result_df)} event windows (vs 6 before)
    - Train 4 competitive models with better data
    - Run proper walk-forward validation
    - Select best model for testnet trading
    """)
else:
    print("❌ No windows extracted. Check data format.")

print()
