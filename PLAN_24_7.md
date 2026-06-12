# Plan de Prueba 24/7 — Un Mes en Testnet

Objetivo: dejar el bot corriendo un mes completo en el portátil, recolectar
datos con la **contabilidad honesta** (v1.1) y decidir con números si está
listo para mainnet. Todo lo descrito aquí está automatizado por
`python bot_crypto.py forever`; este documento explica qué hace, qué valores
usa y qué revisar tú.

---

## 0) Instalación en un portátil virgen (Windows)

1. Instalar **Python 3.11** (python.org, marcar "Add Python to PATH") y **Git**.
2. Clonar y preparar el entorno:
   ```powershell
   git clone https://github.com/juanortizpa/crypto_bot.git
   cd crypto_bot
   python -m venv .venv
   Set-ExecutionPolicy -Scope Process Bypass
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
3. Crear `.env` con las keys de **testnet.binance.vision**:
   `BINANCE_API_KEY`, `BINANCE_API_SECRET`, `BINANCE_MODE=testnet`, `CRYPTO_PORTFOLIO=1000`.
4. Datos: bajar la base histórica (6.4 GB, ver README §Datasets en Hugging
   Face) y **continuar la descarga hasta hoy** — el dataset de HF llega solo
   hasta su fecha de corte:
   ```powershell
   python scripts/download_datasets_from_hf.py   # histórico 2024 → corte del dataset
   python bot_crypto.py maintain data            # continúa desde el corte hasta hoy
   ```
   `maintain data` es reanudable: detecta el último timestamp en cada DB y
   baja solo lo que falta (klines 5m de los 20 pares + 1m/funding/OI/macro
   de `data_extended.db`). Si se corta la conexión, relánzalo y sigue donde
   quedó. Equivale a correr `python -m model_d_training.download_data` y
   `python -m model_d_training.download_extended`. Durante el mes, `forever`
   repite este refresco a diario en automático.
5. **Entrenar el ensemble ML (Modelo D)** — los `.pkl` entrenados no viajan
   en GitHub: se generan en el propio portátil a partir de los datos del
   paso 4. Es una sola vez, ~1-3 h de CPU (déjalo corriendo):
   ```powershell
   python -m model_d_training.features        # features + labels desde las velas
   python -m model_d_training.train_grid      # Trainer A (grid)
   python -m model_d_training.train_xgb       # Trainer B (XGBoost)
   python -m model_d_training.train_hybrid    # Trainer C (híbrido)
   python -m model_d_training.compare         # validación OOS y veredicto
   ```
   Revisa la salida de `compare`: el objetivo es WR > 55% y PF > 1.5
   out-of-sample (GUIA_DIARIA §3B). Si sale `NO DEPLOYABLE` la prueba puede
   arrancar igual — el ensemble solo filtra las entradas del modelo D y el
   resto de modelos opera con el gate + meta-modelo — pero anótalo en tu
   registro. Este paso regenera los thresholds de
   `model_d_training/results/*_best.json` (sobrescribe los del repo).
6. **meta_model y exit_model**: no hay que hacer nada — arrancan en modo
   neutro (P(WIN)=0.5) y `forever` los entrena automáticamente cuando el
   propio mes acumule los mínimos (80 trades / 100 snapshots post-fix).
7. **Historial**: las DBs de `state/` (predicciones, decisiones ML) se crean
   solas en el primer arranque. El mes empieza con historial limpio — es lo
   deseable para que las métricas midan solo esta prueba.
8. Requisito de disco: ~15 GB libres.

## 1) Arranque (una sola vez)

```powershell
cd crypto_bot
.\.venv\Scripts\Activate.ps1
python smoke_test.py --network        # todo debe dar OK
python bot_crypto.py status           # conexión Binance OK
python bot_crypto.py risk             # guard NO tripped
.\start_24_7.ps1                      # dry-run paper, 31 días
# o:  .\start_24_7.ps1 -Live          # testnet real
```

`start_24_7.ps1` desactiva la suspensión del portátil (con corriente),
activa el venv y relanza el proceso si el intérprete muere. Dentro,
`forever` encadena sesiones y hace el mantenimiento solo.

**Checklist del portátil:**
- [ ] Conectado a la corriente y con red estable (cable > WiFi si se puede).
- [ ] Windows Update en pausa / horas activas configuradas (un reboot
      automático mata el proceso; al relanzar, las posiciones PENDING se
      retoman y `check_outcomes` reconstruye el hueco con velas de 5m).
- [ ] ~5 GB libres en disco (datasets crecen con el refresco diario).
- [ ] Ningún editor con las `.db` de `state/` abiertas.
- [ ] Antivirus: excluir la carpeta del proyecto (los scans bloquean SQLite).

## 2) Qué corre y cada cuánto

| Tarea | Frecuencia | Variable (default) |
|---|---|---|
| Sesión de trading (scan 5 min, monitor 60 s) | continua, en bloques de 8h | `CRYPTO_SESSION_HOURS=8` |
| Carry-over de posiciones entre sesiones | siempre en forever | `CRYPTO_CARRY_OVER=true` |
| Resolver outcomes (path-check 5m) + ml-eval | antes y después de cada sesión | — |
| Reporte diario (`reports/daily_*.md` + `summary.csv`) | tras cada sesión; consolidado al cambiar de día | — |
| Backup de `crypto_predictions.db` y `ml_decisions.db` | diario (retiene 10) | `CRYPTO_BACKUP_DAYS=1` |
| Refresco incremental de datos (klines 5m + `data_extended.db` con macro DXY/SP500/VIX que usa el ML en vivo) | diario | `CRYPTO_DATA_REFRESH_DAYS=1` |
| Reentrenar meta_model / exit_model con trades vivos | chequeo cada 3 días — **solo entrena** al llegar a 80 trades / 100 snapshots post-fix | `CRYPTO_MODELS_RETRAIN_DAYS=3` |
| Reentrenar ensemble Modelo D (pipeline offline completo) | cada 14 días, **con quality gate**: si el `compare` OOS no lo marca deployable, se restauran los modelos anteriores | `CRYPTO_ENSEMBLE_RETRAIN_DAYS=14` |

Notas de diseño:
- **Carry-over:** a diferencia del modo `run` clásico, al terminar una sesión
  NO se fuerza el cierre de posiciones: quedan PENDING y la siguiente sesión
  las monitorea. Así no se regalan cierres forzosos cada 12h ni se pierden
  las 2h de FREEZE (en forever el freeze baja a 15 min).
- **Reentrenos seguros:** meta/exit model solo aprenden de trades con
  outcome posterior al 2026-06-10 (contabilidad honesta) — el filtro está en
  el código, no depende de limpiar la DB. El ensemble nuevo solo se adopta
  si la validación out-of-sample lo aprueba; si no, se queda el anterior.
- **Reentreno del ensemble con posiciones abiertas:** se pospone hasta una
  ventana sin posiciones (máx. 2 días de gracia); si se fuerza, el hueco de
  monitoreo lo cubre el path-check al volver.
- **Risk guard desatendido:** `DAILY_LOSS` se auto-resetea al día siguiente;
  `CONSEC_LOSSES` tras 12h de cooldown; `DRAWDOWN ≥15%` **no** se auto-resetea
  — el bot pasa a solo-monitoreo y espera tu `risk-reset`. Si esto pasa, la
  prueba del mes se considera fallida: no lo resetees para "seguir probando"
  sin entender la causa.
- **Circuit breaker (X2):** sigue activo con sus pausas propias (-5% en 24h
  o 4 pérdidas seguidas → 12h sin entradas).

## 3) Monitoreo: pre, durante y post predicción

- **Pre:** preflight de cada sesión (conexión Binance con backoff, disco,
  `PRAGMA quick_check` de la DB), gate de 17 factores, señal bajista como
  veto, guardia de régimen (BTC RED → solo modelo D), meta-modelo P(WIN) y
  selección por EV, ensemble ML para el modelo D, sizing con hard caps.
- **Durante:** monitor cada 60 s con caché limpiado por ciclo, stops/targets
  duros con prioridad sobre las reglas R1–R8, trailing a breakeven,
  `BEAR_SIGNAL_LOCK/CUT`, heartbeat en `state/heartbeat.json`.
- **Post:** `check_outcomes` con path-check de 5m y comisiones (WIN/LOSS/BE),
  `ml-eval` etiqueta cada decisión ML (BAD_GO, MISSED_WIN…), reporte diario
  y fila en `summary.csv`.

## 4) Tu rutina durante el mes (5 minutos al día)

```powershell
python bot_crypto.py health        # heartbeat fresco? pendientes? disco? guards?
type reports\summary.csv           # tendencia día a día
```

Y una vez por semana:

```powershell
python bot_crypto.py readiness     # cuántos criterios de lanzamiento se cumplen ya
python bot_crypto.py ml-report     # calidad de las decisiones ML
python run_crypto_models.py report # WR/expectancy por modelo
```

Señales de alarma:
- `health` muestra heartbeat STALE (>5 min) → revisar consola/relanzar.
- `Datos data_extended.db` con >48h de antigüedad → las features macro del
  ML están congeladas; corre `python bot_crypto.py maintain data`.
- Risk guard `DRAWDOWN` tripped → parar y analizar, no resetear a ciegas.

## 5) Decisión al final del mes

```powershell
python bot_crypto.py readiness
```

Criterios (todos deben cumplirse, sobre trades post-fix):
≥14 días operando · ≥20 trades cerrados · WR ≥55% · expectancy >0 neta de
comisiones · profit factor >1.2 · max drawdown de equity <15%.

Si se cumplen: pasar a mainnet **gradualmente** (1% del capital, ver
CLAUDE.md §Deployment). Si no: usar `summary.csv` y los reportes diarios
para diagnosticar qué modelo/regla falla antes de tocar nada.

## 6) Variables de entorno (resumen para `.env`)

```ini
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
BINANCE_MODE=testnet
CRYPTO_PORTFOLIO=1000            # capital simulado de referencia
# Modo 24/7 (defaults ya correctos; solo cambiar si hace falta)
CRYPTO_SESSION_HOURS=8
CRYPTO_FREEZE_HOURS=0.25
CRYPTO_CARRY_OVER=true
CRYPTO_DATA_REFRESH_DAYS=1
CRYPTO_MODELS_RETRAIN_DAYS=3
CRYPTO_ENSEMBLE_RETRAIN_DAYS=14
CRYPTO_BACKUP_DAYS=1
CRYPTO_LOG_MAX_MB=10             # rotación de logs (5 archivos)
```

## 7) Si algo se rompe

| Síntoma | Acción |
|---|---|
| El proceso murió | `start_24_7.ps1` lo relanza solo; las PENDING se retoman |
| DB corrupta (`quick_check` falla) | restaurar la más reciente de `state/backups/` |
| Sin red varias horas | forever espera con backoff; al volver, path-check resuelve el hueco |
| Logs gigantes | rotan solos a 10MB ×5; si no, `CRYPTO_LOG_MAX_MB` |
| Reentreno del ensemble rechazado (`REJECTED_RESTORED`) | normal: el mercado no da señal deployable; se mantiene el modelo anterior |
