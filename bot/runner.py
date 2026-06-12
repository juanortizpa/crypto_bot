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


def _carry_over_enabled() -> bool:
    """
    Modo 24/7 (forever): al terminar la sesion NO se fuerza el cierre de
    posiciones — quedan PENDING y la siguiente sesion las retoma (el monitor
    lee todas las PENDING de la DB, y check_outcomes() reconstruye con velas
    de 5m cualquier stop/target tocado durante el hueco entre sesiones).
    """
    return os.environ.get("CRYPTO_CARRY_OVER", "").lower() in ("1", "true", "yes")


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
    con.row_factory = sqlite3.Row
    pred = con.execute("SELECT * FROM predictions WHERE id=?", (pred_id,)).fetchone()
    if not pred:
        return None
    entry = pred["price_at_pred"]
    pnl_pct = (current_price - entry) / entry * 100 if entry else 0.0
    # WIN solo si cubre comisiones; zona +-FEE_RT_PCT es breakeven (BE)
    from bot.predictions import FEE_RT_PCT
    if pnl_pct > FEE_RT_PCT:
        outcome = "WIN"
    elif pnl_pct < -FEE_RT_PCT:
        outcome = "LOSS"
    else:
        outcome = "BE"
    now = datetime.now()
    try:
        pred_time = datetime.fromisoformat(pred["predicted_at"])
        hours_held = round((now - pred_time).total_seconds() / 3600, 4)
    except Exception:
        hours_held = None
    con.execute("""
        UPDATE predictions
        SET outcome=?, price_at_outcome=?, pnl_pct=?, outcome_date=?, error_flags=?, hours_held=?
        WHERE id=?
    """, (outcome, current_price, round(pnl_pct, 4),
          now.isoformat(), f"CLOSED_BY_RUNNER:{reason}", hours_held, pred_id))
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
    from bot.crypto_data import get_price, clear_cache
    from bot.trade_monitor import record_snapshot, DB_PATH

    # FIX CRÍTICO: el cache de crypto_data solo lo limpiaba scan() (cada 5 min
    # y SOLO si la sesion permite abrir trades). En FREEZE o con risk guard
    # tripped, el monitor corria con precios congelados del ultimo scan —
    # exactamente cuando mas importa cerrar bien. Limpiar SIEMPRE aqui.
    clear_cache()

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
    # WIN solo si cubre comisiones; zona +-FEE_RT_PCT es breakeven (BE)
    from bot.predictions import FEE_RT_PCT
    if pnl_pct > FEE_RT_PCT:
        outcome = "WIN"
    elif pnl_pct < -FEE_RT_PCT:
        outcome = "LOSS"
    else:
        outcome = "BE"
    now = datetime.now()
    try:
        pred_time = datetime.fromisoformat(row["predicted_at"])
        hours_held = round((now - pred_time).total_seconds() / 3600, 4)
    except Exception:
        hours_held = None
    con.execute("""
        UPDATE predictions
        SET outcome=?, price_at_outcome=?, pnl_pct=?, outcome_date=?, error_flags=?, hours_held=?
        WHERE id=?
    """, (outcome, current_price, round(pnl_pct, 4),
          now.isoformat(), f"CLOSED_BY_RUNNER:{reason}", hours_held, pid))
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


def _run_scan_cycle(session_start_iso: str = None):
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
        # Cargar simbolos ya operados en esta sesion (evita reentradas)
        _ssi = session_start_iso  # recibido como parametro
        session_syms = set(row[0] for row in open_con.execute(
            "SELECT DISTINCT symbol FROM predictions WHERE outcome IN ('WIN','LOSS') AND predicted_at >= ?",
            (_ssi,)
        ).fetchall()) if _ssi else set()
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

            # GUARD 1b: no reentrar al mismo par si ya se opero en esta sesion
            if sym in session_syms:
                log("INFO", f"  {sym}: ya operado en esta sesion — skip reentrada")
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

            # GUARD 3: prediccion ML (XGB + RF + HYBRID ensemble).
            # IMPORTANTE: el ensemble fue entrenado SOLO para dips (Modelo D),
            # asi que aqui unicamente se CALCULA su opinion. La accion de bloquear
            # o degradar tamano se aplica mas abajo, despues de elegir modelo, y
            # SOLO cuando el modelo elegido es D (ver "Gate ML consciente del modelo").
            # Para B/E/F/A/C el ML es informativo: no debe vetar momentum/breakout.
            ml_decision = None
            ml_result = None
            if ML_AVAILABLE and ml_predict is not None:
                try:
                    ml_result = ml_predict(sym)
                    ml_decision = ml_result.get("decision")
                    log("INFO", f"  {sym}: ML={ml_decision} ({ml_result.get('votes','?')})")

                    # UNKNOWN: fallo en computar features. Reintento 1 vez.
                    if ml_decision == "UNKNOWN":
                        log("INFO", f"  {sym}: ML UNKNOWN, retry...")
                        time.sleep(2)
                        ml_result = ml_predict(sym)
                        ml_decision = ml_result.get("decision")
                        log("INFO", f"  {sym}: ML retry={ml_decision} ({ml_result.get('votes','?')})")
                except Exception as e:
                    log("WARN", f"  {sym}: error en ML predict: {e}")
                    ml_decision = None
                    ml_result = None

            try:
                tech = technical_score(sym)
                price_now = tech.get("price")
                # ── Selección por MEJOR modelo (no por orden fijo) ───────────────
                # 1) Reunir TODOS los modelos que califican para este símbolo.
                # 2) Puntuar cada uno por expectativa esperada:
                #       EV = P(WIN)*target_pct - (1-P(WIN))*stop_pct
                #    donde P(WIN) viene del meta-modelo (predict_entry) que sabe
                #    distinguir por model_id, y target/stop son los del propio modelo.
                # 3) Ejecutar con el de mayor EV. Así el sistema elige el modelo
                #    con el que el trade funcionaría mejor, en vez de quedarse
                #    siempre con D por ser el primero del loop.
                from bot.meta_model import predict_entry
                candidates = []  # (model_id, stop, target, p_win, ev)
                for mid in ("A", "B", "C", "D", "E", "F"):
                    califica, stop, target = evaluate_model(mid, gate, tech)
                    if not califica:
                        continue
                    # P(WIN) del meta-modelo para ESTE modelo. Fallback neutro 0.5.
                    p_win = 0.5
                    try:
                        _dec, _p = predict_entry(gate, mid, symbol=sym)
                        if _dec != "NO_MODEL" and _p:
                            p_win = _p
                    except Exception:
                        pass
                    # Expectativa ponderada por el R:R real del modelo.
                    if price_now:
                        target_pct = max(target / price_now - 1.0, 0.0)
                        stop_pct = max(1.0 - stop / price_now, 0.0)
                    else:
                        target_pct = MODELS[mid].get("target_pct", 0.03)
                        stop_pct = MODELS[mid].get("stop_pct", 0.02)
                    ev = p_win * target_pct - (1.0 - p_win) * stop_pct
                    candidates.append((mid, stop, target, p_win, ev))

                if not candidates:
                    log("INFO", f"  {sym}: ningun modelo califico")
                    continue

                # Elegir el de mayor EV; desempate por mayor P(WIN).
                candidates.sort(key=lambda c: (c[4], c[3]), reverse=True)
                chosen_model, chosen_stop, chosen_target, chosen_pwin, chosen_ev = candidates[0]
                if len(candidates) > 1:
                    ranking = ", ".join(
                        f"{m}(p={pw:.2f},ev={e:+.4f})" for m, _s, _t, pw, e in candidates)
                    log("INFO", f"  {sym}: modelos que califican -> {ranking}")
                log("INFO",
                    f"  {sym}: elegido modelo {chosen_model} "
                    f"(P(WIN)={chosen_pwin:.2f}, EV={chosen_ev:+.4f})")

                # ── Gate ML CONSCIENTE DEL MODELO ────────────────────────────────
                # El ensemble ML fue entrenado para DIPS (Modelo D): da probabilidades
                # bajas en momentum/breakout y vetaria ganadores de B/E/F. Por eso su
                # veto SOLO aplica cuando el modelo elegido es D. Para el resto el ML
                # es informativo: se loguea y audita, pero NO bloquea ni degrada.
                _allow_unknown = os.environ.get(
                    "CRYPTO_ALLOW_ML_UNKNOWN", "").lower() in ("1", "true", "yes")
                if chosen_model == "D":
                    if ml_decision == "UNKNOWN" and not _allow_unknown:
                        log("INFO", f"  {sym}: [D] ML UNKNOWN -> skip (capital protegido)")
                        continue
                    if ml_decision == "ABORT":
                        if r["decision"] == "EXECUTE_FULL":
                            r["decision"] = "EXECUTE_HALF"
                            log("INFO", f"  {sym}: [D] ML ABORT + gate FULL -> HALF (advisory)")
                        else:
                            log("INFO", f"  {sym}: [D] ML ABORT + gate HALF -> skip")
                            try:
                                from bot.ml_audit import record_decision
                                from bot.crypto_data import get_price
                                record_decision(sym, r["decision"], r["green"],
                                                ml_result, get_price(sym) or 0)
                            except Exception:
                                pass
                            continue
                    elif ml_decision == "WATCH" and r["decision"] == "EXECUTE_FULL":
                        r["decision"] = "EXECUTE_HALF"
                        log("INFO", f"  {sym}: [D] ML WATCH -> HALF")
                    elif ml_decision == "HALF" and r["decision"] == "EXECUTE_FULL":
                        r["decision"] = "EXECUTE_HALF"
                        log("INFO", f"  {sym}: [D] ML HALF (mayoria) -> HALF")
                elif ml_decision and ml_decision != "UNKNOWN":
                    log("INFO",
                        f"  {sym}: [{chosen_model}] ML={ml_decision} informativo "
                        f"(no veta momentum/breakout)")

                # Comprobar que el trade cabe en lo que queda de sesion.
                # En modo carry-over (24/7) los trades sobreviven el fin de
                # sesion, asi que no aplica este limite.
                model_max_h = MODELS[chosen_model].get("max_hours", 4)
                if not _carry_over_enabled():
                    if sm is not None and not sm.can_fit_trade(model_max_h):
                        log("INFO",
                            f"  {sym}: trade ({model_max_h}h) excede tiempo restante de sesion")
                        continue
                    # Minimo 30 minutos restantes para abrir cualquier trade
                    if sm is not None and sm.remaining_hours() < 0.5:
                        log("INFO", f"  {sym}: menos de 30min restantes — no abrir nuevos trades")
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


def _compute_simulated_balance(initial_balance: float, since_iso: str = None) -> float:
    """
    Calcula el balance simulado en dry-run sumando el P&L de trades cerrados
    DENTRO DE LA SESION ACTUAL (desde since_iso).
    Asume position_size = 5% del capital inicial por trade (sizing HALF conservador).
    """
    try:
        from bot.trade_monitor import DB_PATH
        con = sqlite3.connect(DB_PATH)
        if since_iso:
            rows = con.execute(
                "SELECT pnl_pct FROM predictions "
                "WHERE outcome IN ('WIN','LOSS') AND pnl_pct IS NOT NULL "
                "AND outcome_date >= ?",
                (since_iso,)
            ).fetchall()
        else:
            # Sin filtro de sesion: contar TODOS los trades historicos
            rows = con.execute(
                "SELECT pnl_pct FROM predictions "
                "WHERE outcome IN ('WIN','LOSS') AND pnl_pct IS NOT NULL"
            ).fetchall()
        con.close()

        POSITION_PCT = 0.05  # 5% del capital por trade
        sim_balance = initial_balance
        for r in rows:
            pnl = r[0] if isinstance(r, tuple) else r["pnl_pct"]
            sim_balance += initial_balance * POSITION_PCT * (pnl / 100.0)
        return round(max(sim_balance, 0.0), 2)
    except Exception:
        return initial_balance


def _refresh_risk_balance(initial_balance: float, dry_run: bool, session_start_iso: str = None, since_iso: str = None):
    """Actualiza el risk guard con el balance actual (real o simulado)."""
    if not initial_balance or initial_balance <= 0:
        return  # Sin capital base valido, no actualizar (evita DRAWDOWN_100%)
    try:
        effective_since = since_iso if since_iso is not None else session_start_iso
        if dry_run:
            bal = _compute_simulated_balance(initial_balance, since_iso=effective_since)
        else:
            from bot.capital_profile import _get_usdt_balance
            bal = _get_usdt_balance()
            if not bal or bal <= 0:
                bal = _compute_simulated_balance(initial_balance, since_iso=effective_since)
        if bal and bal > 0:
            update_balance(bal)
    except Exception:
        pass


def run(max_hours: float = None, dry_run: bool = None):
    """Loop principal con cap de 12h."""
    if max_hours is None:
        max_hours = float(os.environ.get("CRYPTO_SESSION_HOURS", "12.0"))
    if dry_run is None:
        dry_run = DRY_RUN

    sm = SessionManager.start(max_hours=max_hours)
    print(sm.report())

    # Inicializar risk_guard con el balance actual
    # Binance testnet suele devolver 0 USDT — fallback al estado guardado o .env
    try:
        from bot.capital_profile import _get_usdt_balance
        balance = _get_usdt_balance()
    except Exception:
        balance = 0.0

    if not balance or balance <= 0:
        # Sin balance real: usar initial_capital del estado guardado
        try:
            from bot.risk_guard import _load_state as _rg_load
            _saved = _rg_load()
            balance = (_saved.get("initial_capital") or
                       _saved.get("current_balance") or 0.0)
        except Exception:
            balance = 0.0
        if not balance or balance <= 0:
            balance = float(os.environ.get("CRYPTO_PORTFOLIO", "480"))

    init_session(balance)
    # Recalcular balance real sumando TODOS los trades historicos cerrados
    _refresh_risk_balance(balance, dry_run, since_iso=None)
    print(risk_report())

    if is_tripped():
        log("ERROR", "Risk guard activo: %s. Reset manual requerido." % trip_reason())
        return

    # Timestamp de inicio de sesion para filtrar P&L simulado (solo trades nuevos)
    session_start_iso = datetime.now().isoformat()
    last_scan_at = 0.0

    carry_over = _carry_over_enabled()

    while sm.should_continue():
        now_ts = time.time()
        st = sm.state()
        log("INFO", "  [LOOP] state=%s elapsed=%.2fh remaining=%.2fh" % (
            st, sm.elapsed_hours(), sm.remaining_hours()))

        # Heartbeat para vigilancia externa (health / watchdog 24-7)
        try:
            from bot.heartbeat import beat
            beat("SESSION_" + st,
                 elapsed_h=round(sm.elapsed_hours(), 2),
                 remaining_h=round(sm.remaining_hours(), 2),
                 dry_run=bool(dry_run))
        except Exception:
            pass

        # FORCE_CLOSE -> cerrar todo y salir (o entregar a la proxima sesion)
        if sm.must_force_close():
            if carry_over:
                log("INFO", "  Fin de sesion (carry-over): las posiciones "
                            "abiertas quedan PENDING para la proxima sesion")
                _monitor_open_positions(force_close_all=False)
                break
            log("WARN", "  Sesion en FORCE_CLOSE — cerrando todas las posiciones")
            _monitor_open_positions(force_close_all=True)
            break

        # Risk guard tripped -> solo monitorear (no abrir nuevas)
        if is_tripped():
            log("WARN", "  Risk guard tripped (%s) — solo monitor" % trip_reason())
            _monitor_open_positions(force_close_all=False)
            _refresh_risk_balance(balance, dry_run, since_iso=None)
            sm.sleep(MONITOR_INTERVAL_SEC)
            continue

        # Monitor de posiciones siempre
        _monitor_open_positions(force_close_all=False)

        # Actualizar balance en risk guard (todos los trades acumulados)
        _refresh_risk_balance(balance, dry_run, since_iso=None)

        # Scan solo en estado OPEN y cada SCAN_INTERVAL_SEC
        if sm.can_open_new_trades() and (now_ts - last_scan_at) >= SCAN_INTERVAL_SEC:
            _run_scan_cycle(session_start_iso)
            last_scan_at = now_ts
        elif not sm.can_open_new_trades():
            log("INFO", "  Estado %s - no se abren nuevas entradas" % st)

        sm.sleep(MONITOR_INTERVAL_SEC)

    # Fin de sesion
    log("INFO", "  Sesion terminada. Estado final:")
    print(sm.report())
    print(risk_report())


if __name__ == "__main__":
    args = sys.argv[1:]
    hours = None
    dry = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--hours" and i + 1 < len(args):
            hours = float(args[i + 1])
            i += 2
        elif a == "--dry-run":
            dry = True
            i += 1
        elif a == "--live":
            dry = False
            i += 1
        else:
            i += 1
    run(max_hours=hours, dry_run=dry)
