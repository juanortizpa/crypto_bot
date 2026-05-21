# CLAUDE.md - Guía de Desarrollo

Instrucciones y contexto para Claude (o cualquier IA/desarrollador) trabajando en este proyecto.

## 🎯 Objetivo del Proyecto

Construir un bot de trading automatizado de criptomonedas que:
1. Predice movimientos de precio usando análisis técnico + sentimiento
2. Opera en Binance (testnet primero, mainnet después)
3. Monitorea trades en tiempo real con cierre dinámico
4. Compara performance de 6 modelos competitivos
5. Identifica qué modelo tiene mejor win rate

## 📋 Stack Técnico

- **Lenguaje:** Python 3.9+
- **Datos:** Binance API (gratis, sin límites)
- **ML:** XGBoost + scikit-learn
- **DB:** SQLite3
- **Sentiment:** Google News RSS + custom NLP

## 🗂️ Estructura Clave

```
bot/                        → Módulos principales (predicción, monitoreo)
model_d_training/          → Pipeline de entrenamiento event-driven
state/                     → Base de datos SQLite + modelos entrenados
run_crypto_models.py       → Punto de entrada (CLI principal)
.env                       → API keys Binance (NO subir a GitHub)
```

Ver [ARCHITECTURE.md](ARCHITECTURE.md) para diagrama completo.

## 🚀 Cómo Empezar

### 1. Setup inicial
```bash
# Clonar/descargar proyecto
cd crypto_bot

# Crear virtual environment
python -m venv .venv

# Activar (Windows)
.\.venv\Scripts\Activate.ps1

# Instalar dependencias
pip install -r requirements.txt --break-system-packages
```

### 2. Configurar Binance API
```bash
# Crear archivo .env con API keys
# NO SUBIR .env A GITHUB
echo BINANCE_API_KEY=your_key > .env
echo BINANCE_API_SECRET=your_secret >> .env
echo BINANCE_MODE=testnet >> .env
```

### 3. Ejecutar bot
```bash
# Generar nuevas predicciones
python run_crypto_models.py full

# Monitorear en tiempo real (corre continuamente)
python run_crypto_models.py monitor

# Validar datos
python run_crypto_models.py validate
```

## 📊 Datos de Entrenamiento

El bot fue entrenado con:
- **Período:** 2024 (1 año)
- **Timeframe:** 5 minutos
- **Klines:** 4.6M (4.6 millones de velas)
- **Pares:** TOP 20 (ver [bot/top20_pairs.py](bot/top20_pairs.py))
- **Eventos:** 39 eventos globales en 2026

### TOP 20 Pares (NUNCA EXPANDIR SIN REENTRENAMIENTO)
```
STABLE (10):   BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT, ADAUSDT, AVAXUSDT, DOTUSDT, LINKUSDT, MATICUSDT
VOLATILE (10): DOGEUSDT, SHIBUSDT, NEARUSDT, APTUSDT, SUIUSDT, INJUSDT, RNDRUSDT, TIAUSDT, SEIUSDT, FETUSDT
```

**⚠️ CRÍTICO:** Si cambias CRYPTO_PAIRS a más de 20 pares, los modelos pierden precisión (extrapolación sin entrenamiento).

## 🔑 Conceptos Críticos

### 1. Gate de 13 Factores
Sistema de semáforos que evalúa:
- **M1-M3:** Contexto macro (BTC trend, FNG, volatilidad)
- **S1-S4:** Corto plazo (momentum, volumen, dominancia)
- **T1-T3:** Timing (micro-trend, buy/sell ratio, señal entrada)
- **R1-R2:** Riesgo (R:R ratio, exposición total)
- **N1:** Noticias (peso 2x para crypto)

Salida: GREEN (3+), YELLOW (1-2), RED (3+ factores negativos)

### 2. 6 Modelos Competitivos
Todos entrenados en los mismos datos (4.6M klines):
- **A** (Scalp Conservative, 4h, ~85% WR)
- **B** (Momentum Burst, 2h, **97.3% WR**) ⭐ Mejor en backtest
- **C** (News Spike, 4h, ~80%)
- **D** (Dip Scalper, 8h, ~85%)
- **E** (Breakout Micro, 6h, ~82%)
- **F** (Trend Rider, 12h, ~78%)

Sistema elige modelo según condiciones del mercado.

### 3. Monitoreo Real-Time
Corre cada 5 minutos, evalúa si cerrar trades dinámicamente:
- ✅ WIN si P&L ≥ +3% (early close)
- ❌ LOSS si toca stop (-2.5%)
- ✅ WIN si toca target
- ❌ LOSS si momentum invierte (más RED que GREEN)
- ❌ LOSS si volatilidad colapsa

NO cierra por tiempo fijo. Solo por condiciones.

## 🎨 Convenciones de Código

### Imports
```python
import os, sys, json
from datetime import datetime, timedelta
from bot.crypto_data import get_price, get_bars
from bot.logger import log
```

### Logging
```python
from bot.logger import log
log(f"Información importante aquí")  # Usa central logger, NO print()
```

### Estructura de funciones
```python
def evaluate_condition(symbol):
    """
    Evalúa una condición.
    
    Args:
        symbol: Par crypto (ej: BTCUSDT)
        
    Returns:
        (bool, str, str): (debe_cerrar, outcome, reason)
    """
    price = get_price(symbol)
    if not price:
        return False, "PENDING", "NO_PRICE"
    return True, "WIN", "REASON_AQUI"
```

## 🔄 Workflow de Desarrollo

### 1. Entender el Problema
- Lee [ARCHITECTURE.md](ARCHITECTURE.md)
- Revisa [FUENTES_DE_DATOS.md](FUENTES_DE_DATOS.md)
- Entiende el gate y los modelos

### 2. Hacer Cambios
- Edita solo archivos en `bot/` o `model_d_training/`
- NO edites `run_crypto_models.py` a menos que sea necesario
- Sigue convenciones de código arriba

### 3. Validar
```bash
# Valida que datos están bien
python run_crypto_models.py validate

# Corre una predicción de prueba
python run_crypto_models.py full

# Monitorea un ciclo (Ctrl+C después de 5-10 min)
python run_crypto_models.py monitor
```

## ⚠️ Errores Comunes

### "ImportError: cannot import name 'X' from 'bot.y'"
**Solución:** Verifica que la función está exportada en el módulo. Revisa los imports en el archivo.

### "unable to open database file"
**Solución:** 
1. Cierra cualquier editor que tenga el archivo `.db` abierto
2. Asegúrate de que ejecutas desde PowerShell/CMD, no desde Python CLI
3. Verifica que hay espacio en disco (requiere ~100MB para transacciones SQLite)

### "BinanceAPI error: 401"
**Solución:** Revisa que `BINANCE_API_KEY` y `BINANCE_API_SECRET` están correctos en `.env`

### "0 predicciones generadas"
**Solución:** 
- Verifica que el mercado no está totalmente bajista (gate muy rojo)
- Corre `python run_crypto_models.py validate` para asegurar que baja datos
- Revisa logs en `logs/` si existen

## 📈 Métricas para Monitorear

Después de 1-2 semanas de operación, verifica:

```
Métrica              | Target   | Cómo Verificar
─────────────────────┼──────────┼─────────────────────────
Win Rate Global      | >75%     | python run_crypto_models.py report
Win Rate Modelo B    | >85%     | SELECT * FROM predictions WHERE model='B'
Avg P&L Ganadores    | >2.5%    | BD: pnl_pct WHERE outcome='WIN'
Avg P&L Perdedores   | >-2.5%   | BD: pnl_pct WHERE outcome='LOSS'
Trades Cerrados      | >20      | COUNT(*) WHERE outcome != 'PENDING'
Exposición Total     | <5 pairs | SELECT COUNT(*) WHERE outcome='PENDING'
```

## 🔧 Tareas Frecuentes

### Agregar Nuevo Par (NO RECOMENDADO)
⚠️ Requiere reentrenamiento completo de modelos. Ver [MISMATCH_TRAINING_VS_PREDICCION.md](MISMATCH_TRAINING_VS_PREDICCION.md).

### Cambiar Stop/Target
Edita valores en `bot/predictions.py`:
```python
STOP_PCT = -0.025  # -2.5%
TARGET_PCT = 0.03  # +3.0%
```

### Ajustar Monitor Interval
En `bot/predictions_realtime.py`:
```python
MONITOR_INTERVAL = 300  # segundos (5 minutos)
```

### Entrenar Nuevo Modelo
Ver [model_d_training/README.md](model_d_training/README.md) para pipeline completo.

## 📞 Debugging

### Ver predicciones pendientes
```sql
sqlite3 state/crypto_predictions.db
SELECT model, symbol, predicted_at, price_at_pred, gate_score, decision 
FROM predictions WHERE outcome='PENDING' ORDER BY predicted_at DESC;
```

### Ver últimas resueltas
```sql
SELECT model, symbol, outcome, pnl_pct, hours_held 
FROM predictions WHERE outcome IN ('WIN','LOSS') 
ORDER BY outcome_date DESC LIMIT 10;
```

### Win Rate por modelo
```sql
SELECT model, 
       COUNT(*) as total,
       SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) as wins,
       ROUND(100.0*SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END)/COUNT(*), 1) as wr_pct
FROM predictions WHERE outcome IN ('WIN','LOSS')
GROUP BY model ORDER BY wr_pct DESC;
```

## 🚀 Deployment a Mainnet

**SOLO DESPUÉS DE 2-3 SEMANAS DE VALIDACIÓN EN TESTNET**

1. Cambiar `BINANCE_MODE=mainnet` en `.env`
2. Cambiar `AUTO_EXECUTE=False` a `True` en `run_crypto_models.py` (inicialmente)
3. Empezar con pequeño size de posición (ej: 1% del capital)
4. Monitorear continuamente las primeras 2 semanas
5. Aumentar posición gradualmente si win rate se mantiene

## 📚 Referencias Internas

- [README.md](README.md) - Documentación para usuarios
- [ARCHITECTURE.md](ARCHITECTURE.md) - Diagrama técnico completo
- [FUENTES_DE_DATOS.md](FUENTES_DE_DATOS.md) - De dónde vienen los datos
- [MISMATCH_TRAINING_VS_PREDICCION.md](MISMATCH_TRAINING_VS_PREDICCION.md) - Por qué no expandir pares
- [model_d_training/README.md](model_d_training/README.md) - Cómo entrenar modelos
- [EJECUTAR_AHORA.txt](EJECUTAR_AHORA.txt) - Instrucciones paso a paso Windows

## 💡 Mejoras Futuras (Roadmap)

- [ ] Per-tier model training (DeFi, Memecoins, L2)
- [ ] On-chain signals (Glassnode, CryptoQuant)
- [ ] Enhanced sentiment (Twitter API paid)
- [ ] Liquidity checks antes de entrada
- [ ] Position correlation tracker
- [ ] Automated rebalancing
- [ ] Email/SMS alerts
- [ ] Web dashboard

---

**Última actualización:** 2026-05-15
**Versión:** 1.0 (Production Ready)
**Autor:** Juan (firu)
