# Guía Diaria — Operación, Análisis y Datos para Entrenar

Rutina diaria del bot tras la limpieza del 2026-06-01 (DB desde cero, thresholds nuevos,
selección por mejor modelo activada). Todos los comandos se corren desde:

```
cd "C:\Users\JUAN\Documents\Claude\Projects\operacion cripto\crypto_bot"
.\.venv\Scripts\Activate.ps1
```

---

## 0) Una sola vez (hoy, después de la limpieza)

Aplicar los thresholds nuevos sin reiniciar nada más:

```bash
python bot_crypto.py ml-reload      # recarga xgb=0.60 / rf=0.55 / hybrid=0.55
```

> Si no lo corres, igual se aplican en la primera predicción del próximo `run`.

---

## 1) Mañana — arrancar la sesión

```bash
python bot_crypto.py status         # 1. conexión a Binance OK
python bot_crypto.py risk           # 2. risk guard NO tripped, capital correcto
python bot_crypto.py fear           # 3. Fear & Greed del día (contexto del Modelo D)
python bot_crypto.py run --dry-run  # 4. sesión paper de hasta 17h (sin dinero)
```

`run` hace todo el ciclo solo: escanea los 20 pares, pasa el gate de 16 factores,
consulta el ensemble ML, **elige el modelo con mayor expectativa (EV)** y monitorea
cada trade en tiempo real hasta cerrarlo por condición (no por tiempo fijo).

- Paper / pruebas: `run --dry-run`
- Testnet real: `run` (requiere `BINANCE_MODE=testnet` en `.env`)
- Sesión más corta: `run --dry-run --hours 8`

Déjalo corriendo. Con la lógica nueva, en los logs deberías ver líneas como:

```
SOLUSDT: modelos que califican -> B(p=0.61,ev=+0.012), D(p=0.55,ev=+0.004)
SOLUSDT: elegido modelo B (P(WIN)=0.61, EV=+0.012)
```

Eso confirma que ya **no opera solo D**: varios modelos compiten y gana el de mejor EV.

### Inspección puntual (opcional, sin abrir trade)
```bash
python bot_crypto.py scan            # ranking de pares por gate ahora mismo
python bot_crypto.py gate SOLUSDT    # los 16 factores de un par
python bot_crypto.py ml-debug SOLUSDT# features + probabilidad de cada modelo ML
python bot_crypto.py predict SOLUSDT # guarda predicción sin comprar
```

---

## 2) Tarde/Noche — cerrar y extraer el análisis

Corre en este orden:

```bash
python bot_crypto.py outcomes        # 1. resuelve pendientes al precio actual
python today.py                      # 2. trades de HOY (WR, P&L neto)
python run_crypto_models.py report   # 3. WR + expectativa por modelo
python bot_crypto.py ml-eval         # 4. etiqueta retrospectiva de cada decisión ML
python bot_crypto.py ml-report       # 5. calidad de las decisiones ML
```

### Qué mirar en cada reporte

**`report` (comparación de modelos)** — la tabla principal. Por cada modelo:
- `WR%` — win rate. Objetivo global **> 55%**.
- `Exp` (expectativa) — P&L medio por trade. **Debe ser > 0**. Esto manda más que el WR:
  un modelo con 45% WR y Exp +0.30% es rentable.
- Regla de auto-ejecución: un modelo pasa a candidato real cuando tiene
  **≥ 15 trades, WR ≥ 55% Y Exp > 0**.

**`ml-report` (calidad de decisiones)** — mide si el ML acierta al filtrar:
- `Entry accuracy` — % de GO que terminaron en ganancia. Objetivo **subirlo de 35%**
  (era el problema antes de subir thresholds). Vigílalo: si sigue < 45% con volumen
  suficiente, hay que recalibrar o reentrenar.
- `Skip accuracy` — % de vetos correctos. Si es alto (>85%) el filtro protege bien.
- `BAD_GO` — entradas que el ML aprobó y perdieron. Es el número a reducir.
- `MISSED_WIN` — ganadores que vetó de más. Si crece mucho, los thresholds quedaron
  demasiado estrictos.

**`today.py`** — foto del día: wins, losses, P&L neto en USD.

### Anota cada día (lleva un registro simple)
Fecha · nº trades · WR% · Exp · P&L neto · Entry accuracy · BAD_GO · MISSED_WIN.
Con 2-3 semanas de esto ves la tendencia real, no el ruido de un día.

---

## 3) Datos para entrenar — dos caminos distintos

Hay **dos** entrenamientos y no se deben confundir:

### A) Recalibrar el meta-modelo de ENTRADA (qué modelo elegir y thresholds)
Se alimenta de **los trades vivos** que se van acumulando en
`state/crypto_predictions.db` y `state/ml_decisions.db`. No hay que descargar nada:
operar genera el dataset.

- **Cuándo:** cuando acumules **~150–200 trades cerrados** (no antes; con menos se
  sobreajusta).
- **Cómo medir si hace falta:** si `ml-report` muestra Entry accuracy estancado < 45%
  con buen volumen, o las probabilidades no separan ganadores de perdedores.
- **Mientras tanto:** ajusta thresholds en los `*_best.json` (no reentrenes) y corre
  `python bot_crypto.py ml-reload`.

Para revisar cuántos datos llevas acumulados:
```bash
python -c "import sqlite3;c=sqlite3.connect('state/crypto_predictions.db');print('cerrados:',c.execute(\"SELECT COUNT(*) FROM predictions WHERE outcome IN('WIN','LOSS')\").fetchone()[0])"
```

### B) Reentrenar el ensemble del Modelo D (xgb / rf / hybrid)
Pipeline **offline** con klines históricos, en `model_d_training/`. No usa los trades
vivos sino velas descargadas de Binance. Corre en orden (en tu PC, no en sandbox):

```bash
python -m model_d_training.download_data    # 1. descarga klines 2026 (~30 min)
python -m model_d_training.features         # 2. features + labels
python -m model_d_training.train_grid       # 3a. Trainer A (grid)
python -m model_d_training.train_xgb        # 3b. Trainer B (XGBoost)
python -m model_d_training.train_hybrid     # 3c. Trainer C (híbrido)
python -m model_d_training.compare          # 4. compara y elige ganador (OOS)
python -m model_d_training.live_runner --dry-run --once   # 5. verificación
```

- **Cuándo:** cada **2-4 semanas**, o si el régimen de mercado cambia mucho
  (los modelos actuales son del 21-may; revísalos si el comportamiento se degrada).
- **Checklist antes de confiar en el ganador:** el `compare` debe mostrar
  **WR > 55% y PF > 1.5** out-of-sample.
- Reentrenar **sobrescribe** los `results/*_best.json`, así que perderás los thresholds
  que subimos a mano. Tras reentrenar, vuelve a revisar/ajustar los thresholds.

---

## Resumen de un día típico

```
Mañana:   status → risk → fear → run --dry-run   (déjalo corriendo)
Noche:    outcomes → today.py → report → ml-eval → ml-report
Semanal:  revisar tendencia anotada; ajustar thresholds si hace falta
Mensual:  reentrenar ensemble D (pipeline offline) si el régimen cambió
```

## Recordatorios de seguridad
- Sigue en **paper/testnet**. No pongas dinero real hasta tener **2-3 semanas**
  con WR ≥ 55% y expectativa > 0 sostenidos.
- No expandas más allá de los 20 pares entrenados (extrapolación sin entrenamiento).
- Backups de la DB antes de cualquier limpieza: ya hay `.bak_20260601_041226` en `state/`.
