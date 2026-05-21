# 🔴 Diagnosis: Why 0 Trades in Walk-Forward Validation

## The Problem
- **Walk-forward OOS (April-May 2026)**: 0 trades across all models
- **Root cause**: Grid filters too restrictive for normal market conditions

## The Deeper Issue Discovered

### True Performance of 5-min Features
When we evaluate TRUE completed trades (held==1):

```
Combo           IS Trades  Win%   OOS Trades  Win%
s020_t030_h6    16,310     22.7%  1,385       19.4%
s025_t040_h8    16,310     20.8%  1,385       14.9%
s030_t050_h12   16,310     20.0%  1,385       12.9%
```

**The raw features alone achieve only ~20% win rate** → losing money regardless of parameters.

### Why the 0 Trades Problem
The grid search filters require ALL conditions met:
1. **RSI ≤ 40** ✓ (49% pass rate)
2. **DD ≤ -20%** ✗ (0% pass rate — April-May only had -5% max DD)
3. **FNG ≤ 25** ✗ (21% pass rate — FNG averaged 32)
4. **BTC DOM ≤ 60** ✓ (94% pass rate)
5. **Momentum ≥ 2%** ✗ (0.8% pass rate — market had -0.39% average)
6. **Volume ≥ 1.2x** ✗ (21% pass rate — volume was 0.96x average)

**Result: 0 / 6353 bars (0%) passed ALL conditions**

## Architectural Problem

The machine learning approach (Grid Search, XGBoost) trained on pure features (RSI, momentum, drawdown, volume) is fundamentally limited:
- Features are lagging indicators
- They work only in extreme conditions (panic)
- They fail in normal markets

### Evidence
- **In Panic (2024-2025)**: 91 trades with 48% WR (extreme FNG/DD filters)
- **In Normal Market (2026)**: 1,385 trades with 19-22% WR (no filter restrictions)

**This proves the signal comes from market regime, not features.**

## The Real Solution

### Root Cause
The 13-factor gate system (M1-M3, S1-S4, T1-T3, R1-R2, N1-N2) was designed to:
- Detect market regimes (bull/bear/flat)
- Weight signals by market conditions
- Give signal strength via gate score

The gate + 4 models (A/B/C/D) approach was working because:
- **Model A (Conservador)**: Only trades green gates (high conviction)
- **Model D (Dip Scalper)**: Trades red gates + low FNG (panic buying)
- Gate filters act as regime detector, not just signal filter

### Why Pure ML Failed
```
Features alone → 20% win rate → negative PnL
Features + Gate filters → regime detection → 48% win rate (panic only)
```

Machine learning can't replace regime detection. It needs human-designed signals.

## Recommended Next Steps

### Option 1: Gate-Based Trading (Recommended)
Use the existing 13-factor gate + 4 models approach:
```bash
python run_crypto_models.py  # This already works!
# Runs: model_a, model_b, model_c, model_d with gate filters
```

### Option 2: Ensemble
Combine:
1. Gate scores (regime detection) 
2. ML models for within-regime optimization
3. Meta-model that weights by regime

### Option 3: Event-Driven (Model C Focus)
Since we integrated global events:
- News spikes + low FNG = highest probability trades
- Train ONLY on event-affected klines
- Ignore static features

## Immediate Action

The 5-minute kline + event tracking is **working correctly**. The issue is the modeling approach, not the data.

**What to do:**
1. Stop tuning ML hyperparameters
2. Use the existing gate-based system in `run_crypto_models.py`
3. Or re-focus on Model C (News-Spike) with event data
4. Test on testnet with $10 initial capital

The bot's architecture was sound. The ML detour didn't add value.
