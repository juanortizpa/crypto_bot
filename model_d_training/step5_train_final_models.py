#!/usr/bin/env python3
"""
step5_train_final_models.py - Train final models for deployment.

This is the FINAL step after Step 4 expands event windows.

Input: event_training_data_expanded.csv (50-150 event windows)
Output:
  - Trained models ready for testnet
  - Performance comparison report
  - Recommendation for best model
"""
import pandas as pd
import numpy as np
import json
import os
import pickle
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(ROOT, "results")

print("\n" + "="*80)
print("STEP 5: Train Final Models (Expanded Data)")
print("="*80 + "\n")

# ════════════════════════════════════════════════════════════════════════════
# CHECK FOR EXPANDED DATA
# ════════════════════════════════════════════════════════════════════════════

expanded_path = os.path.join(RESULTS_DIR, "event_training_data_expanded.csv")
fallback_path = os.path.join(RESULTS_DIR, "event_training_data.csv")

if os.path.exists(expanded_path):
    print(f"✅ Found expanded data: {expanded_path}")
    df = pd.read_csv(expanded_path)
    is_expanded = True
elif os.path.exists(fallback_path):
    print(f"⚠️  Using fallback data: {fallback_path}")
    print(f"   (Run step4_expand_event_windows.py first for better results)")
    df = pd.read_csv(fallback_path)
    is_expanded = False
else:
    print(f"❌ ERROR: No data found at {expanded_path} or {fallback_path}")
    exit(1)

df['date'] = pd.to_datetime(df['event_date'])
print(f"Loaded {len(df)} event windows\n")

# ════════════════════════════════════════════════════════════════════════════
# PREPARE DATA
# ════════════════════════════════════════════════════════════════════════════

feature_cols = [
    'rsi_pre', 'mom_pre', 'atr_pre', 'vol_pre', 'fng', 'btc_dom',
    'rsi_post', 'mom_post', 'atr_post', 'vol_post',
    'hour', 'day_week'
]

X = df[feature_cols].copy().fillna(df[feature_cols].mean())

# Add engineered features
X['rsi_change'] = df['rsi_post'] - df['rsi_pre']
X['mom_change'] = df['mom_post'] - df['mom_pre']
X['atr_change'] = df['atr_post'] - df['atr_pre']
X['vol_change'] = df['vol_post'] - df['vol_pre']

# Normalize
for col in X.columns:
    mean = X[col].mean()
    std = X[col].std() + 1e-8
    X[col] = (X[col] - mean) / std

# Time-series split (80/20)
split_idx = int(0.8 * len(df))
X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
df_train, df_test = df.iloc[:split_idx], df.iloc[split_idx:]

print(f"Train/Test split: {len(X_train)}/{len(X_test)} samples")
print(f"Train period: {df_train['date'].min().date()} to {df_train['date'].max().date()}")
print(f"Test period: {df_test['date'].min().date()} to {df_test['date'].max().date()}\n")

# ════════════════════════════════════════════════════════════════════════════
# LOGISTIC REGRESSION MODEL
# ════════════════════════════════════════════════════════════════════════════

class SimpleLogisticModel:
    def __init__(self, learning_rate=0.01, iterations=200):
        self.lr = learning_rate
        self.iters = iterations
        self.weights = None
        self.bias = None

    def sigmoid(self, z):
        return 1 / (1 + np.exp(-np.clip(z, -500, 500)))

    def fit(self, X, y):
        if len(np.unique(y)) < 2:
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

    def predict(self, X, threshold=0.5):
        return (self.predict_proba(X) > threshold).astype(int)

    def score(self, X, y):
        return np.mean(self.predict(X) == y)


# ════════════════════════════════════════════════════════════════════════════
# TRAIN 4 MODELS
# ════════════════════════════════════════════════════════════════════════════

models_config = {
    'A_Conservative': {
        'label': 'label_conservative',
        'description': 'Moves > 2% (high confidence)',
        'threshold': 0.5
    },
    'B_Aggressive': {
        'label': 'label_aggressive',
        'description': 'Moves > 0.5% (catch trends)',
        'threshold': 0.45
    },
    'C_Spike': {
        'label': 'label_spike',
        'description': 'Upspikes > 1% (momentum)',
        'threshold': 0.45
    },
    'D_Dip': {
        'label': 'label_dip',
        'description': 'Downspikes > -1% (panic)',
        'threshold': 0.45
    },
}

results = {}
best_f1 = 0
best_model_name = None

for model_name, config in models_config.items():
    print(f"\nTraining {model_name}: {config['description']}")
    print("─" * 80)

    # Get labels
    y_train = df_train[config['label']].values.astype(int)
    y_test = df_test[config['label']].values.astype(int)

    print(f"  Train: {y_train.sum()}/{len(y_train)} positive ({100*y_train.mean():.1f}%)")
    print(f"  Test:  {y_test.sum()}/{len(y_test)} positive ({100*y_test.mean():.1f}%)")

    # Train
    model = SimpleLogisticModel(learning_rate=0.1, iterations=500)
    model.fit(X_train.values, y_train)

    # Evaluate
    threshold = config['threshold']
    y_train_pred = model.predict(X_train.values, threshold)
    y_test_pred = model.predict(X_test.values, threshold)

    y_test_proba = model.predict_proba(X_test.values)

    # Metrics
    train_acc = np.mean(y_train_pred == y_train)
    test_acc = np.mean(y_test_pred == y_test)

    # Precision & Recall on test set
    tp = ((y_test_pred == 1) & (y_test == 1)).sum()
    fp = ((y_test_pred == 1) & (y_test == 0)).sum()
    fn = ((y_test_pred == 0) & (y_test == 1)).sum()
    tn = ((y_test_pred == 0) & (y_test == 0)).sum()

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * (precision * recall) / (precision + recall + 1e-8)

    # Win rate (% of trades that are correct)
    win_rate = tp / (tp + fp) if (tp + fp) > 0 else 0
    trade_count = (y_test_pred == 1).sum()

    print(f"\n  Train Accuracy: {train_acc:.1%}")
    print(f"  Test Accuracy:  {test_acc:.1%}")
    print(f"  Test Precision: {precision:.1%} ({tp} TP, {fp} FP)")
    print(f"  Test Recall:    {recall:.1%} ({tp} TP, {fn} FN)")
    print(f"  F1-Score:       {f1:.1%}")
    print(f"  Win Rate:       {win_rate:.1%} on {trade_count} trades")

    # Save model
    model_path = os.path.join(RESULTS_DIR, "models", f"{model_name}_final.pkl")
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    with open(model_path, 'wb') as f:
        pickle.dump({
            'model': model,
            'feature_cols': X.columns.tolist(),
            'config': config,
            'performance': {
                'train_accuracy': float(train_acc),
                'test_accuracy': float(test_acc),
                'precision': float(precision),
                'recall': float(recall),
                'f1': float(f1),
                'win_rate': float(win_rate),
                'trades': int(trade_count),
            }
        }, f)

    results[model_name] = {
        'description': config['description'],
        'train_accuracy': float(train_acc),
        'test_accuracy': float(test_acc),
        'precision': float(precision),
        'recall': float(recall),
        'f1': float(f1),
        'win_rate': float(win_rate),
        'trades': int(trade_count),
        'tp': int(tp),
        'fp': int(fp),
        'fn': int(fn),
        'tn': int(tn),
        'model_path': model_path,
    }

    if f1 > best_f1:
        best_f1 = f1
        best_model_name = model_name

# ════════════════════════════════════════════════════════════════════════════
# SUMMARY & RECOMMENDATION
# ════════════════════════════════════════════════════════════════════════════

print(f"\n\n{'='*80}")
print("SUMMARY: Final Model Performance")
print(f"{'='*80}\n")

summary_df = pd.DataFrame(results).T[['description', 'test_accuracy', 'precision', 'recall', 'f1', 'win_rate', 'trades']]
print(summary_df.to_string())

print(f"\n{'='*80}")
print("RECOMMENDATION FOR DEPLOYMENT")
print(f"{'='*80}\n")

if best_model_name:
    best_perf = results[best_model_name]
    print(f"🏆 Best Model: {best_model_name}")
    print(f"   {best_perf['description']}")
    print(f"   F1-Score: {best_perf['f1']:.1%}")
    print(f"   Win Rate: {best_perf['win_rate']:.1%} ({int(best_perf['trades'])} trades)")
    print(f"   Precision: {best_perf['precision']:.1%} (low false positives)")
    print(f"   Saved: {best_perf['model_path']}")

    if best_perf['win_rate'] > 0.50:
        print(f"\n✅ READY FOR TESTNET!")
        print(f"   This model shows promising performance (>{50}% win rate)")
        print(f"   Next: python run_crypto_models.py (paper trading)")
    elif best_perf['win_rate'] > 0.45:
        print(f"\n⚠️  BORDERLINE - Use with caution")
        print(f"   Performance is marginal ({best_perf['win_rate']:.0%} win rate)")
        print(f"   Consider ensemble or more data")
    else:
        print(f"\n❌ NOT READY - Need more work")
        print(f"   Win rate < 45% ({best_perf['win_rate']:.0%})")
        print(f"   Suggestions:")
        print(f"     - Expand data further (more synthetic events)")
        print(f"     - Adjust label thresholds")
        print(f"     - Add more technical indicators")
        print(f"     - Consider ensemble methods")

# Save results
results_json = os.path.join(RESULTS_DIR, "final_models_results.json")
with open(results_json, 'w') as f:
    json.dump(results, f, indent=2)

print(f"\n✅ Results saved: {results_json}")

print(f"\n{'='*80}")
print("NEXT STEPS")
print(f"{'='*80}\n")

print("""
1. Deploy to Testnet (Paper Trading):
   export AUTO_EXECUTE=False
   export BINANCE_MODE=testnet
   python run_crypto_models.py

2. Monitor for 1-2 weeks:
   python bot_crypto.py compare

3. If win_rate > 50% after 50+ trades:
   export AUTO_EXECUTE=True
   export INITIAL_CAPITAL=10  # $10 testnet
   python run_crypto_models.py

4. If testnet > 50% over 1 month:
   Move to mainnet with real capital
""")

print()
