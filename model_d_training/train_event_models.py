#!/usr/bin/env python3
"""
train_event_models.py — Entrena modelos que predicen reaccion a eventos.

Toma los 4.6M klines y 39 eventos globales.
Para cada evento, mide si el precio subio/bajo los proximos minutos.

Entrena 3 modelos:
  1. Conservative: Predice solo cambios grandes (>2%)
  2. Aggressive: Predice movimientos medianos (>0.5%)
  3. News-Spike: Predice picos de volatilidad post-evento
"""
import os, sys, json, pandas as pd, numpy as np
from datetime import datetime, timedelta
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
import pickle

ROOT = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(ROOT, "state", "features_d.csv")
RESULTS_DIR = os.path.join(ROOT, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

print("\n=== Event-Driven Model Training ===\n")

# Load data
df = pd.read_csv(CSV_PATH).sort_values("ts")
df['dt_iso'] = pd.to_datetime(df['dt_iso'])
print(f"Loaded {len(df)} rows from features_d.csv")

# Get events
from global_events_2026 import GLOBAL_EVENTS_2026, POTENTIAL_CRISIS_EVENTS
events = GLOBAL_EVENTS_2026 + POTENTIAL_CRISIS_EVENTS
print(f"Loaded {len(events)} events from 2026\n")

# ======== FEATURE ENGINEERING ========

def extract_event_features(df, event_dict):
    """Extract features around a single event"""
    event_date = event_dict.get('date')
    event_time = event_dict.get('time', '13:30')
    event_str = event_date + " " + event_time

    try:
        event_dt = pd.to_datetime(event_str)
    except:
        return None

    window_start = event_dt - timedelta(minutes=30)
    window_end = event_dt + timedelta(minutes=120)

    # Get window data
    mask = (df['dt_iso'] >= window_start) & (df['dt_iso'] <= window_end)
    window = df[mask].copy()

    if len(window) < 15:
        return None

    # Split before/after
    before = window[window['dt_iso'] < event_dt]
    after = window[window['dt_iso'] >= event_dt]

    if len(before) < 5 or len(after) < 5:
        return None

    # Compute features
    features = {
        'pre_rsi': before['rsi14'].mean(),
        'pre_mom': before['mom_4h'].mean(),
        'pre_atr': before['atr_pct'].mean(),
        'pre_vol': before['vol_ratio'].mean(),
        'pre_fng': before['fng_value'].iloc[-1],
        'post_rsi': after['rsi14'].mean(),
        'post_mom': after['mom_4h'].mean(),
        'post_atr': after['atr_pct'].mean(),
        'post_vol': after['vol_ratio'].mean(),
        'hour': event_dt.hour,
        'impact': event_dict.get('impact', 'MEDIUM'),
    }

    # Target: did price move significantly after event?
    post_price_change = (after['entry_price'].iloc[-1] - after['entry_price'].iloc[0]) / after['entry_price'].iloc[0] * 100

    return features, post_price_change, event_dict.get('impact')

# Extract features for all events
X_list = []
y_conservative = []
y_aggressive = []
y_spike = []

for event in events:
    result = extract_event_features(df, event)
    if result is None:
        continue

    features, price_change, impact = result
    X_list.append(features)

    # Different targets for different models
    y_conservative.append(1 if abs(price_change) > 2.0 else 0)  # Only big moves
    y_aggressive.append(1 if abs(price_change) > 0.5 else 0)    # Even small moves
    y_spike.append(1 if price_change > 1.0 else 0)              # Upside bias (spike)

X = pd.DataFrame(X_list)
print(f"Extracted {len(X)} event windows\n")

if len(X) < 20:
    print("ERROR: Not enough event features extracted. Check data.")
    sys.exit(1)

# Drop non-numeric impact column, one-hot encode
X = pd.get_dummies(X, columns=['impact'], drop_first=True)

print(f"Training sets:")
print(f"  Conservative (>2%): {sum(y_conservative)} positive, {len(y_conservative)-sum(y_conservative)} negative")
print(f"  Aggressive (>0.5%): {sum(y_aggressive)} positive, {len(y_aggressive)-sum(y_aggressive)} negative")
print(f"  Spike (>1% up):     {sum(y_spike)} positive, {len(y_spike)-sum(y_spike)} negative")

# ======== TRAIN MODELS ========

results = {}

for name, y in [("conservative", y_conservative), ("aggressive", y_aggressive), ("spike", y_spike)]:
    print(f"\nTraining {name} model...")

    # Split
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=42)

    # Scale
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    # Train
    model = LogisticRegression(max_iter=1000, random_state=42)
    model.fit(X_train_scaled, y_train)

    # Evaluate
    train_score = model.score(X_train_scaled, y_train)
    test_score = model.score(X_test_scaled, y_test)

    print(f"  Train ACC: {train_score:.3f}")
    print(f"  Test ACC:  {test_score:.3f}")

    # Save
    model_path = os.path.join(RESULTS_DIR, f"event_model_{name}.pkl")
    with open(model_path, 'wb') as f:
        pickle.dump({'model': model, 'scaler': scaler, 'features': X.columns.tolist()}, f)

    results[name] = {
        'train_accuracy': float(train_score),
        'test_accuracy': float(test_score),
        'n_events': len(y),
        'n_positive': int(sum(y)),
        'positive_rate': float(sum(y) / len(y))
    }

# Save results
results_path = os.path.join(RESULTS_DIR, "event_models_summary.json")
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2)

print(f"\n✅ Saved models to {RESULTS_DIR}/")
print(f"✅ Summary: {results_path}")
print("\nRECOMMENDATION:")
best = max(results.items(), key=lambda x: x[1]['test_accuracy'])
print(f"  Use '{best[0]}' model (test accuracy: {best[1]['test_accuracy']:.1%})")
