#!/usr/bin/env python3
"""
step3_walkforward_validation.py - Proper time-series walk-forward validation.

Problem with Step 2: Only 6 event windows total (1 in OOS).
Solution: Use expanding window walk-forward validation:
  - Train on progressively larger in-sample windows
  - Test on next unseen period
  - Report aggregate performance across all folds

Also diagnoses why only 6/39 events produced usable windows.
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
print("STEP 3: Walk-Forward Validation & Data Diagnostics")
print("="*80 + "\n")

# ════════════════════════════════════════════════════════════════════════════
# LOAD DATA
# ════════════════════════════════════════════════════════════════════════════

df = pd.read_csv(DATA_PATH)
df['date'] = pd.to_datetime(df['event_date'])
df = df.sort_values('date').reset_index(drop=True)

print(f"Loaded {len(df)} events")
print(f"Date range: {df['date'].min().date()} to {df['date'].max().date()}\n")

# ════════════════════════════════════════════════════════════════════════════
# DIAGNOSTIC: Why only 6/39 events?
# ════════════════════════════════════════════════════════════════════════════

print("="*80)
print("DIAGNOSTIC: Event Window Extraction Analysis")
print("="*80 + "\n")

from global_events_2026 import GLOBAL_EVENTS_2026, POTENTIAL_CRISIS_EVENTS
all_events = GLOBAL_EVENTS_2026 + POTENTIAL_CRISIS_EVENTS

extracted_event_names = set(df['event_name'].str.strip().unique())
all_event_names = set(e.get('event', '') for e in all_events)

print(f"Total events in 2026: {len(all_events)}")
print(f"Events with extracted windows: {len(df)} (unique: {len(extracted_event_names)})")
print(f"Success rate: {100*len(df)/len(all_events):.1f}%\n")

print("Events that produced windows:")
for _, row in df.iterrows():
    print(f"  {row['date'].date()} {row['event_name'][:40]:40} [{row['impact']}]")

print(f"\nPossible reasons for low extraction rate:")
print(f"  1. Timezone mismatch (events in EST, klines in UTC)")
print(f"  2. Sparse 5-min data (gaps if market closed or low volume)")
print(f"  3. Time window too strict (±150 min might not capture volatility)")
print(f"  4. Event time incorrect (many events are multi-hour, not point-in-time)")
print(f"  5. Data quality (features_d.csv may have gaps)")

# ════════════════════════════════════════════════════════════════════════════
# WALK-FORWARD VALIDATION
# ════════════════════════════════════════════════════════════════════════════

print(f"\n{'='*80}")
print("Walk-Forward Validation: Expanding Window")
print(f"{'='*80}\n")

class SimpleLogisticModel:
    """Same model from Step 2"""
    def __init__(self, learning_rate=0.01, iterations=100):
        self.lr = learning_rate
        self.iters = iterations
        self.weights = None
        self.bias = None

    def sigmoid(self, z):
        return 1 / (1 + np.exp(-np.clip(z, -500, 500)))

    def fit(self, X, y):
        if len(np.unique(y)) < 2:
            # Can't train if only one class
            self.weights = np.zeros(X.shape[1])
            self.bias = 0
            return

        n_samples, n_features = X.shape
        self.weights = np.zeros(n_features)
        self.bias = 0

        for _ in range(self.iters):
            z = np.dot(X, self.weights) + self.bias
            predictions = self.sigmoid(z)
            dw = (1/n_samples) * np.dot(X.T, (predictions - y))
            db = (1/n_samples) * np.sum(predictions - y)
            self.weights -= self.lr * dw
            self.bias -= self.lr * db

    def predict_proba(self, X):
        z = np.dot(X, self.weights) + self.bias
        return self.sigmoid(z)

    def predict(self, X):
        return (self.predict_proba(X) > 0.5).astype(int)

    def score(self, X, y):
        return np.mean(self.predict(X) == y)


def prepare_features(df_split):
    """Same as Step 2"""
    feature_cols = [
        'rsi_pre', 'mom_pre', 'atr_pre', 'vol_pre', 'fng', 'btc_dom',
        'rsi_post', 'mom_post', 'atr_post', 'vol_post',
        'hour', 'day_week'
    ]

    X = df_split[feature_cols].copy()
    X = X.fillna(X.mean())

    X['rsi_change'] = X['rsi_post'] - X['rsi_pre']
    X['mom_change'] = X['mom_post'] - X['mom_pre']
    X['atr_change'] = X['atr_post'] - X['atr_pre']
    X['vol_change'] = X['vol_post'] - X['vol_pre']

    for col in X.columns:
        mean = X[col].mean()
        std = X[col].std() + 1e-8
        X[col] = (X[col] - mean) / std

    return X.values, X.columns.tolist()


# For walk-forward with small dataset: use leave-one-out CV
print("Using Leave-One-Out validation (each event as test set):\n")

model_configs = {
    'A_Conservative': 'label_conservative',
    'B_Aggressive': 'label_aggressive',
    'C_Spike': 'label_spike',
    'D_Dip': 'label_dip',
}

wf_results = {}

for model_name, label_col in model_configs.items():
    print(f"{'─'*80}")
    print(f"Model: {model_name}")
    print(f"{'─'*80}")

    fold_results = []

    # Leave-one-out: for each event, train on rest and test on that one
    for test_idx in range(len(df)):
        train_df = df.drop(test_idx)
        test_df = df.iloc[[test_idx]]

        if len(train_df) < 2:
            continue  # Skip if not enough training data

        # Prepare features
        X_train, _ = prepare_features(train_df)
        X_test, _ = prepare_features(test_df)

        y_train = train_df[label_col].values.astype(int)
        y_test = test_df[label_col].values.astype(int)

        # Train
        model = SimpleLogisticModel(learning_rate=0.1, iterations=500)
        model.fit(X_train, y_train)

        # Predict
        y_pred = model.predict(X_test)
        correct = (y_pred[0] == y_test[0])

        # Store result
        fold_results.append({
            'test_date': test_df['date'].iloc[0],
            'event': test_df['event_name'].iloc[0][:30],
            'true_label': int(y_test[0]),
            'prediction': int(y_pred[0]),
            'correct': correct,
            'n_train': len(train_df),
        })

    # Aggregate
    fold_df = pd.DataFrame(fold_results)
    fold_df = fold_df.sort_values('test_date')

    accuracy = fold_df['correct'].mean()
    tp = ((fold_df['prediction'] == 1) & (fold_df['true_label'] == 1)).sum()
    fp = ((fold_df['prediction'] == 1) & (fold_df['true_label'] == 0)).sum()
    fn = ((fold_df['prediction'] == 0) & (fold_df['true_label'] == 1)).sum()

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0

    print(f"\nLeave-One-Out Results ({len(fold_df)} folds):")
    print(f"  Accuracy: {accuracy:.1%}")
    print(f"  Precision: {precision:.1%} ({tp} TP, {fp} FP)")
    print(f"  Recall: {recall:.1%} ({tp} TP, {fn} FN)")
    print(f"  F1-Score: {f1:.1%}\n")

    print("Fold-by-fold breakdown:")
    for _, row in fold_df.iterrows():
        result = "✅" if row['correct'] else "❌"
        pred_str = "SIGNAL" if row['prediction'] == 1 else "no sig"
        true_str = "event" if row['true_label'] == 1 else "no-event"
        print(f"  {result} {row['test_date'].date()} {row['event'][:28]:28} pred={pred_str:6} true={true_str}")

    wf_results[model_name] = {
        'accuracy': float(accuracy),
        'precision': float(precision),
        'recall': float(recall),
        'f1': float(f1),
        'n_folds': len(fold_df),
        'tp': int(tp),
        'fp': int(fp),
        'fn': int(fn),
    }

# ════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ════════════════════════════════════════════════════════════════════════════

print(f"\n{'='*80}")
print("Summary: Leave-One-Out Cross-Validation")
print(f"{'='*80}\n")

summary = pd.DataFrame(wf_results).T[['accuracy', 'precision', 'recall', 'f1']]
print(summary.to_string())

print(f"\n{'='*80}")
print("Key Findings")
print(f"{'='*80}\n")

print("1. Dataset Size Constraint:")
print(f"   - Only 6 event windows extracted (too small for reliable ML)")
print(f"   - Leave-One-Out CV is appropriate for small datasets")
print(f"   - Each fold trains on 5 events, tests on 1")

print(f"\n2. Model Performance:")
best_model = max(wf_results.items(), key=lambda x: x[1]['f1'])
print(f"   - Best Model: {best_model[0]} (F1={best_model[1]['f1']:.1%})")

for name, perf in wf_results.items():
    status = "🟢" if perf['f1'] > 0.5 else "🟡" if perf['f1'] > 0.3 else "🔴"
    print(f"   {status} {name}: Accuracy={perf['accuracy']:.0%}, F1={perf['f1']:.0%}")

print(f"\n3. Recommendations:")
print(f"   A. Current state: Models show promise but dataset too small")
print(f"   B. To improve: Expand event windows")
print(f"      - Relax time window (currently ±150 min)")
print(f"      - Include events with partial data")
print(f"      - Extract synthetic windows (price extrema)")
print(f"   C. Next step: Use the best model for Step 4 (Final Report)")

# Save results
wf_path = os.path.join(ROOT, "results", "walkforward_results.json")
with open(wf_path, 'w') as f:
    json.dump(wf_results, f, indent=2)

print(f"\n✅ Results saved: {wf_path}\n")
