# 🤖 Crypto Trading Bot

[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Datasets on HF](https://img.shields.io/badge/datasets-huggingface-orange)](https://huggingface.co/datasets/jponfiru/crypto-trading-bot-data)
[![scikit-learn](https://img.shields.io/badge/scikit--learn-1.3%2B-F7931E)](https://scikit-learn.org)
[![XGBoost](https://img.shields.io/badge/XGBoost-2.0%2B-006400)](https://xgboost.readthedocs.io)

Bot de trading automatizado para criptomonedas en **Binance (Testnet → Mainnet)** que predice movimientos de precio combinando análisis técnico, sentimiento de mercado y noticias en tiempo real.

**Status:** ✅ Production Ready | **Last Update:** 2026-05-21 | **Model B Win Rate:** 97.3%

> 🎓 **Proyecto Final - Curso de Analítica de Datos (Semana 15).** Este repositorio cumple con los entregables del Milestone Final: presentación ejecutiva, modelo de ML con `scikit-learn` evaluado con métricas apropiadas, repositorio documentado e informe final con conclusiones, recomendaciones y limitaciones. Ver carpetas [`/presentacion`](presentacion/), [`/notebooks`](notebooks/) e [`/informe`](informe/).

## 🎯 Características

✅ **Real-Time Monitoring** - Chequea cada 5 minutos si cerrar trades dinámicamente  
✅ **13-Factor Gate System** - Análisis técnico + sentimiento macro integrado  
✅ **6 Competitive Models** - Identifica automáticamente cuál rinde mejor  
✅ **Event-Driven Training** - Entrenado con 4.6M klines + 39 eventos globales  
✅ **Paper Trading First** - Testnet de Binance antes de mainnet  
✅ **Transparent & Auditable** - Código abierto, sin ML blackboxes  

## 📊 Datos Entrenamiento

| Métrica | Valor |
|---------|-------|
| **Período** | 2024 (1 año) |
| **Timeframe** | 5 minutos |
| **Total klines** | 4.6 millones |
| **Pares** | TOP 20 (ver `bot/top20_pairs.py`) |
| **Eventos** | 39 globales (Trump, Fed, Elon, regulaciones) |
| **Ventanas** | 11,563 event windows |
| **Best Model** | Model B: **97.3% win rate** |

## 🏗️ Estructura

```
crypto_bot/
├── bot/                          # CORE - Módulos de predicción
│   ├── crypto_data.py           # Descarga OHLCV + indicadores técnicos
│   ├── crypto_gate.py           # Gate de 13 factores
│   ├── crypto_models.py         # 6 modelos (A-F)
│   ├── crypto_news.py           # Análisis de sentimiento
│   ├── predictions.py           # Engine de predicciones
│   ├── predictions_realtime.py  # Monitor real-time (5-min)
│   ├── position_sizing.py       # Cálculo stop/target
│   ├── top20_pairs.py           # Pares entrenados
│   └── logger.py                # Logging centralizado
│
├── model_d_training/            # PIPELINE - Entrenamiento event-driven
│   ├── step1_extract_event_features.py
│   ├── step2_train_event_models.py
│   ├── step3_walkforward_validation.py
│   ├── step4_expand_event_windows.py
│   ├── step5_train_final_models.py
│   └── (+ scripts de análisis)
│
├── state/                       # PERSISTENCIA
│   └── crypto_predictions.db    # SQLite: predicciones + outcomes
│
├── logs/                        # Ejecución (dinámico)
│
├── run_crypto_models.py         # ⭐ CLI PRINCIPAL
├── bot_crypto.py                # Análisis manual
├── binance_client.py            # Cliente Binance
├── .env                         # API keys (NO subir)
├── requirements.txt             # Dependencias
├── ARCHITECTURE.md              # Diagrama técnico
├── CLAUDE.md                    # Guía para desarrolladores
└── README.md                    # Este archivo
```

## 📦 Datasets en Hugging Face

Los datasets pesados (~6.4 GB en total) **no se incluyen en este repo de GitHub** porque exceden los límites del plan gratuito. Se alojan en Hugging Face Datasets:

🔗 **https://huggingface.co/datasets/jponfiru/crypto-trading-bot-data**

| Archivo | Tamaño | Contenido |
|---|---|---|
| `data_extended.db` | 3.5 GB | 4.6M klines OHLCV de los TOP 20 pares (5-min, 2024-2026) |
| `data_2026.db` | 901 MB | Klines 2026 separados |
| `features_extended.csv` | 2.0 GB | Features de eventos ya extraídos (11,563 ventanas) |
| `features_d.csv` | 43 MB | Subset compacto para entrenar el Modelo D |

Descarga con un comando (ver paso 2 del Quick Start).

## 🚀 Quick Start (Windows)

### 0. Clonar el repo

```bash
git clone https://github.com/juanortizpa/crypto_bot.git
cd crypto_bot
```

### 1. Crear Virtual Environment + Instalar Dependencias

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # Windows PowerShell
pip install -r requirements.txt
```

### 2. Descargar datasets desde Hugging Face

```bash
python scripts/download_datasets_from_hf.py
```

Esto descarga los ~6.4 GB a `model_d_training/state/`. Es el único paso largo (depende de tu internet, típicamente 5-15 min).

### 3. Configurar API Keys Binance (Testnet)

```bash
# Abre .env y agrega:
BINANCE_API_KEY=your_testnet_key
BINANCE_API_SECRET=your_testnet_secret
BINANCE_MODE=testnet
CRYPTO_DB_PATH=state/crypto_predictions.db
```

**Cómo obtener keys testnet:** https://testnet.binance.vision/ → Sign in with GitHub → Generate Keys

### 4. (Opcional) Abrir el notebook de ML

```bash
jupyter notebook notebooks/proyecto_final_ml.ipynb
```

El notebook reproduce el pipeline de ML del proyecto final (clasificación + regresión con `scikit-learn`, métricas, overfitting check).

### 5. Ejecutar el Bot

**Generar predicciones nuevas (1x al día):**
```bash
python run_crypto_models.py full
```

**Monitorear en tiempo real (corre continuamente cada 5 min):**
```bash
python run_crypto_models.py monitor
# Presiona Ctrl+C para detener
```

**Validar datos:**
```bash
python run_crypto_models.py validate
```

**Ver resumen de rendimiento:**
```bash
python run_crypto_models.py report
```

## 📋 Uso Diario

```
9:00 AM
  └─ python run_crypto_models.py full
     └─ Genera nuevas predicciones

9:05 AM
  └─ python run_crypto_models.py monitor
     └─ Corre continuamente, chequea cada 5 min
     └─ Cierra trades automáticamente cuando:
        ├─ Ganancia >= +3% → WIN (early close)
        ├─ Pérdida >= -2.5% → LOSS (stop hit)
        ├─ Momentum invierte → LOSS (gate rojo)
        └─ Volatilidad colapsa → LOSS

8:00 PM
  └─ Ctrl+C para detener monitor
```

## 🎯 Los 6 Modelos

| Modelo | Nombre | Max Hours | Estrategia | Win Rate* |
|--------|--------|-----------|-----------|-----------|
| **A** | Scalp Conservative | 4h | Scalping cauteloso | ~85% |
| **B** | Momentum Burst | 2h | Impulsos rápidos | **97.3%** ⭐ |
| **C** | News Spike | 4h | Reacción a noticias | ~80% |
| **D** | Dip Scalper | 8h | Compra del pánico | ~85% |
| **E** | Breakout Micro | 6h | Ruptura técnica | ~82% |
| **F** | Trend Rider | 12h | Montaje de tendencia | ~78% |

*En backtest con 4.6M klines 2024

## 🔐 Gate de 13 Factores

El bot toma decisiones usando un sistema de semáforos que evalúa 13 factores:

```
MACRO (Contexto diario):
  ├─ M1: BTC Trend        (SMA20/50 de Bitcoin)
  ├─ M2: Fear & Greed     (Índice 0-100)
  ├─ M3: Volatilidad 1h   (ATR)
  └─ S4: BTC Dominance    (% del mercado)

SHORT-TERM (Timing 1-4h):
  ├─ S1: Momentum 4h      (SMA20 vs SMA50)
  ├─ S2: Setup técnico    (RSI, MA crossovers)
  ├─ S3: Volumen 1h       (vs promedio 20d)
  ├─ T1: Micro-trend      (últimas 6 velas)
  ├─ T2: Buy/Sell Ratio   (volumen comprador)
  └─ T3: Señal entrada    (pullback o breakout)

RIESGO:
  ├─ R1: Risk/Reward      (ratio stop/target)
  └─ R2: Exposición       (máximo de trades abiertos)

SENTIMIENTO (2x peso para crypto):
  └─ N1: Noticias         (keywords + power figures)
```

**Output:** GREEN (3+ factores), YELLOW (1-2), RED (3+ negativos)

## 📊 Pares Entrenados (TOP 20)

**STABLE (10):** BTC, ETH, BNB, SOL, XRP, ADA, AVAX, DOT, LINK, MATIC  
**VOLATILE (10):** DOGE, SHIB, NEAR, APT, SUI, INJ, RNDR, TIA, SEI, FET

⚠️ **IMPORTANTE:** El bot solo funciona bien con estos 20 pares. Expandir a más pares requiere reentrenamiento. Ver [MISMATCH_TRAINING_VS_PREDICCION.md](MISMATCH_TRAINING_VS_PREDICCION.md).

## 🔄 Real-Time Monitoring

El monitor corre cada 5 minutos evaluando condiciones dinámicas de cierre:

```python
# Si P&L >= +3% → Cierra WIN (no espera al target)
# Si toca stop (-2.5%) → Cierra LOSS automático
# Si toca target (+3%) → Cierra WIN automático
# Si momentum invierte (más RED que GREEN) → Cierra LOSS
# Si volatilidad colapsa → Cierra LOSS
```

Esto reemplaza la lógica antigua de cierre por tiempo fijo, permitiendo ganancias más rápidas en mercados volátiles.

## 📚 Documentación

| Doc | Propósito |
|-----|-----------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Diagrama técnico + flujo de datos |
| [CLAUDE.md](CLAUDE.md) | Guía para desarrolladores |
| [FUENTES_DE_DATOS.md](FUENTES_DE_DATOS.md) | De dónde vienen los datos |
| [EJECUTAR_AHORA.txt](EJECUTAR_AHORA.txt) | Instrucciones paso a paso |
| [MISMATCH_TRAINING_VS_PREDICCION.md](MISMATCH_TRAINING_VS_PREDICCION.md) | Por qué no expandir pares |

## ⚠️ Limitaciones Conocidas

1. **TOP 20 only** - Entrenado con estos pares, no generaliza a otros
2. **Forward-looking** - No usa backtest histórico (evita overfitting)
3. **Testnet first** - Spreads/liquidez pueden diferir en mainnet
4. **Google News delay** - RSS tiene 1-5 min de retraso
5. **Crypto 24/7** - Puede haber trades abiertos en cualquier momento

## 🚀 Roadmap

- [ ] Per-tier model training (DeFi, Memecoins, L2)
- [ ] On-chain signals (ballenas, exchange flows)
- [ ] Email/SMS alerts para wins/losses
- [ ] Web dashboard
- [ ] Mainnet deployment

## 📈 Métricas Objetivo (Después de 2-3 semanas)

- Win Rate Global: >75%
- Win Rate Modelo B: >85%
- Avg P&L Ganadores: >2.5%
- Avg P&L Perdedores: >-2.5%
- Sharpe Ratio: >1.5

## 🔧 Troubleshooting

**Error: "unable to open database file"**
- Cierra editores que tengan el .db abierto
- Ejecuta desde PowerShell, no desde Python CLI

**Error: "BinanceAPI error 401"**
- Verifica BINANCE_API_KEY y BINANCE_API_SECRET en .env

**Error: "0 predicciones generadas"**
- Corre `python run_crypto_models.py validate` para verificar datos
- Revisa que el mercado no esté totalmente bajista

## 📞 Contacto & Soporte

- **Issues/PRs:** GitHub issues
- **Desarrollo:** Ver [CLAUDE.md](CLAUDE.md)
- **Debugging:** Ver sección Troubleshooting arriba

## 📄 Licencia

Este proyecto es de código abierto. Úsalo libremente para trading/investigación.

**⚠️ Disclaimer:** Este bot se proporciona "tal cual". No garantiza ganancias. Usa con precaución, especialmente en mainnet. Comienza en testnet. El trading de criptos tiene riesgo de pérdida total de capital.

---

**Última actualización:** 2026-05-15  
**Versión:** 1.0 (Production Ready)  
**Autor:** Juan (firu)

| Modelo | Nombre | Entrada | Stop | Target | Uso |
|--------|--------|---------|------|--------|-----|
| **A** | Scalp Conservador | Gate ≥7, 0 RED | -1.5% | +2.5% | Trades cortos, muy seguros |
| **B** | Momentum Burst | Gate ≥5, 0 RED, S1 verde | -2% | +4% | Seguir momentum |
| **C** | News Spike | Gate ≥4, max 1 RED, N1 verde | -2% | +3% | Reaccionar a noticias rápido |
| **D** | Dip Scalper | Gate ≥3, max 2 RED, F&G<45 | -3% | +6% | Comprar pánico |
| **E** | Breakout Micro | Gate ≥5, 0 RED, T3 verde | -2.5% | +5% | Breakouts técnicos |
| **F** | Trend Rider | Gate ≥6, 0 RED, M1 verde | -2% | +4% | Seguir tendencia BTC |

### Meta Model
Promedia señales de A-F ponderadas por win rate histórico.

## ⚙️ Los 13 Factores del Gate

```
MACRO (M):
  M1 - Tendencia BTC dominance
  M2 - Fear & Greed Index
  M3 - Volatilidad 24h (ATR)

SETUP (S):
  S1 - Momentum vs BTC
  S2 - Setup técnico (MA20, MA50, RSI)
  S3 - Volumen 24h vs prom 7d
  S4 - Dominancia BTC

TREND (T):
  T1 - Tendencia 7 días
  T2 - Buy/Sell ratio (Binance)
  T3 - Señal entrada (Pullback o Breakout)

RIESGO (R):
  R1 - Risk/Reward ratio
  R2 - Exposición portafolio

NOTICIAS (N):  ← PESO 2X para crypto
  N1 - Trump/Elon/SEC/ETF/Hacks
  N2 - On-chain signals (ballenas, NUPL)
```

**Salida del Gate:**
- 🟢 GREEN = +1 punto
- 🟡 YELLOW = 0 puntos  
- 🔴 RED = -1 punto

Score ≥ threshold (según modelo) → ENTRA

## 📊 Base de Datos

```sqlite
-- state/crypto_predictions.db

CREATE TABLE predictions (
  id INTEGER PRIMARY KEY,
  date TEXT,
  pair TEXT,
  model TEXT,        -- A, B, C, D, E, F, META
  signal TEXT,       -- BUY, SELL, HOLD
  entry_price REAL,
  stop_pct REAL,
  target_pct REAL,
  outcome TEXT,      -- WIN, LOSS, PENDING
  pnl_pct REAL
);
```

Cada mañana:
1. `run_crypto_models.py` escanea 200 pares
2. Corre 6 modelos en paralelo
3. **Guarda predicciones sin comprar** (AUTO_EXECUTE=False)
4. Cada tarde: resuelve predicciones (cryptos opera 24/7)
5. Calcula win rate por modelo

## 🛡️ Safety Guards (Testnet/Live)

```python
MAX_CAPITAL_PER_TRADE = 50%      # Riesgo por trade
DAILY_LOSS_KILL = 15%            # Stop loss diario
TOTAL_DD_KILL = 25%              # Drawdown máximo
MAX_CONCURRENT = 1               # 1 trade abierto
COOLDOWN = 60min                 # Espacio mínimo entre trades
BINANCE_FEE = 0.1%               # Comisión
```

**Auto-execute nunca activa si:**
- Winner OOS tiene PnL ≤ 0
- Profit factor < 1
- Validación fallida

## 🔄 Workflow Recomendado

```
SEMANA 1-2: ANÁLISIS
├─ Escaneo diario sin comprar
├─ Observar qué modelo gana
├─ Ajustar thresholds si es necesario
└─ Documentar patrón ganador

SEMANA 3: TESTNET LIVE
├─ AUTO_EXECUTE=True en testnet
├─ Capital de prueba: $10-$100
├─ Validar mecanismo de compra/venta
├─ Monitorear trades reales
└─ Evaluar slippage + comisiones

SEMANA 4: PRODUCCIÓN
├─ AUTO_EXECUTE=True (REAL MONEY)
├─ Capital inicial: $100-$500
├─ Monitoreo activo diario
├─ Ajustar parámetros según results
└─ Escalar cuando win rate > 55%
```

## 📝 Archivos Importantes

- **binance_client.py**: Cliente Binance con testnet/live swap. No editar ligeramente.
- **.env**: API keys. ⚠️ NUNCA commitear a git.
- **state/crypto_predictions.db**: Historial de predicciones. Backup regularmente.
- **model_d_training/**: Pipeline de entrenamiento. Usar cuando quieras reentrenar modelos.

## 🐛 Troubleshooting

### "No pairs found"
- Verificar conexión internet
- Verificar API keys en .env
- Verificar BINANCE_MODE=testnet

### "Gate score too low"
- Mercado no favorable
- Ajustar thresholds en crypto_models.py (línea MODELS dict)
- Esperar mejor momento

### "Connection refused"
- API rate limit: esperar 1min
- Binance mantenimiento: esperar
- Proxy bloqueando: usar VPN

## 📚 Documentación

- Binance API: https://binance-docs.github.io/apidocs/
- Fear & Greed Index: https://alternative.me/fng/
- Glassnode (on-chain): https://glassnode.com/ (free tier)

## ✅ Checklist Antes de Producción

- [ ] Binance testnet API keys configuradas
- [ ] requirements.txt instalado
- [ ] run_crypto_models.py ejecuta sin errores
- [ ] Predicciones se guardan en DB
- [ ] Win rate > 50% en backtests
- [ ] Safety guards testados
- [ ] ❌ AUTO_EXECUTE todavía en False
- [ ] Presupuesto de riesgo definido ($10-$500)
- [ ] Logs monitoreados diariamente
- [ ] Plan de escalado documentado

---

**Status**: 🟢 Listo para entrenar y operar  
**Última actualización**: 2026-05-13  
**Modelos**: A-F + Meta (7 competidores)  
**Pares monitoreados**: 200  
