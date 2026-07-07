"""
Trade Monitor — recolecta snapshots cada 5 minutos por trade activo.

Por cada snapshot graba:
  - P&L actual, MFE/MAE acumulados
  - Velocity (cambio vs anterior) y aceleracion
  - Intervalos consecutivos bajando
  - Decision de reglas: HOLD o EXIT + razon

Funciones principales:
  record_snapshot(pred_id, price)   -> dict con estado actual del trade
  update_optimal_exit(pred_id)      -> marca el mejor momento de salida post-cierre
  get_snapshots(pred_id)            -> lista de snapshots de un trade
  summary(pred_id)                  -> imprime evolucion del trade
"""
import sqlite3, os, sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from bot.logger import log

DB_PATH = os.environ.get(
    "CRYPTO_DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "state", "crypto_predictions.db"),
)


def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row

    con.execute("""
        CREATE TABLE IF NOT EXISTS trade_snapshots (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            prediction_id     INTEGER NOT NULL,
            snapshot_time     TEXT    NOT NULL,
            elapsed_h         REAL    NOT NULL,
            price             REAL    NOT NULL,
            pnl_pct           REAL    NOT NULL,
            mfe_so_far        REAL    NOT NULL DEFAULT 0,
            mae_so_far        REAL    NOT NULL DEFAULT 0,
            pnl_velocity      REAL,
            pnl_accel         REAL,
            consecutive_down  INTEGER DEFAULT 0,
            time_positive_cnt INTEGER DEFAULT 0,
            exit_decision     TEXT    DEFAULT 'HOLD',
            exit_reason       TEXT
        )
    """)

    # Tabla de monitoreo post-cierre (30 min despues de cerrar)
    con.execute("""
        CREATE TABLE IF NOT EXISTS post_close_snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            prediction_id   INTEGER NOT NULL,
            snapshot_time   TEXT    NOT NULL,
            minutes_after   REAL    NOT NULL,
            price           REAL    NOT NULL,
            pnl_vs_entry    REAL    NOT NULL,
            pnl_vs_close    REAL    NOT NULL
        )
    """)

    # Columnas nuevas en predictions (migracion)
    for col_def in [
        "mfe_pct REAL",
        "mae_pct REAL",
        "mfe_time_h REAL",
        "mae_time_h REAL",
        "optimal_exit_h REAL",
        "optimal_exit_pnl REAL",
        "post_close_pnl REAL",
        "exit_quality TEXT",
    ]:
        try:
            con.execute(f"ALTER TABLE predictions ADD COLUMN {col_def}")
            con.commit()
        except Exception:
            pass

    con.commit()
    return con


# ── Snapshot ──────────────────────────────────────────────────────────

def record_snapshot(pred_id: int, price: float) -> dict:
    """
    Graba un snapshot del trade en curso.
    Calcula velocity, aceleracion, MFE/MAE acumulados y aplica reglas.
    Retorna dict con estado actual del trade.
    """
    con = _conn()

    pred = con.execute("SELECT * FROM predictions WHERE id=?", (pred_id,)).fetchone()
    if not pred:
        con.close()
        return {}

    entry     = pred["price_at_pred"]
    max_hours = pred["max_hours"] or 4.0
    pred_time = datetime.fromisoformat(pred["predicted_at"])
    now       = datetime.now()
    elapsed_h = (now - pred_time).total_seconds() / 3600
    pnl_pct   = round((price - entry) / entry * 100, 4)

    # Snapshots previos para derivadas
    prev_snaps = con.execute(
        "SELECT * FROM trade_snapshots WHERE prediction_id=? ORDER BY elapsed_h DESC LIMIT 2",
        (pred_id,),
    ).fetchall()

    # MFE / MAE acumulados
    if prev_snaps:
        mfe_so_far = max(prev_snaps[0]["mfe_so_far"], pnl_pct)
        mae_so_far = min(prev_snaps[0]["mae_so_far"], pnl_pct)
    else:
        mfe_so_far = max(0.0, pnl_pct)
        mae_so_far = min(0.0, pnl_pct)

    # Velocity y aceleracion
    pnl_velocity     = None
    pnl_accel        = None
    consecutive_down = 0
    time_positive_cnt = 0

    if prev_snaps:
        pnl_velocity = round(pnl_pct - prev_snaps[0]["pnl_pct"], 4)

        if len(prev_snaps) >= 2 and prev_snaps[0]["pnl_velocity"] is not None:
            pnl_accel = round(pnl_velocity - prev_snaps[0]["pnl_velocity"], 4)

        prev_down = prev_snaps[0]["consecutive_down"] or 0
        consecutive_down = (prev_down + 1) if pnl_velocity < 0 else 0

        time_positive_cnt = (prev_snaps[0]["time_positive_cnt"] or 0) + (1 if pnl_pct > 0 else 0)
    else:
        time_positive_cnt = 1 if pnl_pct > 0 else 0

    # Evaluacion de reglas (R1-R5 base + R6-R8 nuevas)
    decision, reason = _evaluate_rules(
        pnl_pct, pnl_velocity, pnl_accel, mfe_so_far, mae_so_far,
        consecutive_down, elapsed_h, max_hours,
        pred["target_price"], entry,
        symbol=pred["symbol"],
    )

    # ── NIVELES DUROS (FIX CRÍTICO) ──────────────────────────────────
    # Las reglas R1-R8 NUNCA miraban stop_price ni target_price:
    #   - un dump temprano atravesaba el stop sin cerrar (R1 exigia
    #     pnl < -1.8% Y time_ratio > 0.3 — en la primera fase del trade
    #     no habia NINGUN freno de perdidas)
    #   - al tocar target, H1/H2 devolvian HOLD y la ganancia solo se
    #     cobraba tras devolver 70% del pico (R3)
    # El stop y el target del plan de trade SIEMPRE mandan sobre las reglas.
    stop_price   = pred["stop_price"]
    target_price = pred["target_price"]
    if stop_price and price <= stop_price:
        decision, reason = "EXIT", "STOP_HIT_HARD"
    elif target_price and price >= target_price:
        decision, reason = "EXIT", "TARGET_HIT"

    cur = con.execute("""
        INSERT INTO trade_snapshots
          (prediction_id, snapshot_time, elapsed_h, price, pnl_pct,
           mfe_so_far, mae_so_far, pnl_velocity, pnl_accel,
           consecutive_down, time_positive_cnt, exit_decision, exit_reason)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        pred_id, now.isoformat(), round(elapsed_h, 4), round(price, 6), pnl_pct,
        round(mfe_so_far, 4), round(mae_so_far, 4), pnl_velocity, pnl_accel,
        consecutive_down, time_positive_cnt, decision, reason,
    ))
    snap_id = cur.lastrowid

    # Actualizar MFE/MAE en predictions si superan al registro anterior
    if pred["mfe_pct"] is None or mfe_so_far > (pred["mfe_pct"] or 0):
        con.execute(
            "UPDATE predictions SET mfe_pct=?, mfe_time_h=? WHERE id=?",
            (round(mfe_so_far, 4), round(elapsed_h, 4), pred_id),
        )
    if pred["mae_pct"] is None or mae_so_far < (pred["mae_pct"] or 0):
        con.execute(
            "UPDATE predictions SET mae_pct=?, mae_time_h=? WHERE id=?",
            (round(mae_so_far, 4), round(elapsed_h, 4), pred_id),
        )

    con.commit()
    con.close()

    log(
        "DEBUG",
        f"Snap #{snap_id} pred={pred_id} t={elapsed_h:.2f}h "
        f"pnl={pnl_pct:+.3f}% mfe={mfe_so_far:+.3f}% mae={mae_so_far:+.3f}% "
        f"vel={pnl_velocity} cd={consecutive_down} -> {decision}({reason})",
    )

    return {
        "snap_id":          snap_id,
        "elapsed_h":        elapsed_h,
        "pnl_pct":          pnl_pct,
        "mfe_so_far":       mfe_so_far,
        "mae_so_far":       mae_so_far,
        "pnl_velocity":     pnl_velocity,
        "pnl_accel":        pnl_accel,
        "consecutive_down": consecutive_down,
        "time_positive_cnt": time_positive_cnt,
        "decision":         decision,
        "reason":           reason,
    }


# ── Logica de reglas HOLD / EXIT ──────────────────────────────────────

def _evaluate_rules(
    pnl_pct, velocity, accel, mfe, mae,
    consec_down, elapsed_h, max_hours,
    target_price, entry_price,
    symbol: str = None,
) -> tuple:
    """
    Decide HOLD o EXIT basado en reglas.

    FILOSOFIA: dejar correr winners hasta el target (+3%).
    Solo cerrar cuando hay señal CLARA de crash o perdida confirmada.
    Un trade positivo NUNCA se cierra por reglas menores.

    Overrides de retencion (se evaluan primero):
      H1: precio casi en target (>95%) -> dejar llegar
      H2: P&L positivo -> aguantar, no cerrar por volatilidad normal

    Salidas defensivas (alta prioridad — protegen capital):
      R6: noticia bearish o sentiment SPIKE BEAR durante el trade -> EXIT
      R7: cambio de regimen macro (evento CRITICAL inminente) -> EXIT
      R8: timeout de sesion forzado; o 2x max_hours con P&L negativo

    Señales de salida tecnicas (umbrales altos — evitar salir temprano):
      R1: perdida > 1.8% pasado el 30% del tiempo (cerca del stop real -2.5%)
      R2: 10+ intervalos consecutivos bajando Y perdida > 0.5%
      R3: MFE fue > 2.0% y precio retrocedio >70% del MFE
      R4: a 70% del tiempo con perdida > 1.0% (trade muerto)
      R5: caida muy acelerada (velocity < -0.4 Y accel < -0.2) Y perdida > 0.5%
    """
    time_ratio = elapsed_h / max_hours if max_hours > 0 else 1.0

    # ── R8: timeout obligatorio por sesion 12h ─────────────────────
    # Si la sesion esta en FORCE_CLOSE o no hay margen, salir ya
    try:
        from bot.session_manager import SessionManager
        sm = SessionManager.current()
        if sm is not None and sm.must_force_close():
            return "EXIT", "R8_SESSION_FORCE_CLOSE"
    except Exception:
        pass
    # Timeout de trade: solo cerrar si estamos en perdida o muy pasados del limite
    if elapsed_h >= max_hours:
        if pnl_pct < 0:
            return "EXIT", "R8_TRADE_TIMEOUT"          # perdiendo -> cerrar
        elif elapsed_h >= max_hours * 2.0:
            return "EXIT", "R8_TRADE_TIMEOUT_EXTENDED"  # 2x el tiempo -> cerrar igualsi positivo
        # else: positivo al timeout -> NO cerrar, dejar correr hasta target

    # ── R7: cambio de regimen macro CRITICAL inminente ─────────────
    try:
        from bot.macro_events import get_active_regime_modifier
        regime = get_active_regime_modifier()
        if regime == "BLACKOUT":
            if pnl_pct >= 0:
                return "EXIT", "R7_REGIME_BLACKOUT_TAKE_PROFIT"
            return "EXIT", "R7_REGIME_BLACKOUT_CUT_LOSS"
    except Exception:
        pass

    # ── R6: noticia bearish o sentiment SPIKE BEAR ─────────────────
    if symbol:
        try:
            from bot.sentiment import get_sentiment
            sent = get_sentiment(symbol)
            score = sent.get("score", 0.0)
            spike = sent.get("spike", False)
            overall = sent.get("overall", "NEUTRAL")
            if spike and score < -0.2:
                if pnl_pct > 0:
                    return "EXIT", "R6_NEWS_SPIKE_BEAR_PROTECT_GAIN"
                return "EXIT", "R6_NEWS_SPIKE_BEAR_CUT_LOSS"
            if overall == "BEARISH" and score <= -0.4:
                return "EXIT", "R6_NEWS_BEARISH"
        except Exception:
            pass  # sentiment no disponible -> ignorar R6, no penalizar

    # H1: cerca del target, no interrumpir
    if target_price and entry_price and entry_price > 0:
        target_pct = (target_price - entry_price) / entry_price * 100
        if target_pct > 0 and pnl_pct >= target_pct * 0.95:
            return "HOLD", "H1_NEAR_TARGET"

    # H2: P&L positivo -> mantener SIEMPRE salvo crash claro
    # Un ganador no se cierra por volatilidad normal ni por tiempo
    if pnl_pct > 0:
        # R3 para ganadores: solo proteger si MFE fue muy alto y caemos mucho
        if mfe > 2.0 and pnl_pct < mfe * 0.3:
            return "EXIT", "R3_PEAK_REVERSION"
        # R5 para ganadores: solo si hay crash muy claro desde ganancia pequeña
        if (velocity is not None and velocity < -0.6
                and accel is not None and accel < -0.3
                and pnl_pct < 0.5):
            return "EXIT", "R5_CRASH_FROM_GAIN"
        return "HOLD", "H2_POSITIVE_PNL_HOLD"

    # ─── Desde aqui solo entramos si pnl_pct <= 0 ──────────────────

    # R1: perdida profunda (cerca del stop real -2.5%)
    if pnl_pct < -1.8 and time_ratio > 0.3:
        return "EXIT", "R1_DEEP_LOSS"

    # R2: momentum bajista sostenido Y en perdida significativa
    if consec_down >= 10 and pnl_pct < -0.5:
        return "EXIT", "R2_CONSEC_DOWN"

    # R3: retroceso desde pico significativo (solo si MFE fue relevante)
    if mfe > 2.0 and pnl_pct < mfe * 0.3:
        return "EXIT", "R3_PEAK_REVERSION"

    # R4: trade muerto avanzado en tiempo Y perdida moderada
    if time_ratio >= 0.7 and pnl_pct < -1.0:
        return "EXIT", "R4_MIDPOINT_NEG"

    # R5: caida acelerada clara en perdida
    if (
        velocity is not None and velocity < -0.4
        and accel is not None and accel < -0.2
        and pnl_pct < -0.5
    ):
        return "EXIT", "R5_ACCEL_DOWN"

    return "HOLD", "NO_EXIT_SIGNAL"


# ── Post-cierre ───────────────────────────────────────────────────────

def update_optimal_exit(pred_id: int):
    """
    Llamar despues de que un trade cierra.
    Busca el snapshot con mejor pnl_pct y lo registra como salida optima.
    Sirve para etiquetar el dataset de entrenamiento del modelo ML.
    """
    con = _conn()
    pred = con.execute("SELECT * FROM predictions WHERE id=?", (pred_id,)).fetchone()
    if not pred:
        con.close()
        return

    snaps = con.execute(
        "SELECT * FROM trade_snapshots WHERE prediction_id=? ORDER BY elapsed_h",
        (pred_id,),
    ).fetchall()

    if not snaps:
        con.close()
        return

    best = max(snaps, key=lambda s: s["pnl_pct"])
    con.execute(
        "UPDATE predictions SET optimal_exit_h=?, optimal_exit_pnl=? WHERE id=?",
        (round(best["elapsed_h"], 4), round(best["pnl_pct"], 4), pred_id),
    )
    con.commit()
    con.close()

    final_pnl = pred["pnl_pct"] or 0
    gain = best["pnl_pct"] - final_pnl
    log(
        "DEBUG",
        f"optimal_exit #{pred_id}: mejor snapshot @ {best['elapsed_h']:.2f}h "
        f"({best['pnl_pct']:+.3f}% vs cierre {final_pnl:+.3f}%, "
        f"ganancia_no_cobrada={gain:+.3f}%)",
    )


# ── Consultas ─────────────────────────────────────────────────────────

def get_snapshots(pred_id: int) -> list:
    """Retorna todos los snapshots de un trade ordenados por tiempo."""
    con = _conn()
    rows = con.execute(
        "SELECT * FROM trade_snapshots WHERE prediction_id=? ORDER BY elapsed_h",
        (pred_id,),
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


# -- Post-close monitoring --

POST_CLOSE_MINUTES = 30   # cuanto tiempo monitorear despues del cierre
POST_CLOSE_POLL    = 5    # cada cuantos minutos tomar snapshot


def record_post_close_snapshot(pred_id: int, price: float) -> dict | None:
    """
    Graba un snapshot post-cierre.
    Compara precio actual vs precio de entrada Y vs precio de cierre.
    Retorna dict con datos o None si el trade no existe.
    """
    con = _conn()
    pred = con.execute("SELECT * FROM predictions WHERE id=?", (pred_id,)).fetchone()
    if not pred or pred["outcome"] not in ("WIN", "LOSS"):
        con.close()
        return None

    entry       = pred["price_at_pred"]
    close_price = pred["price_at_outcome"] or entry
    close_time  = datetime.fromisoformat(pred["outcome_date"])
    now         = datetime.now()
    mins_after  = (now - close_time).total_seconds() / 60

    pnl_vs_entry = round((price - entry) / entry * 100, 4)
    pnl_vs_close = round((price - close_price) / close_price * 100, 4)

    con.execute("""
        INSERT INTO post_close_snapshots
          (prediction_id, snapshot_time, minutes_after, price, pnl_vs_entry, pnl_vs_close)
        VALUES (?,?,?,?,?,?)
    """, (pred_id, now.isoformat(), round(mins_after, 2),
          round(price, 6), pnl_vs_entry, pnl_vs_close))
    con.commit()
    con.close()

    return {
        "minutes_after": mins_after,
        "price": price,
        "pnl_vs_entry": pnl_vs_entry,
        "pnl_vs_close": pnl_vs_close,
    }



def finalize_post_close(pred_id: int) -> str | None:
    """
    Despues de POST_CLOSE_MINUTES, clasifica la calidad del cierre.
    GOOD_EXIT:  precio bajo >0.3% despues de cerrar (salimos bien)
    BAD_EXIT:   precio subio >0.3% despues de cerrar (salimos temprano)
    NEUTRAL:    cambio < 0.3%
    """
    con = _conn()
    snaps = con.execute(
        "SELECT * FROM post_close_snapshots WHERE prediction_id=? ORDER BY minutes_after DESC",
        (pred_id,),
    ).fetchall()

    if not snaps:
        con.close()
        return None

    # Usar el ultimo snapshot como referencia
    last = snaps[0]
    pnl_vs_close = last["pnl_vs_close"]

    # Tambien calcular el max/min post-cierre
    max_post = max(s["pnl_vs_close"] for s in snaps)
    min_post = min(s["pnl_vs_close"] for s in snaps)

    THRESHOLD = 0.3  # 0.3% para considerar significativo

    if pnl_vs_close <= -THRESHOLD:
        quality = "GOOD_EXIT"    # precio bajo — salimos a tiempo
    elif pnl_vs_close >= THRESHOLD:
        quality = "BAD_EXIT"     # precio subio — salimos temprano
    else:
        quality = "NEUTRAL"

    con.execute("""
        UPDATE predictions
        SET exit_quality = ?, post_close_pnl = ?
        WHERE id = ?
    """, (quality, round(pnl_vs_close, 4), pred_id))
    con.commit()
    con.close()

    log("INFO", f"post-close #{pred_id}: {quality} (pnl_vs_close={pnl_vs_close:+.3f}%, max={max_post:+.3f}%, min={min_post:+.3f}%)")
    return quality


def get_post_close_stats() -> dict:
    """Estadisticas agregadas de calidad de salida."""
    con = _conn()
    rows = con.execute(
        "SELECT exit_quality, post_close_pnl FROM predictions WHERE exit_quality IS NOT NULL"
    ).fetchall()
    con.close()

    if not rows:
        return {"total": 0, "good": 0, "bad": 0, "neutral": 0, "avg_post_pnl": None}

    good    = sum(1 for r in rows if r["exit_quality"] == "GOOD_EXIT")
    bad     = sum(1 for r in rows if r["exit_quality"] == "BAD_EXIT")
    neutral = sum(1 for r in rows if r["exit_quality"] == "NEUTRAL")
    avg_pnl = sum(r["post_close_pnl"] or 0 for r in rows) / len(rows)

    return {
        "total":        len(rows),
        "good":         good,
        "bad":          bad,
        "neutral":      neutral,
        "avg_post_pnl": round(avg_pnl, 4),
    }


def summary(pred_id: int):
    """Imprime resumen completo de un trade, incluyendo snapshots y post-cierre."""
    con = _conn()
    pred = con.execute("SELECT * FROM predictions WHERE id=?", (pred_id,)).fetchone()
    if not pred:
        print(f"  Trade #{pred_id} no encontrado.")
        con.close()
        return

    pred = dict(pred)  # sqlite3.Row no tiene .get()

    print(f"\n  === TRADE #{pred_id} ===")
    print(f"  Symbol:  {pred['symbol']}")
    print(f"  Model:   {pred.get('model', '?')}")
    print(f"  Entry:   ${pred['price_at_pred']:.6f}")
    print(f"  Target:  ${pred.get('target_price', 0) or 0:.6f}")
    print(f"  Stop:    ${pred.get('stop_price', 0) or 0:.6f}")
    print(f"  Outcome: {pred['outcome']}")
    if pred["pnl_pct"] is not None:
        print(f"  P&L:     {pred['pnl_pct']:+.3f}%")
    if pred.get("hours_held") is not None:
        print(f"  Hold:    {pred['hours_held']:.2f}h")
    if pred.get("mfe_pct") is not None:
        print(f"  MFE:     {pred['mfe_pct']:+.3f}%  |  MAE: {pred.get('mae_pct', 0):+.3f}%")
    if pred.get("error_flags"):
        print(f"  Flags:   {pred['error_flags']}")
    if pred.get("exit_quality"):
        print(f"  Exit Q:  {pred['exit_quality']}  (post-close P&L: {pred.get('post_close_pnl', 0):+.3f}%)")

    # Snapshots activos
    snaps = con.execute(
        "SELECT * FROM trade_snapshots WHERE prediction_id=? ORDER BY elapsed_h",
        (pred_id,),
    ).fetchall()
    if snaps:
        print(f"\n  Snapshots ({len(snaps)}):")
        print(f"    {'Hora':>6}  {'P&L':>8}  {'Vel':>7}  {'MFE':>7}  {'MAE':>7}")
        for s in snaps:
            print(f"    {s['elapsed_h']:>5.2f}h  {s['pnl_pct']:>+7.3f}%  {(s['pnl_velocity'] or 0):>+6.3f}  {(s['mfe_so_far'] or 0):>+6.3f}  {(s['mae_so_far'] or 0):>+6.3f}")

    # Snapshots post-cierre
    post_snaps = con.execute(
        "SELECT * FROM post_close_snapshots WHERE prediction_id=? ORDER BY minutes_after",
        (pred_id,),
    ).fetchall()
    if post_snaps:
        print(f"\n  Post-cierre ({len(post_snaps)} snapshots):")
        print(f"    {'Min':>5}  {'Precio':>12}  {'vs Entry':>9}  {'vs Close':>9}")
        for ps in post_snaps:
            print(f"    {ps['minutes_after']:>4.0f}m  {ps['price']:>12.6f}  {ps['pnl_vs_entry']:>+8.3f}%  {ps['pnl_vs_close']:>+8.3f}%")

    con.close()
