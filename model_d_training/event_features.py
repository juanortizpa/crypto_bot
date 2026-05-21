#!/usr/bin/env python3
"""
event_features.py — Extrae features alrededor de eventos globales.

Para cada evento:
  - Identifica klines dentro de ventana (±120 min)
  - Calcula volatilidad/momentum/direction pre/post evento
  - Etiqueta: SPIKE_UP, SPIKE_DOWN, NORMAL
"""
import pandas as pd
import sqlite3
import numpy as np
from datetime import datetime, timedelta
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(ROOT, "state", "features_d.csv")
DB_PATH = os.path.join(ROOT, "state", "data_2026.db")

def get_events():
    """Obtiene todos los eventos 2026"""
    from global_events_2026 import GLOBAL_EVENTS_2026, POTENTIAL_CRISIS_EVENTS
    return GLOBAL_EVENTS_2026 + POTENTIAL_CRISIS_EVENTS

def event_window_features(df, event_date, event_time="13:30", event_name="", impact="", pairs=None):
    """
    Extrae features para ventana de evento.

    Ventana: -30min ANTES (anticipación) a +120min DESPUÉS (reacción)
    """
    # Parse event datetime
    event_str = f"{event_date} {event_time}"
    event_dt = pd.to_datetime(event_str)

    window_start = event_dt - timedelta(minutes=30)
    window_end = event_dt + timedelta(minutes=120)

    # Filter to window
    mask = (df['dt_iso'] >= window_start.isoformat()) & (df['dt_iso'] <= window_end.isoformat())
    window_df = df[mask].copy()

    if len(window_df) < 10:
        return None  # Not enough data

    # Split: before and after event
    before_mask = (window_df['dt_iso'] < event_dt.isoformat())
    after_mask = (window_df['dt_iso'] >= event_dt.isoformat())

    before_df = window_df[before_mask]
    after_df = window_df[after_mask]

    if len(after_df) < 5:
        return None  # No post-event data

    # PRE-EVENT features
    pre_rsi = before_df['rsi14'].mean() if len(before_df) > 0 else 50
    pre_atr = before_df['atr_pct'].mean() if len(before_df) > 0 else 1.0
    pre_vol = before_df['vol_ratio'].mean() if len(before_df) > 0 else 1.0
    pre_mom = before_df['mom_4h'].mean() if len(before_df) > 0 else 0
    pre_fng = before_df['fng_value'].iloc[-1] if len(before_df) > 0 else 50

    # POST-EVENT features (next 120 min)
    post_rsi = after_df['rsi14'].mean()
    post_atr = after_df['atr_pct'].mean()
    post_vol = after_df['vol_ratio'].mean()
    post_mom = after_df['mom_4h'].mean()

    # REACTION MEASURE: average PnL if entered at event time
    # Simulamos: entrada en event_time, stop -2%, target +3%
    entry_prices = after_df['entry_price'].iloc[0:1].values
    if len(entry_prices) == 0:
        return None

    entry_price = entry_prices[0]
    highs = after_df['high'].values
    lows = after_df['low'].values

    target_price = entry_price * 1.03
    stop_price = entry_price * 0.98

    hit_target = (highs >= target_price).any()
    hit_stop = (lows <= stop_price).any()

    if hit_target and not hit_stop:
        reaction = "WIN"  # Spike favorable
        spike_magnitude = (highs.max() - entry_price) / entry_price
    elif hit_stop:
        reaction = "LOSS"  # Spike desfavorable
        spike_magnitude = (lows.min() - entry_price) / entry_price
    else:
        reaction = "NORMAL"  # Sin spike importante
        spike_magnitude = (after_df['close'].iloc[-1] - entry_price) / entry_price

    return {
        "event_date": event_date,
        "event_name": event_name,
        "impact": impact,
        "event_time": event_time,
        "pairs_affected": ",".join(pairs) if pairs else "all",

        # Pre-event context
        "pre_rsi": round(pre_rsi, 2),
        "pre_atr_pct": round(pre_atr, 3),
        "pre_vol_ratio": round(pre_vol, 2),
        "pre_momentum": round(pre_mom, 2),
        "pre_fng": round(pre_fng, 1),

        # Post-event reaction
        "post_rsi": round(post_rsi, 2),
        "post_atr_pct": round(post_atr, 3),
        "post_vol_ratio": round(post_vol, 2),
        "post_momentum": round(post_mom, 2),

        # Outcome
        "reaction": reaction,
        "spike_magnitude": round(spike_magnitude * 100, 2),  # %
        "hours_to_reaction": len(after_df) * 5 / 60,  # 5-min bars to hours
    }

def main():
    print(f"\n📊 Extrayendo features de eventos...")

    # Load features
    df = pd.read_csv(CSV_PATH).sort_values("ts")
    df['dt_iso'] = pd.to_datetime(df['dt_iso'])
    # Use entry_price as reference, estimate high/low from ATR
    df['high'] = df['entry_price'] * (1 + df['atr_pct']/100)
    df['low'] = df['entry_price'] * (1 - df['atr_pct']/100)
    df['close'] = df['entry_price']  # Approx

    # Get events
    events = get_events()
    print(f"   Total eventos: {len(events)}")

    # Extract features for each event
    event_features = []
    for event in events:
        event_date = event.get('date')
        event_time = event.get('time', '13:30')
        event_name = event.get('event', '')
        impact = event.get('impact', 'MEDIUM')
        affected = event.get('affected_pairs', [])

        # Para este MVP, procesamos event features agregadas
        # (en producción, haríamos por pair)
        feat = event_window_features(
            df, event_date, event_time, event_name, impact, affected
        )
        if feat:
            event_features.append(feat)

    # Create DataFrame
    result_df = pd.DataFrame(event_features)

    # Save
    out_path = os.path.join(ROOT, "results", "event_features.csv")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    result_df.to_csv(out_path, index=False)

    print(f"\n✅ Extracción completada:")
    print(f"   {len(result_df)} eventos con features")
    print(f"   Guardado: {out_path}")

    # Statistics
    print("\nReacciones a eventos:")
    win_count = (result_df['reaction']=='WIN').sum()
    loss_count = (result_df['reaction']=='LOSS').sum()
    normal_count = (result_df['reaction']=='NORMAL').sum()
    print(f"   WIN (favorable): {win_count}")
    print(f"   LOSS (unfavorable): {loss_count}")
    print(f"   NORMAL: {normal_count}")

    print("\nImpacto promedio por tipo:")
    for impact_type in ['CRITICAL', 'HIGH', 'MEDIUM']:
        subset = result_df[result_df['impact'] == impact_type]
        if len(subset) > 0:
            win_pct = 100 * (subset['reaction']=='WIN').sum() / len(subset)
            avg_spike = subset['spike_magnitude'].mean()
            print("   " + impact_type + ": " + str(round(win_pct, 1)) + "% WIN, avg spike " + str(round(avg_spike, 2)) + "%")

    return result_df

if __name__ == "__main__":
    main()
