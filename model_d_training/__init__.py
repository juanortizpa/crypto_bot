"""
Model D Training Pipeline.

Sub-paquete para entrenar y optimizar el Modelo D (Dip Scalper) usando
datos historicos 2026 (resolucion 1h) de los 20 pares de top20_pairs.py.

Flujo:
    1) download_data.py   → descarga klines 1h, F&G, BTC dominance → state/data_2026.db
    2) features.py        → calcula features + labels para entrenamiento
    3) train_grid.py      → optimizador A: grid search heuristico
    4) train_xgb.py       → optimizador B: XGBoost / LightGBM
    5) train_hybrid.py    → optimizador C: grid + logistic regression
    6) compare.py         → backtest walk-forward + ensemble
    7) live_runner.py     → wrapper live con safety guards

Salidas:
    state/data_2026.db        — datos crudos
    state/features_d.parquet  — features + labels
    results/grid_best.json    — mejores params grid
    results/xgb_model.pkl     — modelo entrenado xgb
    results/hybrid_model.pkl  — modelo entrenado hybrid
    results/comparison.json   — ranking final + ensemble config
"""
