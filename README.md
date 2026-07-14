# 🤖 Crypto Trading Bot

[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Datasets on HF](https://img.shields.io/badge/datasets-huggingface-orange)](https://huggingface.co/datasets/jponfiru/crypto-trading-bot-data)
[![scikit-learn](https://img.shields.io/badge/scikit--learn-1.3%2B-F7931E)](https://scikit-learn.org)
[![XGBoost](https://img.shields.io/badge/XGBoost-2.0%2B-006400)](https://xgboost.readthedocs.io)

Bot de trading automatizado para criptomonedas en **Binance (Testnet → Mainnet)** que predice movimientos de precio combinando análisis técnico, sentimiento de mercado y noticias en tiempo real.

**Status:** 🔧 v1.1 — Contabilidad honesta + risk guards | **Last Update:** 2026-06-10

> ⚠️ **Nota de transparencia (v1.1):** el "97.3% win rate" reportado en versiones
> anteriores era un artefacto de contabilidad (trades expirados con +0.01% contaban
> como WIN, breakeven contaba como WIN, y los stops tocados intra-ventana no se
> registraban). La v1.1 corrige la medición (path-check con velas 5m, comisiones
> descontadas, outcome BE) y agrega stops/targets duros, señal bajista, guarda de
> régimen y circuit breaker. Ver [AUDITORIA_2026-06-10.md](AUDITORIA_2026-06-10.md).

> 🎓 **Proyecto Final - Curso de Analítica de Datos (Semana 15).** Este repositorio cumple con los entregables del Milestone Final: presentación ejecutiva, modelo de ML con `scikit-learn` evaluado con métricas apropiadas, repositorio documentado e informe final con conclusiones, recomendaciones y limitaciones. Ver carpetas [`/presentacion`](presentacion/), [`/notebooks`](notebooks/) e [`/informe`](informe/).

## 🎯 Características

✅ **Real-Time Monitoring** - Stops/targets duros + cierre dinámico cada 1-5 min  
✅ **17-Factor Gate System** - Técnico + macro + sentimiento + vetos de riesgo  
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
| **Best Model** | En re-evaluación con contabilidad v1.1 (ver auditoría) |

## 🏗️ Estructura

```
crypto_bot/
├── bot/                          # CORE - Módulos de predicción
│   ├── crypto_data.py           # Descarga OHLCV + indicadores técnicos
│   ├── crypto_gate.py           # Gate de 13 factores
│   ├── crypto_models.py         # 6 modelos (A-F)
│   ├── crypto_news.py           # Análisis de sentimiento
│   ├── predictions.py           # Engine de predicciones
│   ├── position_sizing.py       # Cálculo stop/target
│   ├── top20_pairs.py           # Pares entrenados
│   └── logger.py                # Logging centralizado
│
├── model_d_training/            # PIPELINE - Entrenamiento del ensemble ML
│   ├── download_data.py         # Klines 5m (incremental)
│   ├── download_extended.py     # 1m + macro DXY/SP500/VIX + funding
│   ├── features.py              # Features + labels (trainer grid)
│   ├── features_extended.py     # Features del ensemble (compartidas con vivo)
│   ├── train_grid/xgb/hybrid/full.py  # Trainers
│   ├── compare.py               # Quality gate OOS (elige/deploya)
│   └── results/                 # *_best.json + comparison.json
│
├── scripts/                     # Utilidades (today, reset_bot, wipe, HF datasets)
├── docs/legacy/                 # Documentación histórica (no operativa)
├── state/                       # PERSISTENCIA (SQLite + estados JSON)
├── logs/                        # Ejecución (dinámico, con rotación)
│
├── bot_crypto.py                # ⭐ CLI PRINCIPAL (run, report, gate, ...)
├── smoke_test.py                # Verificación de fixes v1.1
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

### 5. Verificar la instalación (v1.1)

```bash
python smoke_test.py --network
# Debe terminar en 0 FAIL
```

### 6. Ejecutar el Bot

**Modo principal — sesión autónoma (scan + monitor + cierre, todo en uno):**
```bash
python bot_crypto.py run --dry-run          # paper trading, sesión de 17h max
python bot_crypto.py run --hours 6 --dry-run # sesión más corta
# Ctrl+C para detener
```

**Comandos de consulta:**
```bash
python bot_crypto.py report     # expectancy, WR, breakdown por tipo de cierre
python bot_crypto.py compare    # qué modelo va ganando
python bot_crypto.py pending    # trades abiertos
python bot_crypto.py gate BTC   # gate de 16 factores para un par
python bot_crypto.py risk       # estado del risk guard
```

**Flujo alternativo (predicciones manuales + monitor separado):**
```bash
python bot_crypto.py run --dry-run    # una sesion (scan + monitor incluidos)
python bot_crypto.py health           # salud del bot y frescura de datos
```

## 📋 Uso Diario

```
9:00 AM
  └─ python bot_crypto.py run --dry-run
     └─ Sesión autónoma: escanea cada 5 min, monitorea cada 1 min
     └─ Cierra trades automáticamente cuando:
        ├─ Toca stop          → LOSS (STOP_HIT_HARD)
        ├─ Toca target        → WIN  (TARGET_HIT)
        ├─ Señal bajista ≥4/7 → asegura ganancia o corta pérdida (BEAR_SIGNAL_*)
        ├─ Noticia bearish    → EXIT defensivo (R6)
        └─ Trade muerto       → EXIT por tiempo/momentum (R1-R8)

Al final del día
  └─ python bot_crypto.py report
     └─ Métrica clave: EXPECTANCY neta de fees (no el win rate)
```

Ver [GUIA_DIARIA.md](GUIA_DIARIA.md) para el flujo completo.

## 🆕 Novedades v1.1 (2026-06-10)

- **Contabilidad honesta:** path-check con velas 5m (un stop tocado cuenta aunque el precio rebote), comisiones descontadas (±0.25% = outcome `BE`), fin del "expirado +0.01% = WIN".
- **Stops/targets duros:** `trade_monitor` ahora ejecuta el stop y el target del plan con prioridad sobre las reglas R1-R8 (antes eran decorativos).
- **Fix de caché congelado:** los monitores limpian el caché de precios en cada ciclo (antes operaban sobre una foto del primer ciclo).
- **Señal bajista (`bot/short_signal.py`):** score 0-7 con los mismos factores en espejo; veta entradas long y protege trades abiertos.
- **Guarda de régimen:** con BTC bajista (M1 RED) solo opera el modelo D (Dip Scalper).
- **Circuit breaker (factor X2):** -5% acumulado en 24h o 4 LOSS seguidos → pausa entradas 12h.
- **Guard ML:** los `.pkl` entrenados con etiquetas pre-fix se ignoran automáticamente hasta reentrenar.
- **Análisis direccional:** `python -m model_d_training.train_directional` entrena LONG y SHORT con walk-forward para medir si los factores predicen bajadas.
- Detalle completo: [AUDITORIA_2026-06-10.md](AUDITORIA_2026-06-10.md)

## 🎯 Los 6 Modelos

| Modelo | Nombre | Max Hours | Estrategia |
|--------|--------|-----------|-----------|
| **A** | Scalp Conservative | 4h | Scalping cauteloso |
| **B** | Momentum Burst | 2h | Impulsos rápidos |
| **C** | News Spike | 4h | Reacción a noticias |
| **D** | Dip Scalper | 8h | Compra del pánico |
| **E** | Breakout Micro | 6h | Ruptura técnica |
| **F** | Trend Rider | 12h | Montaje de tendencia |

*Los win rates históricos (~78-97%) se midieron con la contabilidad pre-v1.1,
hoy sabida optimista, y están en re-evaluación. La métrica de referencia desde
v1.1 es la **expectancy neta de comisiones** (`python bot_crypto.py report`).

## 🔐 Gate de 17 Factores

El bot toma decisiones usando un sistema de semáforos:

```
MACRO (Contexto diario):
  ├─ M1: BTC Trend        (SMA20/50 de Bitcoin)
  ├─ M2: Fear & Greed     (Índice 0-100)
  ├─ M3: Volatilidad 1h   (ATR)
  ├─ M4: Eventos macro    (FOMC, CPI, NFP — veto duro)
  └─ S4: BTC Dominance    (% del mercado)

SHORT-TERM (Timing 1-4h):
  ├─ S1: Momentum 4h      (relativo a BTC)
  ├─ S2: Setup técnico    (RSI, MA crossovers)
  ├─ S3: Volumen 1h       (vs promedio 20h)
  ├─ T1: Micro-trend      (últimas 6 velas)
  ├─ T2: Buy/Sell Ratio   (volumen comprador)
  └─ T3: Señal entrada    (pullback o reversal)

RIESGO:
  ├─ R1: Risk/Reward      (ratio stop/target)
  ├─ R2: Exposición       (máximo de trades abiertos)
  └─ R3: Sesión 12h       (tiempo restante — veto duro)

SENTIMIENTO (2x peso para crypto):
  └─ N1: Noticias         (keywords + power figures)

VETOS (v1.0/v1.1):
  ├─ X1: Flash crash/pump (blackout tras extremos — veto duro)
  └─ X2: Circuit breaker  (racha de pérdidas — veto duro, v1.1)
```

**Decisión:** EXECUTE_FULL (12+ verdes) / EXECUTE_HALF (10+) / WATCHLIST (6+) / ABORT (3+ rojos o cualquier veto duro)

Además del gate, en v1.1 toda entrada long pasa dos guardas: **régimen** (BTC bajista → solo modelo D) y **señal bajista del par** (score ≥ 4/7 → no entrar).

## 📊 Pares Entrenados (TOP 20)

**STABLE (10):** BTC, ETH, BNB, SOL, XRP, ADA, AVAX, DOT, LINK, MATIC  
**VOLATILE (10):** DOGE, SHIB, NEAR, APT, SUI, INJ, RNDR, TIA, SEI, FET

⚠️ **IMPORTANTE:** El bot solo funciona bien con estos 20 pares. Expandir a más pares requiere reentrenamiento. Ver [MISMATCH_TRAINING_VS_PREDICCION.md](MISMATCH_TRAINING_VS_PREDICCION.md).

## 🔄 Real-Time Monitoring (v1.1)

El runner monitorea cada 1 min (modo `run`) o cada 5 min (`monitor`), con niveles duros primero y reglas después:

```python
# NIVELES DUROS (prioridad absoluta):
#   precio <= stop   → LOSS (STOP_HIT_HARD)
#   precio >= target → WIN  (TARGET_HIT)
# SEÑAL BAJISTA (score >= 4/7 con factores en espejo):
#   ganando → WIN  (BEAR_SIGNAL_LOCK, asegura antes de la caída)
#   perdiendo → LOSS (BEAR_SIGNAL_CUT, no espera el stop completo)
# REGLAS DEFENSIVAS: noticias bearish (R6), blackout macro (R7),
#   timeout (R8), pérdida profunda (R1), momentum sostenido abajo (R2-R5)
# Resolución diferida: path-check con velas 5m reconstruye lo que pasó
#   mientras el monitor no corría (stops tocados no se pierden)
```

## 📚 Documentación

| Doc | Propósito |
|-----|-----------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Diagrama técnico + flujo de datos |
| [CLAUDE.md](CLAUDE.md) | Guía para desarrolladores |
| [FUENTES_DE_DATOS.md](FUENTES_DE_DATOS.md) | De dónde vienen los datos |
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

## 📈 Métricas Objetivo (Después de 2-3 semanas, contabilidad v1.1)

- **Expectancy neta de fees: > 0** (la métrica que manda)
- Profit factor: > 1.3
- Win Rate global: > 50% (con avg win ≥ avg loss)
- Max drawdown: < 15%
- Trades cerrados: > 30 (mínimo para concluir algo)

## 🔧 Troubleshooting

**Error: "unable to open database file"**
- Cierra editores que tengan el .db abierto
- Ejecuta desde PowerShell, no desde Python CLI

**Error: "BinanceAPI error 401"**
- Verifica BINANCE_API_KEY y BINANCE_API_SECRET en .env

**Error: "0 predicciones generadas"**
- Corre `python bot_crypto.py health` para verificar frescura de datos
- Revisa que el mercado no esté totalmente bajista

## 📞 Contacto & Soporte

- **Issues/PRs:** GitHub issues
- **Desarrollo:** Ver [CLAUDE.md](CLAUDE.md)
- **Debugging:** Ver sección Troubleshooting arriba

## 📄 Licencia

Este proyecto es de código abierto. Úsalo libremente para trading/investigación.

**⚠️ Disclaimer:** Este bot se proporciona "tal cual". No garantiza ganancias. Usa con precaución, especialmente en mainnet. Comienza en testnet. El trading de criptos tiene riesgo de pérdida total de capital.

---

**Última actualización:** 2026-06-10  
**Versión:** 1.1 — Contabilidad honesta + risk guards ([AUDITORIA_2026-06-10.md](AUDITORIA_2026-06-10.md))  
**Autor:** Juan (firu)
