# 🎯 Guía de Entrenamiento con Klines 5min + Eventos

## ¿Qué cambiÓ?

| Aspecto | Antes (1h) | Ahora (5min) | Beneficio |
|--------|-----------|------------|-----------|
| **Intervalo** | 1 hora | 5 minutos | 12x más data |
| **Velas/día** | 24 | 288 | Captura volatilidad real |
| **Velas/año/par** | ~8,760 | ~105,120 | +1,196% precisión |
| **Data 2024-2026** | ~52,560 bars | ~630,720 bars | 12x más entrenamiento |
| **Tiempo descarga** | ~5 min | ~45 min | Vale la pena (12x mejor) |
| **Tamaño DB** | ~20 MB | ~150 MB | Manejable en SSD |

---

## Flujo Completo (Paso a Paso)

### PASO 1: Descargar Klines 5min + Eventos (30-45 min)

```bash
cd crypto_bot

# Descarga 630K+ bars de 5 minutos (2024-2026)
python model_d_training/download_data.py

# Output esperado:
# === RESUMEN ===
# 📊 Klines 5min (NUEVA tabla ohlcv):
#   BTC       ~105,120 bars 5min  2024-01-01 → 2026-05-13
#   ETH       ~105,120 bars 5min  2024-01-01 → 2026-05-13
#   SOL       ~105,120 bars 5min  2024-01-01 → 2026-05-13
#   ...
#   TOTAL:    ~2,102,400 bars de 5min (5.8 años de data)
```

**Nota:** Si se interrumpe, vuelve a correr — reanuda desde donde paró.

---

### PASO 2: Marcar Eventos (2 min)

```bash
# Inserta 30+ eventos globales de 2026 en la DB
# (FOMC, Jobs, Trump/Elon tweets, SEC decisions, ETF approvals, etc.)
python -c "from model_d_training.events_tracker import EventsTracker; t = EventsTracker(); t.insert_events(); print(t.get_stats())"

# Output:
# {'total_events': 32, 'klines_marked': 1,234, 'high_volatility_klines': 456, 'high_vol_percentage': '37.0%'}
```

---

### PASO 3: Feature Engineering (10-20 min)

```bash
# Genera features especiales para cada kline 5min:
# - Volatilidad intraday (ATR sobre 5min)
# - Momentum acumulativo (sobre 288 velas)
# - Impacto de eventos (si está en ventana de evento)
# - Correlación con BTC dominance
# - RSI, MACD, Bollinger Bands en escala 5min

python model_d_training/features.py

# Output esperado:
# ✅ Features calculados para 20 pares
# → 630,720 filas en features table
# Tiempo promedio: 12-18 min (depende PC)
```

---

### PASO 4: Entrenar 3 Modelos Competitivos (30-60 min)

Tienes 3 opciones según tu hardware:

#### **Opción A: Grid Search Simple (1-2 min, baseline)**
```bash
python model_d_training/train_grid.py
# Algoritmo: Búsqueda heurística sin ML libs
# Rápido, sin requisitos de libs
# Output: model_d_training/models/grid_model.pkl
```

#### **Opción B: XGBoost (10-20 min, RECOMENDADO)**
```bash
pip install xgboost lightgbm --break-system-packages

python model_d_training/train_xgb.py
# Entrena 2 modelos en paralelo:
#   1. XGBoost (gradient boosting)
#   2. LightGBM (faster gradient boosting)
# Output: model_d_training/models/xgb_model.pkl, lgb_model.pkl
```

#### **Opción C: Hybrid (5-10 min)**
```bash
python model_d_training/train_hybrid.py
# Combina:
#   - Filtros del grid search
#   - Logistic regression final
# Rápido + preciso, buen balance
# Output: model_d_training/models/hybrid_model.pkl
```

**Recomendación:** Corre los 3 en secuencia:
```bash
python model_d_training/train_grid.py && \
python model_d_training/train_xgb.py && \
python model_d_training/train_hybrid.py
```

---

### PASO 5: Validación Walk-Forward (15-30 min)

Crucial para saber cuál modelo es mejor sin overfitting:

```bash
python model_d_training/compare.py

# Output esperado (ejemplo):
# ╔═══════════════════════════════════════════════════════════╗
# ║ WALK-FORWARD VALIDATION (OOS TEST)                       ║
# ╠═══════════════════════════════════════════════════════════╣
# ║                                                           ║
# ║ Grid Search (baseline):                                 ║
# ║   Win Rate:         42.3%                               ║
# ║   Sharpe Ratio:     0.68                                ║
# ║   Max Drawdown:    -12.5%                               ║
# ║   Profit Factor:    1.23                                ║
# ║                                                           ║
# ║ XGBoost:  ⭐ WINNER                                      ║
# ║   Win Rate:         56.8%  ← MEJOR                      ║
# ║   Sharpe Ratio:     1.45   ← MEJOR                      ║
# ║   Max Drawdown:     -8.2%  ← MEJOR                      ║
# ║   Profit Factor:    1.89   ← MEJOR                      ║
# ║                                                           ║
# ║ LightGBM:                                               ║
# ║   Win Rate:         54.2%                               ║
# ║   Sharpe Ratio:     1.23                                ║
# ║   Max Drawdown:    -9.8%                                ║
# ║                                                           ║
# ║ Hybrid:                                                  ║
# ║   Win Rate:         48.1%                               ║
# ║   Sharpe Ratio:     0.95                                ║
# ║   Max Drawdown:    -10.5%                               ║
# ║                                                           ║
# ║ 📊 Recomendación: Usar XGBoost para testnet             ║
# ╚═══════════════════════════════════════════════════════════╝
```

---

## Cómo los Eventos Afectan el Entrenamiento

### 1. **Marcar Klines con Eventos**
Cada kline dentro de ventana de evento (±120min) recibe:
- `event_id`: Qué evento afectó
- `impact`: HIGH, MEDIUM, LOW
- `category`: monetary_policy, political, labor, etc.
- `minutes_from_event`: -30, 0, +60, etc.

### 2. **Features Generados**
```python
# Features especiales de eventos en cada kline:
- is_event_window = 1 si está en ventana
- minutes_from_event = diferencia en minutos
- event_impact = high=3, medium=2, low=1
- volatility_spike = std() en ventana
- momentum_change = momentum pre vs post evento
```

### 3. **Aprender Patrones de Reacción**
El modelo aprende:
- Qué eventos causan más volatilidad
- Cuánto tiempo tarda la reacción (1min? 30min? 2h?)
- Si la reacción es alcista o bajista por tipo de evento
- Ejemplo: Trump tweet → DOGE pump inmediato
- Ejemplo: FOMC decision → BTC volatilidad 2h

---

## Tamaños de Data

```
2024-2026 (30 meses):
├─ 20 pares
├─ 288 velas/día (5min)
└─ ~105K bars/par/30meses
   = ~2.1M total bars
   = ~150 MB SQLite DB
   
Training/Validation Split:
├─ In-Sample (IS):  2024-01-01 → 2025-12-31  (24 meses)
│                   = 1.4M bars
└─ Out-of-Sample (OOS): 2026-01-01 → 2026-05-13  (5 meses)
                   = 700K bars
                   (Aquí mides real performance)
```

---

## Problemas Comunes

### "Too much memory"
```bash
# Reduce features.py a un solo par para probar:
# Edita features.py línea 35: TOP_20 = ["BTC"]
python model_d_training/features.py
```

### "ValueError: cannot reindex on an axis with duplicate labels"
```bash
# Elimina data_2026.db e inicia de 0:
rm model_d_training/state/data_2026.db
python model_d_training/download_data.py
```

### "Binance API rate limit"
```bash
# El script intenta 5 veces con backoff exponencial
# Espera ~10 min si ves: "retry 5/5"
# Luego vuelve a correr
```

---

## Comparación: 1h vs 5min Training

```
MÉTRICA                 | 1h KLINES      | 5min KLINES
─────────────────────────────────────────────────────
Bars por par           | 8,760          | 105,120      (12x)
Total bars 20 pares    | 175,200        | 2,102,400    (12x)
Ventanas de entrada    | 8,700          | 105,100      (12x)
Volatilidad capturada  | Media          | Alta         (intra-day)
Reacción a noticias    | 1h delay       | 5min delay   (real-time)
Overfitting risk       | Bajo           | Moderado     (mitigado con OOS)
Tiempo entrenamiento   | 5 min          | 60 min       (10x)
Accuracy esperada      | 48-52%         | 54-58%       (+6%)
Sharpe Ratio esperado  | 0.8-1.2        | 1.2-1.8      (mejor)
─────────────────────────────────────────────────────
```

---

## Siguiente Paso: Testnet Live

Una vez completado compare.py:

```bash
# 1. Identificar ganador (ej: XGBoost)
# 2. Copiar model_d_training/models/xgb_model.pkl → bot/
# 3. Editar .env:
    AUTO_EXECUTE=True
    BINANCE_MODE=testnet
# 4. Correr:
    python run_crypto_models.py
```

---

## Archivos Clave

- **download_data.py**: Descarga 5min + prepara DB
- **global_events_2026.py**: 30+ eventos globales con fechas exactas
- **events_tracker.py**: Marca klines afectados por eventos
- **features.py**: Genera 50+ features incluyendo contexto de eventos
- **compare.py**: Walk-forward validation (CRÍTICO antes de live)

---

## Timeline Esperado (Primera Vez)

```
Descargar data:              45 min  ⏳
Marcar eventos:              2 min   ⚡
Feature engineering:         15 min  ⏳
Train Grid:                  2 min   ⚡
Train XGBoost:              20 min   ⏳
Train Hybrid:               10 min   ⏳
Validation & compare:       30 min   ⏳
────────────────────────────────────────
TOTAL:                      124 min  (~2 horas)
```

**Después de la primera vez:** Solo ~45 min (solo reentrenamiento de modelos).

---

## Próximas Optimizaciones

Después de validar en testnet:

1. **Fine-tune thresholds** (crypto_gate.py): Ajusta para 5min volatilidad
2. **Event-driven trading**: Activar Modelo C (News Spike) con eventos CRITICAL
3. **Add more crypto data**: Incluir Glassnode (whale movements) en features
4. **Ensemble**: Meta model que pesa XGBoost + Hybrid

---

**¿Listo?** Corre: `python model_d_training/download_data.py`
