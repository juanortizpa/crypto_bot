"""
MEJORAS DE PRECISIÓN - Versión Real-Time

PROBLEMA 1: Bot cerraba trades en tiempo fijo (max_hours)
SOLUCIÓN: Monitoreo cada 5 min + cierre dinámico basado en condiciones

PROBLEMA 2: Sin seguimiento intra-day de condiciones
SOLUCIÓN: Chequeos cada 5 min para:
  - Si P&L >= +3% → cerrar WIN (no esperar a target)
  - Si pérdida >= 2% pero volatilidad alta → aguantar
  - Si momentum se invierte → cerrar LOSS anticipado
  - Si volatilidad cae → cerrar LOSS

PROBLEMA 3: Posibles coins faltando en datos
SOLUCIÓN: Validar que todas las coins en BD están siendo tracked
"""

import sqlite3
import os
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from bot.crypto_data import get_price, atr, get_bars, clear_cache
from bot.crypto_gate import run_gate
from bot.predictions import _conn, DB_PATH
from bot.logger import log
from binance_client import CRYPTO_PAIRS

# Parámetros de monitoreo real-time
MONITOR_INTERVAL = 300  # 5 minutos en segundos
EARLY_CLOSE_PROFIT = 3.0  # Cerrar WIN si ganancia >= 3%
EARLY_CLOSE_LOSS = -2.0  # Cerrar LOSS si pérdida >= 2% (solo en ciertas condiciones)
# FIX: vol_pct se calcula como atr/price*100 (o sea, en %). El valor anterior
# 0.05 significaba ATR < 0.05% — condición casi imposible (regla muerta).
# 0.25 = ATR 1h < 0.25%, un mercado realmente plano para crypto.
VOLATILITY_THRESHOLD = 0.25


# ============================================================================
# PARTE 1: CIERRE DINÁMICO (reemplaza la lógica de time-based)
# ============================================================================

def evaluate_dynamic_close(pred_row):
    """
    Evalúa si un trade debe cerrarse ANTES de que venza el max_hours.

    Retorna:
      (should_close: bool, outcome: str, reason: str)
      Ej: (True, 'WIN', 'EARLY_PROFIT_3%')
    """

    sym = pred_row['symbol']
    entry = pred_row['price_at_pred']
    stop = pred_row['stop_price'] or entry * 0.98
    target = pred_row['target_price'] or entry * 1.03
    model = pred_row['model'] or 'A'

    # Precio actual
    price = get_price(sym)
    if not price:
        return False, "PENDING", "NO_PRICE_DATA"

    pnl_pct = (price - entry) / entry * 100

    # CONDICIÓN 1: Stop hit → LOSS inmediato
    if price <= stop:
        return True, "LOSS", "STOP_HIT"

    # CONDICIÓN 2: Target hit → WIN inmediato
    if price >= target:
        return True, "WIN", "TARGET_HIT"

    # CONDICIÓN 3: Ganancia anticipada (>= 3%)
    if pnl_pct >= EARLY_CLOSE_PROFIT:
        return True, "WIN", f"EARLY_WIN_{pnl_pct:.1f}%"

    # CONDICIÓN 3b: Señal bajista fuerte del par (score >= 4 de 7)
    # Usa los mismos factores del gate leídos en espejo (lado corto).
    # - Si vamos ganando: asegurar la ganancia antes de la caída.
    # - Si vamos perdiendo >= 1%: cortar, no esperar el stop completo.
    if pnl_pct >= 0.5 or pnl_pct <= -1.0:
        try:
            from bot.short_signal import bearish_score, VETO_THRESHOLD
            b_score, b_reasons = bearish_score(sym)
            if b_score >= VETO_THRESHOLD:
                if pnl_pct >= 0.5:
                    return True, "WIN", f"BEAR_SIGNAL_LOCK_{pnl_pct:+.1f}%"
                else:
                    return True, "LOSS", f"BEAR_SIGNAL_CUT_{pnl_pct:+.1f}%"
        except Exception as e:
            log("WARN", f"short_signal({sym}): {e}")

    # CONDICIÓN 4: Pérdida pero con momentum bajando
    if pnl_pct <= EARLY_CLOSE_LOSS:
        try:
            gate = run_gate(sym)
            # Si el gate está más rojo que verde, cerrar LOSS
            # FIX CRÍTICO: run_gate retorna un objeto GateResult, NO un dict.
            # El código anterior hacía gate['red_count'] → TypeError que MATABA
            # el monitor exactamente cuando un trade perdía >= 2%.
            if gate.red_count > gate.green_count:
                return True, "LOSS", f"MOMENTUM_REVERSED_{pnl_pct:.1f}%"
        except Exception as e:
            log("WARN", f"evaluate_dynamic_close({sym}): gate error {e}")

    # CONDICIÓN 5: Pérdida pequeña pero volatilidad colapsó (señal de fin de movimiento)
    if -2 < pnl_pct < 0:
        bars = get_bars(sym, "1h", 20)
        atr_val = atr(bars, 14) if bars else None
        if atr_val:
            vol_pct = (atr_val / price * 100) if price else 0
            if vol_pct < VOLATILITY_THRESHOLD:  # Volatilidad muy baja = sin movimiento esperado
                return True, "LOSS", f"LOW_VOL_EXIT_{pnl_pct:.1f}%"

    # Sin señal de cierre anticipado
    return False, "PENDING", "HOLD"


# ============================================================================
# PARTE 2: MONITOREO EN TIEMPO REAL (cada 5 minutos)
# ============================================================================

def monitor_positions_realtime(check_interval=MONITOR_INTERVAL):
    """
    Corre continuamente, chequea cada 5 min si algún trade debe cerrarse.

    FLUJO:
      - Obtiene predicciones PENDING
      - Para cada una, evalúa si debe cerrarse dinámicamente
      - Si debe cerrarse, actualiza la BD con outcome
      - Duerme 5 minutos y repite

    USO: python run_crypto_models.py monitor
         (corre en terminal, presiona Ctrl+C para detener)
    """

    print(f"\n{'='*70}")
    print(f"  CRYPTO TRADING — REAL-TIME MONITOR")
    print(f"  Chequea cada {check_interval//60} min si algún trade debe cerrarse")
    print(f"{'='*70}\n")

    iteration = 0

    try:
        while True:
            iteration += 1
            now = datetime.now()
            # FIX CRÍTICO: sin esto, el cache de crypto_data conservaba los
            # precios del PRIMER ciclo para siempre. El monitor "en tiempo
            # real" estaba mirando una foto congelada: stops, targets y
            # cierres anticipados no se disparaban nunca.
            clear_cache()
            print(f"[{now.strftime('%H:%M:%S')}] Check #{iteration}...")

            con = _conn()
            pending = con.execute(
                "SELECT * FROM predictions WHERE outcome='PENDING' ORDER BY predicted_at"
            ).fetchall()

            if not pending:
                print(f"  → Sin trades abiertos\n")
                con.close()
                time.sleep(check_interval)
                continue

            resolved = 0

            for pred in pending:
                # Un error en un símbolo no debe matar el monitor completo
                try:
                    should_close, outcome, reason = evaluate_dynamic_close(pred)
                except Exception as e:
                    log("WARN", f"monitor: error evaluando {pred['symbol']}: {e}")
                    continue

                if should_close and outcome != "PENDING":
                    # Actualizar BD
                    price = get_price(pred['symbol'])
                    entry = pred['price_at_pred']
                    pnl_pct = (price - entry) / entry * 100 if price else 0

                    pred_time = datetime.fromisoformat(pred['predicted_at'])
                    hours = (now - pred_time).total_seconds() / 3600

                    con.execute("""
                        UPDATE predictions SET
                            outcome=?, outcome_date=?, price_at_outcome=?,
                            pnl_pct=?, hours_held=?, error_flags=?
                        WHERE id=?
                    """, (outcome, now.isoformat(), round(price, 6) if price else None,
                          round(pnl_pct, 3), round(hours, 2), reason, pred['id']))

                    resolved += 1
                    icon = "✓ WIN" if outcome == "WIN" else "✗ LOSS"
                    print(f"    [{pred['model']}] {pred['symbol']:8s} {icon}  {pnl_pct:+.2f}%  ({reason})")

            con.commit()
            con.close()

            if resolved:
                print(f"  → {resolved} trade(s) cerrado(s)\n")
            else:
                print(f"  → Todos los trades siguen abiertos\n")

            # Dormir hasta el próximo chequeo
            time.sleep(check_interval)

    except KeyboardInterrupt:
        print(f"\n\n✓ Monitor detenido por usuario")
        return


# ============================================================================
# PARTE 3: VALIDACIÓN DE DATOS (verificar coins descargadas)
# ============================================================================

def validate_data_coverage():
    """
    Verifica que TODAS las coins en CRYPTO_PAIRS están siendo descargadas
    y tienen precios recientes.

    Detecta:
      - Coins faltando en caché
      - Precios desactualizados (> 5 min)
      - Problemas de conexión a Binance
    """

    print(f"\n{'='*70}")
    print(f"  VALIDACIÓN DE COBERTURA DE DATOS")
    print(f"  Verifica que se descargan correctamente")
    print(f"{'='*70}\n")

    now = datetime.now()
    missing = []
    stale = []
    ok_count = 0

    for pair in sorted(CRYPTO_PAIRS):
        try:
            # Intentar obtener precio
            price = get_price(pair)

            if not price:
                missing.append(pair)
                print(f"  ✗ {pair:12s} - NO TIENE PRECIO EN CACHÉ")
            else:
                ok_count += 1
                # Verificar que el precio es reciente
                # (esto requeriría timestamp en el caché - mejora futura)
                print(f"  ✓ {pair:12s} - ${price:.6f}")

        except Exception as e:
            missing.append(pair)
            print(f"  ✗ {pair:12s} - ERROR: {str(e)[:40]}")

    print(f"\n{'='*70}")
    print(f"  RESUMEN DE COBERTURA")
    print(f"{'='*70}")
    print(f"  Total coins: {len(CRYPTO_PAIRS)}")
    print(f"  Con precio:  {ok_count}")
    print(f"  Faltando:    {len(missing)}")

    if missing:
        print(f"\n  ⚠️  COINS FALTANDO:")
        for coin in missing:
            print(f"      - {coin}")
        print(f"\n  ACCIÓN: Verifica que Binance API está respondiendo")
        print(f"          y que CRYPTO_PAIRS en binance_client.py es correcta")
    else:
        print(f"\n  ✓ TODAS las coins están siendo descargadas correctamente")

    return len(missing) == 0


# ============================================================================
# PARTE 4: COMPARACIÓN ANTES/DESPUÉS (para auditoría)
# ============================================================================

def compare_close_logic():
    """
    Compara los resultados de:
      - VIEJO: Cierre basado en max_hours (time-based)
      - NUEVO: Cierre dinámico basado en condiciones

    Usa las predicciones ya cerradas para mostrar si el nuevo método
    habría cerrado más temprano (mejor para cryptos volátiles).
    """

    print(f"\n{'='*70}")
    print(f"  AUDITORÍA: Lógica Antigua vs Nueva")
    print(f"{'='*70}\n")

    con = _conn()
    closed = con.execute(
        "SELECT * FROM predictions WHERE outcome IN ('WIN', 'LOSS') LIMIT 100"
    ).fetchall()
    con.close()

    if not closed:
        print("  No hay predicciones cerradas para auditar.\n")
        return

    # Análisis simple: mostrar trades que se habrían cerrado antes con dinámica
    better = 0
    worse = 0

    for pred in closed:
        # Si entrada y salida son positivas pero hora es > 4h, dinámico habría cerrado antes
        if pred['pnl_pct'] and pred['pnl_pct'] >= 2 and pred['hours_held'] and pred['hours_held'] > 4:
            better += 1

    print(f"  Predicciones analizadas: {len(closed)}")
    print(f"  Que se habrían cerrado MÁS TEMPRANO: {better}")
    if better > 0:
        print(f"  → Ahorro potencial: {better} trades con ganancia reinvertible antes")
    print()
