# Auditoría del bot — 10 junio 2026

## Resumen

El 97% de win rate nunca fue real: era un artefacto de cómo el bot contaba los resultados, no de la calidad de las predicciones. Cuando el mercado cambió de régimen, la contabilidad inflada dejó de disimular que el sistema no tenía ventaja estadística, y empezaron las pérdidas visibles. La buena noticia es que tu propio pipeline de entrenamiento ya lo había detectado: `DIAGNOSIS_0TRADES.md` documenta que los features puros logran solo ~20% de WR real en mercado normal, y `results/comparison.json` marca el sistema como `"deployable": false` con 0 trades en la validación out-of-sample de abril-mayo 2026.

## Por qué el 97% era falso

La función `check_outcomes()` en `bot/predictions.py` tenía tres trampas de contabilidad. Primera: un trade que expiraba con cualquier P&L positivo —aunque fuera +0.01%, que neto de comisiones es pérdida— se contaba como WIN. Segunda: los cierres en breakeven (trailing stop a entrada, ganancia 0%) también se contaban como WIN. Tercera y más grave: los resultados se resolvían con el precio del momento en que corrías el script, no con el camino real del precio. Si un trade tocaba el stop a las 2am y rebotaba antes de que corrieras `outcomes` por la mañana, el stop nunca se registraba. En cambio el backtest de entrenamiento (`simulate_trade` en `features.py`) sí recorre vela por vela. Es decir: el backtest y el modo en vivo medían cosas distintas, y el modo en vivo medía con un sesgo optimista enorme. Con targets de +2-4% y la regla de "expirado positivo = WIN", casi cualquier mercado lateral-alcista produce 90%+ de "wins" contables.

Consecuencia adicional: el `meta_model` y el `exit_model` se entrenaron con esas etiquetas WIN/LOSS contaminadas. Aprendieron a predecir la contabilidad rota, no el mercado. Hay que reentrenarlos desde cero una vez que la base acumule trades con la contabilidad corregida.

## Por qué ahora pierde

Cuatro causas se combinan. El régimen de mercado cambió respecto al periodo de calibración (tu propio diagnóstico muestra 48% WR en condiciones de pánico 2024-2025 contra 19-22% en mercado normal 2026 — la señal venía del régimen, no de los factores). El sistema es 100% long-only, así que en mercado bajista o lateral-bajista todos los modelos A-F pierden a la vez; no hay diversificación real entre 6 modelos que compran lo mismo con umbrales distintos. Los filtros del grid (`grid_best.json`: RSI≤40, FNG≤25, DD≤-20%, momentum≥2%) se sobreajustaron a un escenario de pánico que ya no existe, por eso la validación walk-forward dio 0 trades. Y había un bug que mataba el monitor en el peor momento posible (detalle abajo), dejando trades perdedores sin gestión.

## Bugs corregidos en esta sesión

En `bot/predictions_realtime.py`, la condición 4 de `evaluate_dynamic_close()` hacía `gate['red_count']` sobre un objeto `GateResult` que no es subscriptable. Eso lanzaba `TypeError` y tumbaba el proceso del monitor exactamente cuando un trade perdía ≥2% — o sea, el cierre anticipado de perdedores no funcionó nunca, y además el crash dejaba todos los demás trades sin monitoreo. Corregido (`gate.red_count`), con try/except por símbolo para que un error puntual no mate el loop. También corregí `VOLATILITY_THRESHOLD`: estaba en 0.05 (=ATR&lt;0.05%, condición casi imposible, regla muerta); ahora 0.25%.

En `bot/predictions.py`: ahora existe `_path_outcome()`, que reconstruye el camino real del precio con velas de 5m (o 1h si la predicción es vieja) y detecta stops/targets tocados aunque el precio haya rebotado después; si stop y target caen en la misma vela se asume LOSS (criterio conservador, lo opuesto al heurístico optimista del backtest). Los trades expirados solo cuentan WIN si superan `FEE_RT_PCT` (0.25% round-trip); entre -0.25% y +0.25% se marcan `BE` (nuevo outcome, excluido del win rate y del entrenamiento de los ML, que filtran `WIN/LOSS`). El breakeven por trailing también se marca `BE`, no WIN.

Con esto el win rate que veas en `report` va a BAJAR bastante. Ese número más feo es el verdadero. No lo "arregles" volviendo atrás: es la única base sobre la que se puede mejorar de verdad.

## ¿Se pueden predecir bajadas con los factores actuales?

Sí, en principio. Los 13-16 factores son simétricos en información: RSI alto, momentum negativo, precio extendido sobre MA50, BTC bajista, F&G en euforia y volumen débil son señales bajistas tan válidas como sus opuestos son alcistas. Lo que es long-only no son los factores sino el pipeline completo: las etiquetas de entrenamiento solo simulan compras (stop abajo, target arriba), el gate define GREEN=alcista, y los 6 modelos A-F solo abren longs. La clase "no sube" de tus modelos actuales NO equivale a "va a bajar" — mezcla bajadas con laterales.

Para responderlo empíricamente creé `model_d_training/train_directional.py`: entrena dos clasificadores con los mismos factores, uno LONG (¿sube a +target antes de -stop?) y uno SHORT (¿baja a -target antes de +stop?), validados con walk-forward, embargo temporal y comisiones incluidas. Al correrlo imprime un veredicto comparando la expectancy out-of-fold de ambos lados. Dos advertencias: tu diagnóstico previo sugiere que estos features son débiles en mercado normal también para el lado corto, así que no esperes magia; y en spot no se puede shortear — la señal SHORT sirve de entrada solo con Futures/Margin, pero incluso sin eso es valiosa como veto de entrada y disparador de salida para los longs.

## Sobre el objetivo de "no perder ningún trade"

No existe y no puede existir un bot con 100% de win rate; cualquier sistema que lo aparente está ocultando el riesgo en otra parte (como hacía el tuyo con la contabilidad). El objetivo correcto es expectancy positiva neta de comisiones con drawdown controlado: por ejemplo 45% WR con ganancias medias del doble que las pérdidas medias es un sistema excelente. Las métricas que importan, en orden: expectancy por trade, profit factor, max drawdown, y recién después win rate.

## Mejoras aplicadas (segunda pasada, misma fecha)

Además de los fixes de contabilidad, se aplicaron estas mejoras directamente al código.

**Cuarto bug crítico encontrado y corregido — precios congelados en el monitor.** El caché de `crypto_data` solo se vacía con `clear_cache()`, y el loop del monitor nunca lo llamaba. Resultado: a partir del segundo ciclo, `get_price()` devolvía siempre el precio del primer ciclo. El "monitor en tiempo real" miraba una foto congelada — stops, targets y cierres anticipados no se disparaban nunca mientras corría. Combinado con el crash de `gate['red_count']`, el monitoreo real-time simplemente no existía. Ahora cada ciclo limpia el caché.

**Señal bajista activa (`bot/short_signal.py`).** Score 0-7 construido con tus mismos factores leídos en espejo: RSI sobrecomprado, estructura p&lt;MA20&lt;MA50, momentum 4h negativo, mayoría de velas rojas en 6h, BTC cayendo 24h, vendedores dominando el taker flow, y precio sobre-extendido. Se usa en dos puntos: como veto de entradas long en `evaluate_model` (si score ≥ 4, ningún modelo excepto D abre), y como salida anticipada en el monitor (si score ≥ 4: asegura ganancia con `BEAR_SIGNAL_LOCK` o corta pérdida con `BEAR_SIGNAL_CUT` sin esperar el stop completo). Es la respuesta práctica a tu pregunta: los factores sí predicen bajadas, y ahora el bot las usa para defenderse.

**Guarda de régimen en `crypto_models.py`.** Tu propio diagnóstico demostró que la señal viene del régimen de mercado. Ahora, con BTC bajista (M1 RED), solo el modelo D (Dip Scalper) puede abrir; A, B, C, E y F quedan vetados. Antes, B podía abrir longs con BTC cayendo si el resto del gate acompañaba.

**Circuit breaker (`bot/circuit_breaker.py` + factor X2 del gate).** Si los trades cerrados acumulan -5% en 24h, o hay 4 pérdidas consecutivas, el gate veta toda entrada nueva durante 12h (veto duro X2). Esto es lo que faltaba cuando "no parabas de perder": ningún mecanismo decía basta. Configurable por variables de entorno (`CB_*`). X2 se reporta YELLOW cuando está OK a propósito, para no inflar el green_count con el que se calibraron los umbrales de los modelos.

**Guard de modelos ML contaminados.** `meta_model` y `exit_model` ahora rechazan cualquier `.pkl` entrenado antes del 2026-06-10 (etiquetas infladas). El runner cae automáticamente a P(WIN)=0.5 neutro hasta que reentrenes con trades de la contabilidad nueva — no hace falta borrar nada a mano.

**Misma corrección de contabilidad en `runner.py`.** Sus dos funciones de cierre también marcaban WIN con pnl ≥ 0 (incluido 0.0%). Ahora aplican la regla fee-aware (WIN &gt; +0.25%, LOSS &lt; -0.25%, BE en el medio).

**Smoke test (`smoke_test.py`).** Verifica en segundos que todo lo anterior está activo: `python smoke_test.py` (offline) o `python smoke_test.py --network` (incluye llamadas a Binance).

## Tercera pasada: la ruta que realmente usas (`bot_crypto.py run --dry-run`)

Tu flujo real no pasa por `run_crypto_models.py` sino por `bot/runner.py` + `bot/trade_monitor.py`. Auditada esa ruta, aparecieron dos fallas más, ambas corregidas.

**Stops y targets eran decorativos.** Las reglas de salida de `trade_monitor._evaluate_rules` (R1-R8) nunca comparaban el precio contra `stop_price` ni `target_price`. Un dump temprano atravesaba el stop sin cerrar nada, porque R1 exigía pérdida &gt; 1.8% **y** que hubiera pasado 30% del tiempo — en la primera fase del trade no había ningún freno. Y al tocar el target, H1/H2 devolvían HOLD ("dejar llegar"): la ganancia de +3% nunca se cobraba y el trade solo salía tras devolver el 70% del pico (R3). Es la receta exacta de "los perdedores pierden más de lo planeado y los ganadores se devuelven". Ahora `record_snapshot` aplica niveles duros con prioridad sobre todas las reglas: precio ≤ stop → `STOP_HIT_HARD`, precio ≥ target → `TARGET_HIT`.

**Caché congelado también en el runner.** El loop de `runner.run()` solo limpiaba el caché indirectamente vía `scan()` (cada 5 min, y solo cuando la sesión permite abrir trades). En FREEZE (últimas 2h de sesión) o con el risk guard activado — es decir, exactamente cuando vas perdiendo — el monitor corría con precios congelados del último scan. Ahora `_monitor_open_positions` limpia el caché en cada ciclo (60s).

También se aplicó la contabilidad fee-aware al comando `cleanup` de `bot_crypto.py`. El smoke test cubre ahora esta ruta (3 checks nuevos): vuelve a correr `python smoke_test.py`.

## Qué ejecutar ahora (en tu PC, con el venv activado)

Primero: `python smoke_test.py --network` — debe dar todo OK. Después valida el flujo completo: `python run_crypto_models.py full` y revisa que resuelve pendientes con los nuevos flags (`PATH_CHECK`, `BE`, `BEAR_SIGNAL_*`). Corre el análisis direccional: `python -m model_d_training.train_directional` y mira `results/directional_report.json`. Acumula 2-3 semanas de trades con la contabilidad honesta en testnet y solo entonces reentrena meta/exit model (`train_meta_model()` y `train_classifier()`) — los `.pkl` viejos ya quedan ignorados automáticamente por el guard. Mantén `CRYPTO_PAIRS = TOP_20` y no pases a mainnet hasta que la expectancy neta sea positiva sostenida con la contabilidad nueva.
