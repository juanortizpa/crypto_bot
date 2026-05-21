"""
Runner principal del bot — loop con cap de 12 horas.

Flujo del loop (cada SCAN_INTERVAL_SEC segundos):
  1. Verificar estado de sesion (OPEN / FREEZE / FORCE_CLOSE / EXPIRED).
  2. Si FORCE_CLOSE → cerrar todas las posiciones abiertas y terminar.
  3. Si EXPIRED → terminar.
  4. Monitorear posiciones abiertas: para cada una graba snapshot y decide
     HOLD o EXIT segun trade_monitor.
  5. Si estado == OPEN y no esta tripped el risk_guard:
       a. Escanea pares -> evalua gate.
       b. Filtra candidatos cuyo max_hours quepa en la sesion.
       c. Calcula sizing con hard caps.
       d. Ejecuta entradas (o las marca segun DRY_RUN).

Uso:
    python bot_crypto.py run                  # corre la sesion de 12h
    python bot_crypto.py run --hours 6        # sesion corta de 6h
    python bot_crypto.py run --dry-run        # no ejecuta ordenes reales

Variables de entorno relevantes:
    CRYPTO_SESSION_HOURS=12      duracion de la sesion
    CRYPTO_FREEZE_HOURS=2        cuanto antes del fin se prohiben nuevas entradas
    CRYPTO_FORCE_CLOSE_MIN=15    minutos antes del fin para cierre forzoso
    CRYPTO_DRY_RUN=true          no ejecutar ordenes en Binance, solo simular
    CRYPTO_SCAN_INTERVAL_SEC=300 segundos entre ciclos completos
    CRYPTO_MONITOR_INTERVAL_SEC=60 segundos entre snapshots de posiciones
"""
import os
import sys
import time
import sqlite3
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from bot.session_manager import SessionManager
from bot.risk_guard import init_session, is_tripped, trip_reason, update_balance, report as risk_report
from bot.logger import log

SCAN_INTERVAL_SEC = int(os.environ.get("CRYPTO_SCAN_INTERVAL_SEC", "300"))      # 5 min
MONITOR_INTERVAL_SEC = int(os.environ.get("CRYPTO_MONITOR_INTERVAL_SEC", "60")) # 1 min
DRY_RUN = os.environ.get("CRYPTO_DRY_RUN", "true").lower() in ("1", "true", "yes")


def _get_open_predictions(con):
    """Predicciones con outcome PENDING (trades activos)."""
    return con.execute(
        "SELECT id, symbol, price_at_pred, stop_price, target_price, "
        "max_hours, predicted_at FROM predictions WHERE outcome='PENDING'"
    ).fetchall()


def _close_position(con, pred_id: int, reason: str, current_price: float):
    """
    Marca una prediccion como cerrada al precio actual.
    Si DRY_RUN, solo actualiza la DB; si no, deberia integrarse con binance_client
    para ejecutar la venta real (queda como TODO si quieres trading real).
    """
    pred = con.execute("SELECT * FROM predictions WHERE id=?", (pred_id,)).fetchone()
    if not pred:
        return None
    entry = pred[2]  # price_at_pred (asume tupla por position; usar dict factory si row_factory=Row)
    pnl_pct = (current_price - entry) / entry * 100 if entry else 0.0
    outcome = "WIN" if pnl_pct > 0 else "LOSS"
    con.execute("""
        UPDATE predictions
        SET outcome=?, price_at_outcome=?, pnl_pct=?, outcome_date=?, error_flags=?
        WHERE id=?
    """, (outcome, current_price, round(pnl_pct, 4),
          datetime.now().isoformat(), f"CLOSED_BY_RUNNER:{reason}", pred_id))
    con.commit()
    log("INFO", f"  [CLOSE] pred={pred_id} reason={reason} pnl={pnl_pct:+.3f}%")
    # actualizar trailing post-cierre, risk_guard outcome
    try:
        from bot.trade_monitor import update_optimal_exit
        update_optimal_exit(pred_id)
    except Exception:
        pass
    try:
        from bot.risk_guard import register_trade_outcome
        register_trade_outcome(pnl_pct)
    except Exception:
        pass
    return pnl_pct


def _monitor_open_positions(force_close_all: bool = False):
    """Itera todas las posiciones abiertas, graba snapshot, evalua salida."""
    from bot.crypto_data import get_price
    from bot.trade_monitor import record_snapshot, DB_PATH

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM predictions WHERE outcome='PENDING'"
    ).fetchall()
    if not rows:
        con.close()
        return

    log("INFO", f"  Monitorando {len(rows)} posiciones abiertas...")
    for row in rows:
        pid = row["id"]
        sym = row["symbol"]
        try:
            price = get_price(sym)
            if not price:
                log("WARN", f"    Sin precio para {sym} pred={pid}")
                continue
            if force_close_all:
                _close_position_row(con, row, "FORCE_CLOSE_SESSION_END", price)
                continue
            snap = record_snapshot(pid, price)
            decision = snap.get("decision", "HOLD")
            reason = snap.get("reason", "")
            if decision == "EXIT":
                _close_position_row(con, row, reason, price)
        except Exception as e:
            log("WARN", f"    Error monitor pred={pid} {sym}: {e}")
    con.close()


def _close_position_row(con, row, reason: str, current_price: float):
    """Version con Row factory (dict-like)."""
    pid = row["id"]
    entry = row["price_at_pred"]
    pnl_pct = (current_price - entry) / entry * 100 if entry else 0.0
    outcome = "WIN" if pnl_pct > 0 else "LOSS"
    con.execute("""
        UPDATE predictions
        SET outcome=?, price_at_outcome=?, pnl_pct=?, outcome_date=?, error_flags=?
        WHERE id=?
    """, (outcome, current_price, round(pnl_pct, 4),
          datetime.now().isoformat(), f"CLOSED_BY_RUNNER:{reason}", pid))
    con.commit()
    log("INFO", f"  [CLOSE] pred={pid} sym={row['symbol']} reason={reason} pnl={pnl_pct:+.3f}%")
    try:
        from bot.trade_monitor import update_optimal_exit
        update_optimal_exit(pid)
    except Exception:
        pass
    try:
        from bot.risk_guard import register_trade_outcome
        register_trade_outcome(pnl_pct)
    except Exception:
        pass


def _run_scan_cycle():
    """Un ciclo de scan + generacion de predicciones + sizing."""
    log("INFO", "  Ciclo de scan inicial...")
    try:
        from bot.crypto_scanner import scan, print_scan_report
        results = scan()
        if not results:
            log("INFO", "  Scan: sin candidatos")
            return
        print_scan_report(results)
        log("INFO", f"  Scan completo: {len(results)} candidatos")

        # Solo abrir trades nuevos si hay EXECUTE_FULL o EXECUTE_HALF
        actionable = [r for r in results
                      if r["decision"] in ("EXECUTE_FULL", "EXECUTE_HALF")]
        if not actionable:
            log("INFO", "  Sin candidatos accionables (todos WATCH/ABORT)")
            return

        # Veto por session: si no podemos abrir trades nuevos, salir
        sm = SessionManager.current()
        if sm is not None and not sm.can_open_new_trades():
            log("INFO", f"  Sesion {sm.state()} — no abrimos nuevas entradas")
            return

        # Veto por risk_guard
        if is_tripped():
            log("WARN", f"  Risk guard tripped ({trip_reason()}) — sin nuevas entradas")
            return

        # Crear predicciones para los candidatos accionables
        from bot.predictions import predict
        from bot.crypto_models import evaluate_model, MODELS
        from bot.crypto_data import technical_score, get_bars
        from bot.position_sizing import asignar_capital
        from bot.trade_monitor import _conn as trade_conn

        # Cargar simbolos con posiciones abiertas para evitar duplicados
        open_con = trade_conn()
        open_syms = set(row[0] for row in open_con.execute(
            "SELECT DISTINCT symbol FROM predictions WHERE outcome='PENDING'"
        ).fetchall())
        open_con.close()

        # Importar ml_inference (puede fallar si numpy no esta instalado)
        try:
            from bot.ml_inference import predict as ml_predict
            ML_AVAILABLE = True
        except Exception as e:
            log("WARN", f"  ml_inference no disponible: {e}. Operando solo con gate.")
            ml_predict = None
            ML_AVAILABLE = False

        # Si ML esta deshabilitado por env, lo respetamos
        if os.environ.get("CRYPTO_DISABLE_ML", "").lower() in ("1", "true", "yes"):
            ML_AVAILABLE = False
            log("INFO", "  ML deshabilitado por CRYPTO_DISABLE_ML")

        new_pred_ids = []
        for r in actionable[:5]:  # max 5 trades nuevos por ciclo
            sym = r["symbol"]
            gate = r["gate"]

            # GUARD 1: no abrir duplicado en el mismo simbolo
            if sym in open_syms:
                log("INFO", f"  {sym}: ya hay posicion abierta — skip duplicado")
                continue

            # GUARD 2: detectar precio congelado (data muerta / ticker delistado)
            # Si las ultimas 3 velas 1h tienen exactamente el mismo close,
            # el ticker no esta operando -> skip.
            try:
                stale_bars = get_bars(sym, "1h", 3)
                if stale_bars and len(stale_bars) >= 3:
                    closes = [b["c"] for b in stale_bars[-3:]]
                    if len(set(closes)) == 1:
                        log("WARN",
                            f"  {sym}: precio congelado ({closes[0]}) "
                            f"en ultimas 3h — ticker delistado o ilíquido, skip")
                        continue
            except Exception:
                pass

            # GUARD 3: validacion ML (XGB + RF + HYBRID ensemble)
            # Si los 3 modelos coinciden -> EXECUTE_FULL
            # Si mayoria (2/3) coincide  -> EXECUTE_HALF (degrada FULL si era FULL)
            # Si solo 1/3 coincide       -> degrada a HALF; si gate ya era HALF -> skip
            # Si ninguno coincide        -> skip (ABORT)
            ml_decision = None
            ml_result = None
            if ML_AVAILABLE and ml_predict is not None:
                try:
                    ml_result = ml_predict(sym)
                    ml_decision = ml_result.get("decision")
                    ml_votes = ml_result.get("votes", "?")
                    log("INFO", f"  {sym}: ML={ml_decision} ({ml_votes})")

                    # UNKNOWN: fallo en computar features (red, datos faltantes).
                    # Reintento 1 vez antes de rendirme.
                    if ml_decision == "UNKNOWN":
                        log("INFO", f"  {sym}: ML UNKNOWN, retry...")
                        time.sleep(2)
                        ml_result = ml_predict(sym)
                        ml_decision = ml_result.get("decision")
                        log("INFO", f"  {sym}: ML retry={ml_decision} ({ml_result.get('votes','?')})")

                    # Si sigue UNKNOWN, NO operar. Mejor perder un trade que
                    # operar sin la validacion ML que entrenamos.
                    # Override con env CRYPTO_ALLOW_ML_UNKNOWN=true si lo necesitas.
                    if ml_decision == "UNKNOWN":
                        if os.environ.get("CRYPTO_ALLOW_ML_UNKNOWN", "").lower() in ("1", "true", "yes"):
                            log("WARN", f"  {sym}: ML sigue UNKNOWN pero CRYPTO_ALLOW_ML_UNKNOWN=true, sigo")
                        else:
                            log("INFO", f"  {sym}: ML UNKNOWN, skip (capital protegido)")
                            continue

                    if ml_decision == "ABORT":
                        log("INFO", f"  {sym}: ML veto, skip")
                        # Registrar auditoria
                        try:
                            from bot.ml_audit import record_decision
                            from bot.crypto_data import get_price
                            price_now = get_price(sym) or 0
                            record_decision(sym, r["decision"], r["green"],
                                            ml_result, price_now)
                        except Exception:
                            pass
                        continue

                    if ml_decision == "WATCH" and r["decision"] == "EXECUTE_HALF":
                        log("INFO", f"  {sym}: ML solo 1/3 + gate HALF -> skip")
                        try:
                            from bot.ml_audit import record_decision
                            from bot.crypto_data import get_price
                            price_now = get_price(sym) or 0
                            record_decision(sym, r["decision"], r["green"],
                                            ml_result, price_now)
                        except Exception:
                            pass
                        continue
                    if ml_decision == "WATCH" and r["decision"] == "EXECUTE_FULL":
                        r["decision"] = "EXECUTE_HALF"
                        log("INFO", f"  {sym}: degradado a HALF por ML")
                    if ml_decision == "HALF" and r["decision"] == "EXECUTE_FULL":
                        r["decision"] = "EXECUTE_HALF"
                        log("INFO", f"  {sym}: degradado a HALF (mayoria ML)")
                except Exception as e:
                    log("WARN", f"  {sym}: error en ML predict: {e}")
                    # mismo criterio: si no pudimos evaluar ML, skip
                    if os.environ.get("CRYPTO_ALLOW_ML_UNKNOWN", "").lower() not in ("1", "true", "yes"):
                        log("INFO", f"  {sym}: error ML -> skip")
                        continue

            try:
                tech = technical_score(sym)
                # Probar todos los modelos, elegir el primero que califica
                chosen_model = None
                chosen_stop = None
                chosen_target = None
                for mid in ("D", "A", "B", "F", "E", "C"):  # D primero (dip)
                    califica, stop, target = evaluate_model(mid, gate, tech)
                    if califica:
                        chosen_model = mid
                        chosen_stop = stop
                        chosen_target = target
                        break
                if not chosen_model:
                    log("INFO", f"  {sym}: ningun modelo califico")
                    continue

                # Comprobar que el trade cabe en lo que queda de sesion
                model_max_h = MODELS[chosen_model].get("max_hours", 4)
                if sm is not None and not sm.can_fit_trade(model_max_h):
                    log("INFO",
                        f"  {sym}: trade ({model_max_h}h) excede tiempo restante de sesion")
                    continue

                pid = predict(sym, verbose=False, model=chosen_model,
                              stop_price=chosen_stop, target_price=chosen_target,
                              gate=gate, tech=tech, max_hours=model_max_h)
                if pid:
                    ml_tag = f" ML={ml_decision}" if ml_decision else ""
                    log("INFO", f"  [NEW] pred={pid} sym={sym} model={chosen_model}"
                                f"{ml_tag} stop={chosen_stop} target={chosen_target}")
                    new_pred_ids.append(pid)
                    # Registrar auditoria con el pred_id linkeado
                    if ml_result is not None:
                        try:
                            from bot.ml_audit import record_decision
                            price_at = tech.get("price") or 0
                            stop_pct_use = abs((chosen_stop / price_at - 1) * 100) if price_at else 2.5
                            target_pct_use = abs((chosen_target / price_at - 1) * 100) if price_at else 4.0
                            record_decision(sym, r["decision"], r["green"],
                                            ml_result, price_at,
                                            stop_pct=stop_pct_use,
                                            target_pct=target_pct_use,
                                            max_hours=model_max_h,
                                            opened_pred_id=pid)
                        except Exception as e:
                            log("WARN", f"  ml_audit record fallo: {e}")
            except Exception as e:
                log("WARN", f"  Error creando prediccion {sym}: {e}")

        # Sizing batch para todas las predicciones nuevas
        if new_pred_ids:
            con = trade_conn()
            sized = asignar_capital(con, new_pred_ids)
            con.close()
            for s in sized:
                if s.get("skipped"):
                    log("WARN", f"  pred={s['id']} skipped: {s.get('skip_reason')}")
                else:
                    log("INFO",
                        f"  [SIZED] pred={s['id']} pos=${s['position_usd']} "
                        f"qty={s['quantity']} risk=${s['risk_usd']} ({s['risk_pct_portfolio']}%)")

    except Exception as e:
        import traceback
        log("WARN", f"  Error en scan: {e}")
        log("DEBUG", traceback.format_exc())


def run(max_hours: float = None, dry_run: bool = None):
    """Loop principal con cap de 12h."""
    if max_hours is None:
        max_hours = float(os.environ.get("CRYPTO_SESSION_HOURS", "12.0"))
    if dry_run is None:
        dry_run = DRY_RUN

    sm = SessionManager.start(max_hours=max_hours)
    print(sm.report())

    # Inicializar risk_guard con el balance actual
    try:
        from bot.capital_profile import _get_usdt_balance
        balance = _get_usdt_balance()
    except Exception:
        balance = float(os.environ.get("CRYPTO_PORTFOLIO", "500"))
    init_session(balance)
    print(risk_report())

    if is_tripped():
        log("ERROR", f"Risk guard activo: {trip_reason()}. Reset manual requerido.")
        return

    last_scan_at = 0.0

    while sm.should_continue():
        now_ts = time.time()
        st = sm.state()
        log("INFO", f"  [LOOP] state={st} elapsed={sm.elapsed_hours():.2f}h remaining={sm.remaining_hours():.2f}h")

        # FORCE_CLOSE -> cerrar todo y salir
        if sm.must_force_close():
            log("WARN", "  Sesion en FORCE_CLOSE — cerrando todas las posiciones")
            _monitor_open_positions(force_close_all=True)
            break

        # Risk guard tripped -> solo monitorear (no abrir nuevas)
        if is_tripped():
            log("WARN", f"  Risk guard tripped ({trip_reason()}) — solo monitor")
            _monitor_open_positions(force_close_all=False)
            sm.sleep(MONITOR_INTERVAL_SEC)
            continue

        # Monitor de posiciones siempre
        _monitor_open_positions(force_close_all=False)

        # Scan solo en estado OPEN y cada SCAN_INTERVAL_SEC
        if sm.can_open_new_trades() and (now_ts - last_scan_at) >= SCAN_INTERVAL_SEC:
            _run_scan_cycle()
            last_scan_at = now_ts
        elif not sm.can_open_new_trades():
            log("INFO", f"  Estado {st} — no se abren nuevas entradas")

        sm.sleep(MONITOR_INTERVAL_SEC)

    # Fin de sesion
    log("INFO", "  Sesion terminada. Estado final:")
    print(sm.report())
    print(risk_report())


if __name__ == "__main__":
    # parsing simple de args
    hours = None
    for i, a in enumerate(sys.argv):
        if a == "--hours" and i + 1 < len(sys.argv):
            hours = float(sys.argv[i + 1])
        elif a == "--dry-run":
            os.environ["CRYPTO_DRY_RUN"] = "true"
    run(max_hours=hours)
