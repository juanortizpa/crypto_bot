# Model D Training Pipeline

Pipeline completo para entrenar y desplegar el **Modelo D (Dip Scalper)**
con datos 2026 y los 20 pares de `bot/top20_pairs.py`.

---

## Por que solo Modelo D?

Es el modelo del bot que mejor funciona historicamente. Esta carpeta lo
afina con tres enfoques en paralelo y elige (o combina) el mejor antes
de meter dinero real:

  - **Trainer A — Grid search** (heuristico, sin libs externas)
  - **Trainer B — XGBoost** (clasificador binario WIN/no-WIN)
  - **Trainer C — Hibrido** (filtros del grid + logistic regression)
  - **Comparador** evalua los 3 sobre los ultimos 30 dias *out-of-sample*
    y prueba 4 ensembles (majority 2of3, any, all, prob avg).

---

## Setup (en tu PC Windows, no en la sandbox)

```bash
cd "C:\Users\JUAN\Documents\Claude\Projects\operacion cripto\crypto_bot"

# Solo si vas a usar XGBoost / Hybrid:
pip install pandas numpy scikit-learn xgboost
# (si xgboost falla en tu maquina: pip install lightgbm)
```

El **Trainer A (grid)** corre solo con stdlib — sin instalar nada.

---

## Flujo (corre en orden)

```bash
# 1) Descargar datos 2026 (~30 min, depende de cuantos pares)
python -m model_d_training.download_data

# 2) Generar features + labels (puede tardar 1-2 min)
python -m model_d_training.features

# 3) Entrenar los 3 modelos
python -m model_d_training.train_grid     # Trainer A
python -m model_d_training.train_xgb      # Trainer B
python -m model_d_training.train_hybrid   # Trainer C

# 4) Comparar y elegir ganador (incluye ensembles)
python -m model_d_training.compare

# 5) Verificar en dry-run antes de poner dinero
python -m model_d_training.live_runner --dry-run --once

# 6) Probar en testnet (paper trading, sin dinero real)
python -m model_d_training.live_runner --paper

# 7) LIVE REAL — solo cuando estes 100% conforme
# Edita .env: AUTO_EXECUTE=True y BINANCE_MODE=live
python -m model_d_training.live_runner --live
```

---

## Salidas

| Archivo | Que es |
|---|---|
| `state/data_2026.db` | Klines crudos 1h + F&G |
| `state/features_d.csv` | Features + labels para 5 combos stop/target |
| `results/grid_top.json` | Top 50 combinaciones del grid |
| `results/grid_best.json` | Mejor config grid (para live) |
| `results/xgb_models.pkl` | Modelos XGB entrenados (uno por combo) |
| `results/xgb_best.json` | Mejor combo XGB + threshold |
| `results/hybrid_model.pkl` | Modelo hibrido + scaler |
| `results/hybrid_best.json` | Resumen hibrido |
| `results/comparison.json` | Ranking final + correlaciones |
| `results/winner_config.json` | Config que carga `live_runner.py` |
| `state/live_state.db` | Trades ejecutados en vivo |

---

## Safety guards del live runner ($10–$500 capital)

Todos configurables en `live_runner.py → DEFAULTS`:

```python
portfolio_usdt:        10.0   # tu balance — actualizalo
max_capital_per_trade: 0.50   # 50% del portfolio max por trade
min_notional_usdt:     5.10   # minimo Binance Spot
daily_loss_kill_pct:   0.15   # 15% en 24h → STOP automatico
total_dd_kill_pct:     0.25   # 25% drawdown total → KILL
max_concurrent:        1      # un trade simultaneo
cooldown_minutes:      60     # pausa entre trades del mismo par
scan_interval_minutes: 15     # cada cuanto escanea
fee_pct:               0.10   # 0.1% round-trip Binance
```

Con $10 y stop -2.5%, perdida max por trade = $0.125. Daily kill = $1.50.
Si quemas $2.50 en 24h, el bot se apaga solo.

---

## Checklist pre-LIVE

Antes de correr `--live`, confirma:

- [ ] El comparador muestra **WR > 55%** y **PF > 1.5** en OOS
- [ ] Corriste `--paper` durante al menos 1 semana sin perdidas grandes
- [ ] `.env` tiene `BINANCE_API_KEY` y `BINANCE_SECRET_KEY` validas (live)
- [ ] `.env` tiene `BINANCE_MODE=live` y `AUTO_EXECUTE=True`
- [ ] `CRYPTO_PORTFOLIO` en `.env` matchea tu balance real
- [ ] Las API keys tienen permiso de trading **pero NO de retiro**
- [ ] Tienes notificaciones puestas (email/telegram) por si el kill switch dispara

---

## Que hacer si el ganador es un ensemble

`live_runner.py` ya soporta los 4 tipos de ensemble. El `winner_config.json`
se autopopula con el ganador y `evaluate_signal()` aplica la logica correcta.

Si los 3 modelos individuales tienen correlacion < 0.6 entre senales,
es muy probable que el ensemble Majority 2of3 sea mejor (filtra ruido).

---

## Reentrenar cada N semanas

El mercado cambia. Recomendado:

```bash
# Cada 2-4 semanas:
python -m model_d_training.download_data    # actualiza datos
python -m model_d_training.features
python -m model_d_training.train_grid
python -m model_d_training.train_xgb
python -m model_d_training.train_hybrid
python -m model_d_training.compare
# Si el winner cambio y mejora >10%, redeploy:
python -m model_d_training.live_runner --paper --once  # smoke test
```
