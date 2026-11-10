# Estrategia ROTACION (2026-11-09)

La única estrategia del proyecto con ventaja medida en un backtest con
comisiones y validada fuera de muestra. Sustituye como vía recomendada al
sistema de gate + 6 modelos + ML, que según sus propias auditorías nunca
demostró ventaja (`comparison.json`: `deployable: false`).

## Por qué se cambió de enfoque

El sistema anterior buscaba +2-4% en horas con stops de -1.5/-2.5%. A esa
escala la comisión de ida y vuelta (0.2-0.3%) se come gran parte del
movimiento, el ruido domina y las noticias gratuitas (RSS) llegan cuando el
precio ya reaccionó. Además no se podía backtestear de punta a punta, así que
cada ajuste era a ciegas.

La rotación opera en velas diarias, donde los dos efectos más documentados en
cripto sí aparecen en los datos: **tendencia** (lo que sube tiende a seguir
subiendo unas semanas) y **régimen** (casi todas las pérdidas grandes ocurren
con BTC bajo su media larga).

## Reglas

1. **Régimen**: si BTC cierra bajo su media de 100 días, todo a USDT.
2. **Selección semanal** (cierre diario del domingo UTC): las 3 monedas del
   universo con mayor retorno a 30 días que estén sobre su media de 50 días.
3. **Tamaño**: volatilidad inversa, exposición escalada a ~50% de volatilidad
   anual, máximo 40% en una moneda, nunca más del 100% (sin apalancamiento).
4. **Kill switch**: si la cartera cae 40% desde su pico, liquida y se detiene.

Universo fijo de 30 pares (`backtest/data.py`), que incluye monedas a las que
les fue mal (EOS, FIL, ETC, XLM, MATIC) para no sesgar hacia las ganadoras.

## Resultados (velas diarias Binance, coste 0.15% por lado)

| Periodo | Retorno anual | Caída máx. | Sharpe | Operaciones | % ganadoras | Ganancia/pérdida media |
|---|---|---|---|---|---|---|
| Diseño 2019-2022 | +35.9% | -24.7% | 1.27 | 146 | 41.8% | 3.2x |
| **Validación 2023-nov 2026** | **+28.6%** | **-31.1%** | **0.97** | 214 | 43.5% | 2.4x |

Por año: 2019 +1.9%, 2020 +103%, 2021 +98%, 2022 **-10%** (BTC -64%),
2023 +96%, 2024 +34%, 2025 **-3.5%**, 2026 +3.9% (BTC -14%).

Es el perfil pedido: pierde más veces de las que gana (≈43% de aciertos),
pero la ganancia media es 2.4-3.2 veces la pérdida media.

### Comprobaciones de robustez

- 216 variantes de parámetros (régimen 50-200, momentum 14-90, 2-5 monedas,
  rebalanceo 3-14 días): **todas positivas en validación**; mediana +26.6%
  anual, peor +2.8%, caída máxima mediana -35%.
- Los 7 días posibles de rebalanceo: todos positivos (Sharpe 0.97-1.36).
- Con el coste duplicado y cuadruplicado sigue positiva (+32% → +23% anual
  en la variante genérica).
- Sin las monedas añadidas más tarde (APT, SUI, ARB, OP, INJ, SHIB): +21.8%.
- El ejecutor simulado del bot, reproducido día a día sobre 2023-2026, da el
  mismo resultado que el backtest.
- `python -m backtest.test_backtest` verifica que no hay look-ahead.

## Lo que NO promete

- **No es una garantía.** Un backtest dice qué habría pasado, no qué pasará.
- Hay años planos o negativos (2019, 2022, 2025). Caídas de -30% son normales
  aquí; hay que poder aguantarlas sin apagar el bot.
- En mercados alcistas fuertes gana **menos que simplemente tener BTC**
  (2023-26: BTC +355% total con caída de -53%; el bot +164% con -31%). Lo que
  aporta es evitar la mayor parte de los mercados bajistas.
- Pasa meses en USDT. Que no opere no es un fallo.
- Los parámetros por defecto se vieron contra el periodo de validación antes
  de la prueba de robustez; por eso el número a esperar es la mediana de las
  variantes (~+25% anual, -35% de caída), no el mejor caso.
- El universo de 30 monedas se eligió en 2026; hay algo de sesgo de
  supervivencia aunque se incluyeron perdedoras.

## Uso

```bash
python -m backtest.data                  # descarga/actualiza histórico
python -m backtest.research              # tabla de resultados
python bot_crypto.py rotation signal     # qué pide la estrategia hoy
python bot_crypto.py rotation once       # un ciclo en simulación
python bot_crypto.py rotation run        # bucle 24/7 en simulación (00:05 UTC)
python bot_crypto.py rotation status     # cartera y P&L
```

Variables: `ROT_CAPITAL` (presupuesto, default 1000), `ROT_MAX_DD_PCT` (40),
`ROT_MIN_TRADE_USD` (10). Con menos de ~150 USD varias órdenes quedarán bajo
el mínimo de Binance (5-10 USD) y la cartera no podrá seguir los pesos.

### Órdenes reales

`rotation run --execute` envía órdenes MARKET al entorno de `BINANCE_MODE` y
exige `AUTO_EXECUTE=True`. El bot solo usa `ROT_CAPITAL` y las monedas que él
mismo compró. Recomendado: 4-8 semanas en simulación o testnet con régimen ON
antes de dinero real, clave API sin permiso de retiro, y solo dinero que se
pueda perder.

## Prueba 24/7 gratis (sin PC encendido)

La estrategia decide una vez al día, así que no necesita un servidor: el
workflow `.github/workflows/rotation-paper.yml` corre el ciclo en GitHub
Actions a las 00:10 UTC (19:10 Colombia), gratis en un repo público.

- Modo simulación únicamente: no usa claves de Binance ni envía órdenes.
- La cartera simulada y los reportes quedan en la rama `paper-state`
  (`rotation_state.json`, `rotation_equity.csv`, `rotation_trades.csv`,
  `ultimo_ciclo.txt`).
- Se activa al fusionar esta rama en `main` (los cron solo corren desde la
  rama por defecto). Se puede lanzar a mano en Actions → "Rotacion (paper)"
  → Run workflow.
- Capital simulado: variable de repositorio `ROT_CAPITAL` (default 1000).
- Usa `BINANCE_PUBLIC_URL=https://data-api.binance.vision` porque
  `api.binance.com` rechaza IPs de EE.UU., donde corren los runners.
- GitHub desactiva los cron de un repo público tras 60 días sin actividad;
  si pasa, se reactiva con un clic en la pestaña Actions.

Para órdenes reales GitHub Actions no sirve (IP de EE.UU. bloqueada por
Binance y no conviene guardar claves ahí): eso requiere una VM fuera de
EE.UU., p. ej. Oracle Cloud Always Free (ver DEPLOY_GRATIS.md).
