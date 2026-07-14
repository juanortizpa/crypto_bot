# 📋 Plan de Entrenamiento: Modelos A-D con Klines 5min

## ¿Qué cambió?
- ✅ Descarga de klines 5min completada (4.6M bars 2024-2026)
- ✅ Eventos globales integrados (32 eventos críticos)
- ✅ Features engineering completo (219K filas con 50+ variables)
- ❌ ML puro NO funciona (20% win rate)
- ✓ Gate-based models (A-D) SÍ funciona (48% en pánico)

## Nueva Estrategia

**NO entrenaremos XGBoost/Hybrid/Grid puros.**

En su lugar, **validaremos los 4 modelos existentes (A-D) con datos reales 5min:**

### Los 4 Modelos (ya existen, solo validar):

```
Modelo A - Conservador (Green gates solo)
  Entrada: Gate ≥ 7, sin RED
  Stop: -1.5%, Target: +2.5%
  Riesgo: Muy bajo, pocas trades

Modelo B - Momentum (MA + momentum fuerte)
  Entrada: Gate ≥ 5, S1 verde
  Stop: -2%, Target: +4%
  Riesgo: Medio

Modelo C - News Spike (Noticias + bajo FNG)
  Entrada: N1 evento crítico, FNG < 40
  Stop: -2%, Target: +3%
  Riesgo: Bajo, muy selectivo

Modelo D - Dip Scalper (Pánico + compra)
  Entrada: FNG < 25, drawdown extremo
  Stop: -3%, Target: +6%
  Riesgo: Moderado, alta recompensa
```

## Flujo de Validación (Esta Semana)

### PASO 1: Marcar entradas con el gate (5 min)
```bash
python bot_crypto.py scan BTC  # Ver gate score ahora
python bot_crypto.py gate BTC  # Análisis completo del gate
```

### PASO 2: Ejecutar predicciones (SIN comprar)
```bash
AUTO_EXECUTE=False  # ← Importante: Solo logs
python run_crypto_models.py
# Output: crypto_predictions.db con señales A-D
```

### PASO 3: Monitorear 1-2 semanas
```bash
# Cada día a las 9 AM:
python run_crypto_models.py
# Cada día a las 8 PM:
python run_crypto_models.py outcomes

# Ver cuál modelo gana:
python bot_crypto.py compare
```

### PASO 4: Identificar ganador
```
Si Model C (News) > 55% WR  → Activar en testnet
Si Model D (Dip) > 50% WR   → Activar en testnet
Si Model A (Conservative)   → Más lento pero más seguro
```

### PASO 5: Testnet Live (Cuando gane claro)
```bash
BINANCE_MODE=testnet
AUTO_EXECUTE=True
INITIAL_CAPITAL=10  # $10 USD
python run_crypto_models.py  # En testnet
```

## Qué NO hacer

❌ Re-entrenar Grid Search (no funciona)
❌ Tunar XGBoost (features limitadas)
❌ Optimizar PnL (ya está calibrado)

## Qué SÍ hacer

✅ Validar gate + 4 modelos con 5min data
✅ Elegir modelo que más tradea
✅ Testear en testnet 1-2 semanas
✅ Escalar a $50-$100 si win rate > 50%
✅ Documentar resultados

## Timeline

```
HOY:           python run_crypto_models.py (mode=predict-only)
Mañana-Jueves: Monitorear predicciones
Viernes:       Ver comparativa de modelos
Próx semana:   Testnet live si hay ganador
```

## Validación de Éxito

### Mínimo (violar = no tradear aún)
- [ ] n_trades > 50 (cada modelo)
- [ ] win_rate > 45%
- [ ] profit_factor > 1.5

### Target (bueno para testnet)
- [ ] win_rate > 52%
- [ ] profit_factor > 2.0
- [ ] trades distribuidos en múltiples pares

### Excelente (listo para live)
- [ ] win_rate > 55%
- [ ] profit_factor > 2.5
- [ ] sin correlación entre modelos (diversificación)

## Archivos clave

- `.env`: BINANCE_API_KEY, BINANCE_SECRET_KEY, BINANCE_MODE=testnet, AUTO_EXECUTE=False
- `run_crypto_models.py`: Corre todos los días (9am + 8pm)
- `bot_crypto.py compare`: Ver ganador
- `state/crypto_predictions.db`: Historial de trades

## Próximo paso

```bash
# AHORA:
cd crypto_bot
python run_crypto_models.py
# Esperar output...
# Si ve predicciones → TODO OK
# Si hay error → Revisar logs/
```
