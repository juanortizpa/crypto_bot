# ARQUITECTURA - Crypto Trading Bot

## 📋 Visión General

Sistema automatizado de predicción y monitoreo de trading de criptomonedas en Binance (testnet/paper trading). Combina análisis técnico, sentimiento de mercado y noticias en tiempo real con 4 modelos predictivos competitivos.

```
┌─────────────────────────────────────────────────────────────┐
│                   CRYPTO TRADING BOT                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐      ┌──────────────┐  ┌──────────────┐  │
│  │ Data Layer  │◄─────┤ Binance API  │  │ Sentiment    │  │
│  │ (OHLCV)     │      │ (klines)     │  │ (News/FNG)   │  │
│  └──────┬──────┘      └──────────────┘  └──────────────┘  │
│         │                                                   │
│         ▼                                                   │
│  ┌────────────────────────────────────┐                   │
│  │     13-FACTOR GATE SYSTEM          │                   │
│  │  (Análisis técnico + sentimiento)  │                   │
│  │   GREEN / YELLOW / RED signals     │                   │
│  └────────────┬───────────────────────┘                   │
│               │                                             │
│               ▼                                             │
│  ┌────────────────────────────────────┐                   │
│  │   4 COMPETITIVE MODELS             │                   │
│  │  A: Scalp Conservative (4h)        │                   │
│  │  B: Momentum Burst (2h)            │                   │
│  │  C: News Spike (4h)                │                   │
│  │  D: Dip Scalper (8h) ⭐ 97.3% WR   │                   │
│  │  E: Breakout Micro (6h)            │                   │
│  │  F: Trend Rider (12h)              │                   │
│  └────────────┬───────────────────────┘                   │
│               │                                             │
│               ▼                                             │
│  ┌────────────────────────────────────┐                   │
│  │  Real-Time Monitor (5-min checks)  │                   │
│  │  ├─ Dynamic Close Logic            │                   │
│  │  ├─ P&L tracking                   │                   │
│  │  └─ Data Validation                │                   │
│  └────────────┬───────────────────────┘                   │
│               │                                             │
│               ▼                                             │
│  ┌────────────────────────────────────┐                   │
│  │   SQLite Database                  │                   │
│  │   └─ predictions.db (outcomes)     │                   │
│  └────────────────────────────────────┘                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 🗂️ Estructura de Carpetas

```
crypto_bot/
│
├── bot/                           # CORE - Módulos principales
│   ├── __init__.py
│   ├── crypto_data.py            # Descarga OHLCV de Binance + indicadores técnicos
│   ├── crypto_gate.py            # Gate de 13 factores (GREEN/YELLOW/RED)
│   ├── crypto_models.py          # Lógica de los 6 modelos
│   ├── crypto_news.py            # Análisis de sentimiento de noticias (Google RSS)
│   ├── crypto_scanner.py         # Escaneo de pares
│   ├── predictions.py            # Engine de predicciones + BD SQLite
│   ├── predictions_realtime.py   # Monitor en tiempo real (5-min checks)
│   ├── position_sizing.py        # Cálculo de posición y stop/target
│   ├── sentiment.py              # Análisis de sentimiento avanzado
│   ├── logger.py                 # Logging centralizado
│   ├── top20_pairs.py            # Lista de 20 pares entrenados
│   └── ...otros módulos auxiliares
│
├── model_d_training/             # PIPELINE - Entrenamiento event-driven
│   ├── __init__.py
│   ├── step1_extract_event_features.py     # Extrae features de eventos
│   ├── step2_train_event_models.py         # Entrena 6 modelos
│   ├── step3_walkforward_validation.py     # Validación forward-looking
│   ├── step4_expand_event_windows.py       # Expande ventanas de eventos
│   ├── step5_train_final_models.py         # Entrena modelos finales
│   ├── features.py               # Feature engineering
│   ├── global_events_2026.py     # Eventos económicos macro
│   ├── events_tracker.py         # Tracking de eventos en tiempo real
│   └── ...scripts de análisis/debugging
│
├── state/                        # PERSISTENCIA - Base de datos y modelos
│   ├── crypto_predictions.db     # Tabla de predicciones + outcomes
│   ├── models_*.pkl              # Modelos XGBoost entrenados
│   └── .gitkeep
│
├── logs/                         # EJECUCIÓN - Logs de runs
│   └── .gitkeep
│
├── run_crypto_models.py          # ⭐ PUNTO DE ENTRADA principal
├── bot_crypto.py                 # CLI: análisis manual de pares
│
├── .env                          # ⚙️ Configuración (API keys Binance)
├── requirements.txt              # Dependencias Python
├── README.md                     # Documentación usuario
├── ARCHITECTURE.md               # Este archivo
├── .gitignore                    # Qué excluir de GitHub
│
└── .venv/                        # Virtual environment (NO subir a GitHub)
```

---

## 🔄 Flujo de Datos

### 1️⃣ **Entrenamiento (Offline - una sola vez)**

```
Datos históricos (2024)
        ↓
[model_d_training/]
  ├─ step1: Extrae eventos (39 eventos globales)
  ├─ step2: Genera features de eventos (4.6M klines → 11,563 windows)
  ├─ step3: Validación forward-looking (Walk-forward)
  ├─ step4: Expande ventanas de eventos
  └─ step5: Entrena modelos finales (Model D: 97.3% WR)
        ↓
Modelos guardados: models_D_xgb.pkl
```

### 2️⃣ **Predicción (Daily - cada mañana a las 9:00 AM)**

```
python run_crypto_models.py full
        ↓
┌─────────────────────────────────┐
│ 1. Obtiene OHLCV de Binance     │  ← Binance API
│    (TOP 20 pares entrenados)    │
└──────────────┬──────────────────┘
               ↓
┌─────────────────────────────────┐
│ 2. Calcula indicadores técnicos │  ← crypto_data.py
│    (SMA, RSI, ATR, Volumen)     │
└──────────────┬──────────────────┘
               ↓
┌─────────────────────────────────┐
│ 3. Obtiene sentimiento macro    │  ← alternative.me (FNG)
│    + Dominancia BTC             │  ← CoinGecko
│    + Noticias (Google RSS)      │  ← Google News
└──────────────┬──────────────────┘
               ↓
┌─────────────────────────────────┐
│ 4. Corre Gate de 13 factores    │  ← crypto_gate.py
│    (M1-M3, S1-S4, T1-T3, R1-R2, N1) │
│    Salida: GREEN/YELLOW/RED     │
└──────────────┬──────────────────┘
               ↓
┌─────────────────────────────────┐
│ 5. Corre 6 modelos en paralelo  │  ← crypto_models.py
│    A,B,C,D,E,F                  │
│    Filtra por gate + confianza  │
└──────────────┬──────────────────┘
               ↓
┌─────────────────────────────────┐
│ 6. Calcula position sizing      │  ← position_sizing.py
│    Stop: -2.5%, Target: +3.0%   │
└──────────────┬──────────────────┘
               ↓
┌─────────────────────────────────┐
│ 7. Guarda en BD SQLite          │  ← predictions.py
│    (estado: PENDING)            │
└─────────────────────────────────┘
        ↓
Nuevas predicciones listas para monitoreo
```

### 3️⃣ **Monitoreo Real-Time (Cada 5 minutos - 24/7)**

```
python run_crypto_models.py monitor
        ↓
┌─────────────────────────────────┐
│ Cada 5 minutos:                 │
│ 1. Obtiene predicciones PENDING │
│ 2. Evalúa condiciones dinámicas:│
│    ├─ ¿P&L >= +3%? → WIN        │
│    ├─ ¿Toca stop? → LOSS        │
│    ├─ ¿Toca target? → WIN       │
│    ├─ ¿Momentum invierte? → LOSS│
│    └─ ¿Volatilidad colapsa? →LOSS
│ 3. Cierra si alguna condición   │
│ 4. Actualiza BD con outcome     │
│ 5. Espera 5 minutos             │
│ 6. Repite                       │
└─────────────────────────────────┘
        ↓
Resumen diario: Win rate por modelo
```

---

## 🎯 Datos de Entrenamiento

| Aspecto | Valor |
|---------|-------|
| **Período** | 2024 (1 año) |
| **Timeframe** | 5 minutos |
| **Total klines** | 4.6M |
| **Pares** | TOP 20 (10 stable + 10 volatile) |
| **Eventos** | 39 globales (Trump, Fed, Elon, etc.) |
| **Ventanas generadas** | 11,563 event windows |
| **Modelo B Win Rate** | 97.3% (en backtest) |

### TOP 20 Pares Entrenados
```
STABLE (10):  BTC, ETH, BNB, SOL, XRP, ADA, AVAX, DOT, LINK, MATIC
VOLATILE (10): DOGE, SHIB, NEAR, APT, SUI, INJ, RNDR, TIA, SEI, FET
```

---

## 🧮 13-Factor Gate System

```
MACRO LAYER (Contexto diario):
├─ M1: BTC Trend (SMA20/50 de BTC diario)
├─ M2: Fear & Greed Index (alternative.me, 0-100)
├─ M3: Volatilidad 1h (ATR)
└─ S4: BTC Dominance (% BTC del mercado)

SHORT-TERM LAYER (Timing 1-4h):
├─ S1: Momentum 4h (SMA20 vs SMA50)
├─ S2: Setup técnico 1h (RSI, MA crossovers)
├─ S3: Volumen 1h (vs promedio 20d)
├─ T1: Micro-trend 6h (últimas 6 velas 1h)
├─ T2: Buy/Sell Ratio (volumen comprador)
└─ T3: Señal entrada (pullback a MA20 o breakout)

RISK LAYER:
├─ R1: Risk/Reward ratio (stop/target)
└─ R2: Exposición total (limit predicciones abiertas)

SENTIMENT LAYER (PESO 2x para crypto):
└─ N1: Noticias (keywords + power figures: Trump 3x, Elon 2.5x)
```

**Output:** GREEN (3+ factores), YELLOW (1-2), RED (3+ negativos)

---

## 📊 Base de Datos Schema

### Tabla: `predictions`
```sql
CREATE TABLE predictions (
    id              INTEGER PRIMARY KEY,
    model           TEXT DEFAULT 'A',
    symbol          TEXT NOT NULL,
    predicted_at    TEXT NOT NULL,
    price_at_pred   REAL NOT NULL,
    gate_score      INTEGER,
    decision        TEXT,
    factors_json    TEXT,
    stop_price      REAL,
    target_price    REAL,
    max_hours       REAL DEFAULT 4,
    outcome         TEXT DEFAULT 'PENDING',
    outcome_date    TEXT,
    price_at_outcome REAL,
    pnl_pct         REAL,
    hours_held      REAL,
    error_flags     TEXT
)
```

---

## 🚀 Puntos de Entrada Principales

### `run_crypto_models.py` - CLI principal
```bash
python run_crypto_models.py full         # Genera predicciones nuevas
python run_crypto_models.py monitor      # Monitorea en tiempo real (5-min checks)
python run_crypto_models.py outcomes     # Resuelve predicciones vencidas
python run_crypto_models.py validate     # Valida cobertura de datos
python run_crypto_models.py report       # Genera reporte de performance
python run_crypto_models.py compare      # Compara modelos
```

### `bot_crypto.py` - Análisis manual
```bash
python bot_crypto.py news       # Últimas noticias crypto
python bot_crypto.py gate BTC   # Análisis completo de un par
python bot_crypto.py scan       # Escanea todos los pares
```

---

## 🔐 Configuración Requerida

### `.env` (NO subir a GitHub)
```env
BINANCE_API_KEY=your_key_here
BINANCE_API_SECRET=your_secret_here
BINANCE_MODE=testnet     # testnet o mainnet
CRYPTO_DB_PATH=state/crypto_predictions.db
```

---

## 📈 Modelos Entrenados

| Modelo | Nombre | Timeframe | Estrategia | WR (Backtest) |
|--------|--------|-----------|-----------|---------------|
| **A** | Scalp Conservative | 4h | Scalping prudente | ~85% |
| **B** | Momentum Burst | 2h | Impulsos rápidos | **97.3%** ⭐ |
| **C** | News Spike | 4h | Reacción a noticias | ~80% |
| **D** | Dip Scalper | 8h | Compra del pánico | ~85% |
| **E** | Breakout Micro | 6h | Ruptura técnica | ~82% |
| **F** | Trend Rider | 12h | Montaje de tendencia | ~78% |

---

## 🔄 Ciclo Diario de Operación

```
09:00 AM    ├─ python run_crypto_models.py full
            │  └─ Genera nuevas predicciones
            │
09:05 AM    └─ python run_crypto_models.py monitor
               └─ Inicia monitoreo (corre continuamente cada 5 min)
                  ├─ Check #1 → Sin cambios
                  ├─ Check #2 → Sin cambios
                  ├─ Check #3 → 2 trades cerraron (WIN/LOSS)
                  └─ ... continúa hasta Ctrl+C

08:00 PM    └─ Detener monitor (Ctrl+C)

23:59 PM    └─ (Repetir al día siguiente)
```

---

## ⚠️ Limitaciones Conocidas

1. **Entrenamiento específico por moneda**: Bot entrenado en TOP 20. No generaliza bien a otras monedas.
2. **Forward-looking only**: No usa backtest histórico para predicciones (evita overfitting).
3. **Testnet behavior**: Binance testnet puede tener spreads/liquidez diferentes a mainnet.
4. **News API gratuita**: Google News RSS tiene límites de actualización (~1-5 min de delay).

---

## 🛠️ Stack Técnico

| Componente | Librería/Herramienta |
|-----------|----------------------|
| **API Binance** | requests + urllib (custom, sin librería) |
| **Análisis técnico** | NumPy, Pandas, custom indicators |
| **ML/Modelos** | XGBoost, scikit-learn |
| **Base de datos** | SQLite3 (nativo Python) |
| **Sentimiento** | Google News RSS + custom NLP |
| **Logging** | logging (stdlib) |

---

## 📞 Referencias

- **Documentación de usuario:** [README.md](README.md)
- **Guía de ejecución:** [EJECUTAR_AHORA.txt](EJECUTAR_AHORA.txt)
- **Fuentes de datos:** [FUENTES_DE_DATOS.md](FUENTES_DE_DATOS.md)
- **Training pipeline:** [model_d_training/README.md](model_d_training/README.md)
