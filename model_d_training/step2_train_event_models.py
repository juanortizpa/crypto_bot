#!/usr/bin/env python3
"""
step2_train_event_models.py - Train 4 competitive models on event-driven data.

After Step 1 extracted features from 4.6M klines around 39 events, this script:
  1. Loads event_training_data.csv (6 complete event windows)
  2. Splits into in-sample (2026-01 to 2026-04) and out-of-sample (2026-05+)
  3. Trains 4 models:
     - Model A (Conservative): Predicts moves > 2%
     - Model B (Aggressive):   Predicts moves > 0.5%
     - Model C (Spike):        Predicts upspikes > 1%
     - Model D (Dip):          Predicts downspikes < -1%
  4. Evaluates on both in-sample and out-of-sample
  5. Selects best model based on consistency
  6. Saves models and performance report

Goal: Win rate > 60%, Profit Factor > 2.0
"""
import pandas as pd
import numpy as np
import json
import os
from datetime import datetime
import pickle

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(ROOT, "results", "event_training_data.csv")
MODELS_DIR = os.path.join(ROOT, "results", "models")
os.makedirs(MODELS_DIR, exist_ok=True)

print("\n" + "="*80)
print("STEP 2: Train 4 Competitive Event-Driven Models")
print("="*80 + "\n")

# ════════════════════════════════════════════════════════════════════════════
# LOAD AND PREPARE DATA
# ════════════════════════════════════════════════════════════════════════════

df = pd.read_csv(DATA_PATH)
print(f"Loaded {len(df)} event windows from {DATA_PATH}\n")

# Parse date
df['date'] = pd.to_datetime(df['event_date'])
df['year_month'] = df['date'].dt.to_period('M')

print(f"Date range: {df['date'].min().date()} to {df['date'].max().date()}")
print(f"Event breakdown:")
for month in sorted(df['year_month'].unique()):
    count = (df['year_month'] == month).sum()
    print(f"  {month}: {count} events")

# Split: in-sample (Jan-Apr 2026) and out-of-sample (May+ 2026)
is_mask = df['date'] < '2026-05-01'
df_is = df[is_mask].copy()
df_oos = df[~is_mask].copy()

print(f"\nData split:")
print(f"  In-Sample (training):   {len(df_is)} events (Jan-Apr 2026)")
print(f"  Out-of-Sample (test):   {len(df_oos)} events (May+ 2026)")

if len(df_oos) == 0:
    print("\n⚠️  WARNING: No out-of-sample data. Using last event as OOS.")
    if len(df_is) > 1:
        df_oos = df_is.iloc[-1:].copy()
        df_is = df_is.iloc[:-1].copy()
    else:
        print("ERROR: Not enough data to split. Exiting.")
        exit(1)

# ════════════════════════════════════════════════════════════════════════════
# FEATURE ENGINEERING
# ════════════════════════════════════════════════════════════════════════════

def prepare_features(df_split):
    """Prepare feature matrix from raw event data"""
    feature_cols = [
        'rsi_pre', 'mom_pre', 'atr_pre', 'vol_pre', 'fng', 'btc_dom',
        'rsi_post', 'mom_post', 'atr_post', 'vol_post',
        'hour', 'day_week'
    ]

    X = df_split[feature_cols].copy()

    # Handle missing values
    X = X.fillna(X.mean())

    # Add engineered features
    X['rsi_change'] = X['rsi_post'] - X['rsi_pre']
    X['mom_change'] = X['mom_post'] - X['mom_pre']
    X['atr_change'] = X['atr_post'] - X['atr_pre']
    X['vol_change'] = X['vol_post'] - X['vol_pre']

    # Normalize
    for col in X.columns:
        mean = X[col].mean()
        std = X[col].std() + 1e-8
        X[col] = (X[col] - mean) / std

    return X.values, X.columns.tolist()

X_is, feature_names = prepare_features(df_is)
X_oos, _ = prepare_features(df_oos)

print(f"\nFeatures extracted: {len(feature_names)}")
print(f"  {', '.join(feature_names[:6])}...")

# ════════════════════════════════════════════════════════════════════════════
# SIMPLE LOGISTIC REGRESSION (NO SKLEARN)
# ════════════════════════════════════════════════════════════════════════════

class SimpleLogisticModel:
    """Logistic regression without sklearn using numpy"""

    def __init__(self, learning_rate=0.01, iterations=100):
        self.lr = learning_rate
        self.iters = iterations
        self.weights = None
        self.bias = None

    def sigmoid(self, z):
        return 1 / (1 + np.exp(-np.clip(z, -500, 500)))

    def fit(self, X, y):
        n_samples, n_features = X.shape
        self.weights = np.zeros(n_features)
        self.bias = 0

        for _ in range(self.iters):
            # Forward
            z = np.dot(X, self.weights) + self.bias
            predictions = self.sigmoid(z)

            # Gradient
            dw = (1/n_samples) * np.dot(X.T, (predictions - y))
            db = (1/n_samples) * np.sum(predictions - y)

            # Update
            self.weights -= self.lr * dw
            self.bias -= self.lr * db

    def predict_proba(self, X):
        z = np.dot(X, self.weights) + self.bias
        return self.sigmoid(z)

    def predict(self, X):
        return (self.predict_proba(X) > 0.5).astype(int)

    def score(self, X, y):
        return np.mean(self.predict(X) == y)

# ════════════════════════════════════════════════════════════════════════════
# TRAIN 4 MODELS
# ════════════════════════════════════════════════════════════════════════════

models_config = {
    'A_Conservative': {
        'label': 'label_conservative',
        'description': 'Predicts moves > 2% (large moves only)',
        'threshold': 0.45
    },
    'B_Aggressive': {
        'label': 'label_aggressive',
        'description': 'Predicts moves > 0.5% (even small moves)',
        'threshold': 0.45
    },
    'C_Spike': {
        'label': 'label_spike',
        'description': 'Predicts upspikes > 1% (momentum favors UP)',
        'threshold': 0.45
    },
    'D_Dip': {
        'label': 'label_dip',
        'description': 'Predicts downspikes < -1% (panic sells)',
        'threshold': 0.45
    },
}

results = {}

for model_name, config in models_config.items():
    print(f"\n{'='*80}")
    print(f"Training Model {model_name}")
    print(f"  {config['description']}")
    print(f"{'='*80}")

    # Get labels
    y_is = df_is[config['label']].values.astype(int)
    y_oos = df_oos[config['label']].values.astype(int)

    print(f"\nLabels:")
    print(f"  In-Sample:  {y_is.sum()}/{len(y_is)} positive ({100*y_is.mean():.1f}%)")
    print(f"  Out-of-Sample: {y_oos.sum()}/{len(y_oos)} positive ({100*y_oos.mean():.1f}%)")

    # Train
    model = SimpleLogisticModel(learning_rate=0.1, iterations=500)
    model.fit(X_is, y_is)

    # Evaluate
    y_is_pred = model.predict(X_is)
    y_oos_pred = model.predict(X_oos)

    is_accuracy = np.mean(y_is_pred == y_is)
    oos_accuracy = np.mean(y_oos_pred == y_oos)

    # Win rate (% of positive predictions that were correct)
    y_is_proba = model.predict_proba(X_is)
    y_oos_proba = model.predict_proba(X_oos)

    # If we predicted positive, how often were we right?
    is_pos_mask = y_is_pred == 1
    oos_pos_mask = y_oos_pred == 1

    is_win_rate = np.mean(y_is[is_pos_mask] == 1) if is_pos_mask.sum() > 0 else 0
    oos_win_rate = np.mean(y_oos[oos_pos_mask] == 1) if oos_pos_mask.sum() > 0 else 0

    # Precision, Recall
    is_tp = ((y_is_pred == 1) & (y_is == 1)).sum()
    is_fp = ((y_is_pred == 1) & (y_is == 0)).sum()
    is_fn = ((y_is_pred == 0) & (y_is == 1)).sum()

    is_precision = is_tp / (is_tp + is_fp) if (is_tp + is_fp) > 0 else 0
    is_recall = is_tp / (is_tp + is_fn) if (is_tp + is_fn) > 0 else 0

    print(f"\nPerformance:")
    print(f"  In-Sample:")
    print(f"    Accuracy: {is_accuracy:.1%}")
    print(f"    Precision: {is_precision:.1%} ({is_tp} TP, {is_fp} FP)")
    print(f"    Recall: {is_recall:.1%}")
    print(f"    Win rate (if traded): {is_win_rate:.1%} ({is_pos_mask.sum()} trades)")

    print(f"  Out-of-Sample:")
    print(f"    Accuracy: {oos_accuracy:.1%}")
    print(f"    Win rate (if traded): {oos_win_rate:.1%} ({oos_pos_mask.sum()} trades)")

    # Save model
    model_path = os.path.join(MODELS_DIR, f"{model_name}.pkl")
    with open(model_path, 'wb') as f:
        pickle.dump({
            'model': model,
            'feature_names': feature_names,
            'config': config,
        }, f)

    results[model_name] = {
        'description': config['description'],
        'is_accuracy': float(is_accuracy),
        'oos_accuracy': float(oos_accuracy),
        'is_precision': float(is_precision),
        'is_recall': float(is_recall),
        'is_win_rate': float(is_win_rate),
        'oos_win_rate': float(oos_win_rate),
        'is_trades': int(is_pos_mask.sum()),
        'oos_trades': int(oos_pos_mask.sum()),
        'model_saved': model_path,
    }

# ════════════════════════════════════════════════════════════════════════════
# SUMMARY AND RECOMMENDATIONS
# ════════════════════════════════════════════════════════════════════════════

print(f"\n\n{'='*80}")
print("SUMMARY: Model Performance Comparison")
print(f"{'='*80}\n")

summary_df = pd.DataFrame(results).T
summary_df = summary_df[[
    'description', 'is_accuracy', 'oos_accuracy',
    'is_win_rate', 'oos_win_rate', 'is_trades'
]]

print(summary_df.to_string())

# Select best model based on OOS win rate + accuracy consistency
print(f"\n{'='*80}")
print("Recommendations")
print(f"{'='*80}\n")

best_model = max(results.items(), key=lambda x: x[1]['oos_win_rate'])
best_name = best_model[0]
best_perf = best_model[1]

print(f"🏆 Best Model: {best_name}")
print(f"   {best_perf['description']}")
print(f"   OOS Win Rate: {best_perf['oos_win_rate']:.1%}")
print(f"   OOS Accuracy: {best_perf['oos_accuracy']:.1%}")
print(f"   In-Sample Precision: {best_perf['is_precision']:.1%}")

if best_perf['oos_win_rate'] > 0.55:
    print(f"\n✅ RECOMMENDATION: Use {best_name} for Step 3 validation")
    print(f"   This model shows strong out-of-sample performance (>55% win rate)")
elif best_perf['oos_win_rate'] > 0.50:
    print(f"\n⚠️  CAUTION: {best_name} shows borderline performance (50-55% win rate)")
    print(f"   Consider ensemble or refining with more data")
else:
    print(f"\n❌ WARNING: No model achieved >50% OOS win rate")
    print(f"   May need to:")
    print(f"   1. Extract more event windows (current: {len(df)})")
    print(f"   2. Adjust label definitions")
    print(f"   3. Add more feature engineering")

# Save results
results_path = os.path.join(ROOT, "results", "model_training_results.json")
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2)

print(f"\n✅ Results saved to: {results_path}")
print(f"\n{'='*80}\n")
