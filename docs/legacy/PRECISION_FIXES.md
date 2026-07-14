# FIXES DE PRECISIÓN — Cierre Dinámico + Monitoreo Real-Time

## PROBLEMA IDENTIFICADO

El bot anterior cerraba trades en un tiempo FIJO (`max_hours`):
- Modelo A: 4h
- Modelo B: 2h
- Modelo D: 8h
- etc.

**Resultado**: Trades ganadores se cerraban ANTES de alcanzar target, perdiendo ganancias.
Trades perdedores se mantenían esperando a que venza el timer.

---

## SOLUCIÓN: 3 MEJORAS

### ✅ MEJORA 1: CIERRE DINÁMICO (cierre anticipado inteligente)

En lugar de esperar `max_hours`, el bot ahora cierra automáticamente cuando:

1. **Stop Hit** → LOSS inmediato (siempre)
2. **Target Hit** → WIN inmediato (siempre)
3. **+3% ganancia** → WIN anticipado (no espera más)
4. **Momentum invierte** → LOSS anticipado (gate más rojo que verde)
5. **Volatilidad colapsa** → LOSS (sin movimiento esperado)

**Beneficio**: Protege ganancias rápido en cryptos volátiles.

---

### ✅ MEJORA 2: MONITOREO CADA 5 MINUTOS

En lugar de resolver predicciones una vez al día, ahora:

- Chequea cada 5 minutos si algún trade debe cerrarse
- Corre continuamente en background
- Cierra dinámicamente cuando se cumplan condiciones

**Beneficio**: Captura movimientos rápidos, aprovecha ganancias antes de revertirse.

---

### ✅ MEJORA 3: VALIDACIÓN DE DATOS

Verifica que:
- Todas las coins en `CRYPTO_PAIRS` tienen precio
- No hay coins faltando
- La conexión a Binance API es estable

**Beneficio**: Asegura que el análisis es sobre datos completos.

---

## CÓMO USAR (desde Windows)

### OPCIÓN A: Flujo Manual (recomendado para testing)

**Terminal en Windows (PowerShell o CMD):**

```powershell
# Navega a la carpeta
cd "C:\Users\JUAN\Documents\Claude\Projects\operacion cripto\crypto_bot"

# Activa el virtual env
.\.venv\Scripts\Activate.ps1

# 1. Generar predicciones nuevas
python run_crypto_models.py full

# 2. Inicia monitoreo en tiempo real (corre continuamente)
python run_crypto_models.py monitor
# Presiona Ctrl+C para detener

# 3. Valida cobertura de datos
python run_crypto_models.py validate

# 4. Audita cambios (compara viejo vs nuevo)
python run_crypto_models.py audit
```

### OPCIÓN B: Batch File (más fácil)

**Crea `C:\Users\JUAN\Documents\Claude\Projects\operacion cripto\crypto_bot\monitor.bat`:**

```batch
@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python run_crypto_models.py monitor
pause
```

Luego solo double-click el archivo `.bat` para correr.

---

## FLUJO RECOMENDADO

**CADA MAÑANA:**
```
1. python run_crypto_models.py full
   → Resuelve predicciones del día anterior
   → Genera nuevas predicciones
```

**DURANTE EL DÍA:**
```
2. python run_crypto_models.py monitor
   → Deja corriendo en terminal
   → Monitorea cada 5 min
   → Cierra dinámicamente
   → Presiona Ctrl+C cuando sea hora de nuevas predicciones
```

**TARDE/NOCHE:**
```
3. Vuelve a paso 1
```

---

## PARÁMETROS AJUSTABLES

En `bot/predictions_realtime.py` puedes cambiar:

```python
MONITOR_INTERVAL = 300          # Segundos entre chequeos (5 min)
EARLY_CLOSE_PROFIT = 3.0        # Ganancia % para cerrar WIN anticipado
EARLY_CLOSE_LOSS = -2.0         # Pérdida % para evaluar cierre
VOLATILITY_THRESHOLD = 0.05     # Volatilidad para considerar "baja"
```

---

## MONITOREO: QUÉ VES EN PANTALLA

```
[14:35:21] Check #1...
    [D] BTCUSDT   ✓ WIN  +3.45%  (EARLY_WIN_3.5%)
    [A] ETHUSDT   ✗ LOSS -1.82%  (MOMENTUM_REVERSED_-1.8%)
  → 2 trade(s) cerrado(s)

[14:40:21] Check #2...
  → Todos los trades siguen abiertos

[14:45:21] Check #3...
    [E] SOLusdt   ✓ WIN  +2.10%  (EARLY_WIN_2.1%)
  → 1 trade(s) cerrado(s)
```

---

## CUESTIONES FRECUENTES

**¿Y si me olvido de ejecutar `monitor`?**
→ Las predicciones se resolverán automáticamente cuando ejecutes `full` de nuevo,
pero habrás perdido monitoreo en tiempo real.

**¿Puedo parar el monitor y reiniciarlo?**
→ Sí, presiona Ctrl+C cuando quieras parar. Los trades se quedan como están en la BD.

**¿Qué pasa si cierro la terminal mientras corre?**
→ Los trades PENDING quedan como estaban. Vuelve a ejecutar `monitor` para continuar.

**¿Los 5 minutos son fijos?**
→ Sí, pero puedes cambiar `MONITOR_INTERVAL` en el código si quieres más/menos frecuencia.

---

## PRÓXIMAS MEJORAS

Una vez valides este sistema:

1. **Auto-execute**: Conectar al testnet de Binance para ejecutar órdenes reales
2. **Websocket**: En lugar de polling cada 5 min, usar websocket para reaccionar instant
3. **Machine Learning**: Aprender patrones de cierre dinámico optimal

---

## VALIDACIÓN RÁPIDA

Para verificar que todo funciona:

```powershell
# Valida que los datos se descargan
python run_crypto_models.py validate

# Debe mostrar ✓ para todas las coins
```

Si alguna coin muestra ✗, es un problema de Binance API o conexión.

---

**¿Listo para probar?** 
Ejecuta desde Windows terminal: `python run_crypto_models.py full`
