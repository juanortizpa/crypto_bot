"""
Prediction Engine para Crypto — con trailing stop y tiempos variables.

LOGICA DE SALIDA (por prioridad):
  1. Precio toca STOP -> LOSS inmediato
  2. Precio toca TARGET -> WIN inmediato
  3. A mitad del tiempo, si P&L >= +1% -> stop sube a BREAKEVEN
  4. Al final del tiempo max:
     - Si P&L > 0 -> WIN (salio en positivo)
     - Si P&L <= 0 -> LOSS (no logro moverse)

TIEMPOS POR MODELO:
  B (Momentum):  2h  -- impulso rapido
  A (Scalp):     4h  -- scalp medio
  C (News):      4h  -- noticias duran 2-4h
  E (Breakout):  6h  -- confirmacion de ruptura
  D (Dip):       8h  -- rebotes de panico tardan
  F (Trend):    12h  -- montar la tendencia

TRAILING STOP:
  Cuando el trade va ganando +1% o mas despues del X% del tiempo,
  el stop se mueve a breakeven (precio de entrada). Ya no puedes perder.
"""
import sqlite3, os, sys, json
from datetime import date, datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from bot.crypto_gate import run_gate, GREEN, YELLOW, RED
from bot.crypto_data import technical_score, get_price, clear_cache
from bot.position_sizing import calculate_position, format_quantity, format_usd
from bot.logger import log

DB_PATH = os.environ.get("CRYPTO_DB_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "state", "crypto_predictions.db"))

# Ventana maxima de deduplicacion (el modelo mas largo: Trend Rider 12h)
MAX_HOURS = 12

# Trailing: si P&L >= este %, mover stop a breakeven
TRAIL_TRIGGER_PCT = 1.0


# -- Schema --

def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            model           TEXT    DEFAULT 'A',
            symbol          TEXT    NOT NULL,
            predicted_at    TEXT    NOT NULL,
            price_at_pred   REAL    NOT NULL,
            gate_score      INTEGER NOT NULL,
            decision        TEXT    NOT NULL,
            factors_json    TEXT    NOT NULL,
            stop_price      REAL,
            target_price    REAL,
            rr_ratio        REAL,
            max_hours       REAL    DEFAULT 4,
            outcome         TEXT    DEFAULT 'PENDING',
            outcome_date    TEXT,
            price_at_outcome REAL,
            pnl_pct         REAL,
            r_multiple      REAL,
            hours_held      REAL,
            error_flags     TEXT
        )
    """)
    # Migraciones
    for col_def in [
        "outcome_date TEXT",
        "price_at_outcome REAL",
        "pnl_pct REAL",
        "r_multiple REAL",
        "max_hours REAL DEFAULT 4",
        "hours_held REAL",
        "quantity REAL",
        "position_usd REAL",
        "risk_usd REAL",
        "pnl_usd REAL",
        "error_flags TEXT",
    ]:
        try:
            con.execute(f"ALTER TABLE predictions ADD COLUMN {col_def}")
            con.commit()
        except Exception:
            pass
    con.commit()
    return con


# -- Record a prediction --

def predict(symbol, verbose=True, model="A", stop_price=None, target_price=None,
            gate=None, tech=None, max_hours=None):
    """Guarda prediccion con stop, target y tiempo max del modelo.
    max_hours: override opcional (None = usar el valor del modelo).
    """
    from bot.crypto_models import MODELS

    symbol = symbol.upper()
    if gate is None or tech is None:
        clear_cache()
        gate = run_gate(symbol)
        tech = technical_score(symbol)

    price = tech.get("price")
    if not price:
        log("WARN", f"predict({symbol}): sin precio")
        return None

    model_info = MODELS.get(model, {})
    if max_hours is None:
        max_hours = model_info.get("max_hours", 4)

    if stop_price is None or target_price is None:
        stop_pct   = model_info.get("stop_pct", 0.02)
        target_pct = model_info.get("target_pct", 0.03)
        stop_price   = round(price * (1 - stop_pct), 6)
        target_price = round(price * (1 + target_pct), 6)

    risk = price - stop_price
    rr   = round((target_price - price) / risk, 2) if risk > 0 else 0

    factors_json = json.dumps({k: v["color"] for k, v in gate.factors.items()})

    # Guardar sin sizing — se asigna despues con asignar_capital()
    con = _conn()
    cur = con.execute("""
        INSERT INTO predictions
          (model, symbol, predicted_at, price_at_pred, gate_score, decision,
           factors_json, stop_price, target_price, rr_ratio, max_hours)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        model,
        symbol,
        datetime.now().isoformat(),
        round(price, 6),
        gate.green_count,
        gate.decision,
        factors_json,
        stop_price,
        target_price,
        rr,
        max_hours,
    ))
    pred_id = cur.lastrowid
    con.commit()
    con.close()

    stop_pct_display   = round((1 - stop_price / price) * 100, 2)
    target_pct_display = round((target_price / price - 1) * 100, 2)

    if verbose:
        print(gate.report())
        print(f"  PREDICCION #{pred_id} [Modelo {model}] GUARDADA")
        print(f"  Par:       {symbol}  |  Precio: ${price:.6f}")
        print(f"  Gate:      {gate.green_count}/{len(gate.factors)}")
        print(f"  Stop:      ${stop_price:.6f} (-{stop_pct_display}%)")
        print(f"  Target:    ${target_price:.6f} (+{target_pct_display}%)")
        print(f"  R/R:       {rr:.1f}:1  |  Max: {max_hours}h  |  Trail: +{TRAIL_TRIGGER_PCT}%->BE")
        print(f"  Resultado: PENDIENTE (sizing pendiente)\n")

    log("INFO", f"Pred #{pred_id} [{model}]: {symbol} @ ${price:.6f} (sizing pendiente)")
    return pred_id


# -- Check and resolve outcomes --

def check_outcomes(force_close=False):
    """
    Evalua predicciones PENDING con logica de trailing stop.
    Prioridad: stop hit > target hit > trailing BE > time expired

    force_close=True: cierra TODAS las pendientes al precio actual,
                      sin importar si ya paso el tiempo max.
                      Usado al vencer cada ronda en los tests de 1h.
    """
    from bot.crypto_models import MODELS

    con = _conn()
    # Fix legacy NULL outcomes → PENDING
    con.execute("UPDATE predictions SET outcome = 'PENDING' WHERE outcome IS NULL")
    con.commit()
    pending = con.execute(
        "SELECT * FROM predictions WHERE outcome = 'PENDING'"
    ).fetchall()

    if not pending:
        print("  Sin predicciones pendientes.")
        log("INFO", "check_outcomes: no pending predictions")
        con.close()
        return

    resolved = 0
    trailed  = 0
    now = datetime.now()

    for row in pending:
        sym       = row["symbol"]
        entry     = row["price_at_pred"]
        stop      = row["stop_price"]  or entry * 0.98
        target    = row["target_price"] or entry * 1.03
        model_id  = row["model"] or "A"
        max_hours = row["max_hours"] or MODELS.get(model_id, {}).get("max_hours", 4)
        trail_pct = MODELS.get(model_id, {}).get("trail_after", 0.5)

        pred_time = datetime.fromisoformat(row["predicted_at"])
        hours_elapsed = (now - pred_time).total_seconds() / 3600
        time_ratio = hours_elapsed / max_hours if max_hours > 0 else 1.0

        price = get_price(sym)
        if not price:
            continue

        pnl_pct  = round((price - entry) / entry * 100, 3)
        risk     = entry - stop
        r_mult   = round((price - entry) / risk, 2) if risk > 0 else 0
        outcome  = "PENDING"
        flags    = []

        # TRAILING STOP: mover stop a breakeven
        effective_stop = stop
        if time_ratio >= trail_pct and pnl_pct >= TRAIL_TRIGGER_PCT:
            effective_stop = entry
            flags.append("TRAILING_BE")
            trailed += 1

        # RESOLUCION
        if price <= effective_stop:
            if effective_stop == entry:
                outcome = "WIN"
                flags.append("BREAKEVEN")
            else:
                outcome = "LOSS"
                flags.append("STOP_HIT")
        elif price >= target:
            outcome = "WIN"
            flags.append("TARGET_HIT")
        elif hours_elapsed >= max_hours or force_close:
            outcome = "WIN" if pnl_pct > 0 else "LOSS"
            flags.append(f"EXPIRED_{max_hours:.0f}H" if not force_close else "FORCE_CLOSE")

        if outcome != "PENDING":
            # Calcular P&L en dolares
            qty = row["quantity"] or 0
            pnl_usd = round(qty * (price - entry), 2) if qty else None

            con.execute("""
                UPDATE predictions SET
                  outcome=?, outcome_date=?, price_at_outcome=?,
                  pnl_pct=?, pnl_usd=?, r_multiple=?, hours_held=?, error_flags=?
                WHERE id=?
            """, (outcome, now.isoformat(), round(price, 6),
                  pnl_pct, pnl_usd, r_mult, round(hours_elapsed, 2),
                  ",".join(flags), row["id"]))
            resolved += 1
            icon = "WIN" if outcome == "WIN" else "LOSS"
            usd_str = f" {format_usd(pnl_usd)}" if pnl_usd is not None else ""
            log("INFO", f"Pred #{row['id']} {sym} [{model_id}]: {icon} {pnl_pct:+.3f}%{usd_str} en {hours_elapsed:.1f}h ({','.join(flags)})")

    con.commit()
    con.close()

    still_pending = len(pending) - resolved
    print(f"  Resueltas: {resolved} | Trailing activo: {trailed} | Pendientes: {still_pending}")
    if resolved:
        log("INFO", f"check_outcomes: resolved {resolved}, trailed {trailed}")


# -- Accuracy report --

def accuracy_report():
    """Breakdown completo con analisis de trailing stop."""
    from bot.crypto_models import MODELS
    con  = _conn()
    all_rows  = con.execute("SELECT * FROM predictions").fetchall()
    closed    = [r for r in all_rows if r["outcome"] in ("WIN", "LOSS")]
    pending   = [r for r in all_rows if r["outcome"] == "PENDING"]
    con.close()

    sep = "=" * 62
    print(f"\n{sep}")
    print(f"  CRYPTO SCALPING -- ACCURACY REPORT")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{sep}")
    print(f"  Total predicciones: {len(all_rows)}")
    print(f"  Cerradas:           {len(closed)}")
    print(f"  Pendientes:         {len(pending)}")

    if not closed:
        print("  No hay predicciones cerradas aun.\n")
        return

    wins   = [r for r in closed if r["outcome"] == "WIN"]
    losses = [r for r in closed if r["outcome"] == "LOSS"]
    wr     = len(wins) / len(closed) * 100

    avg_win  = sum(r["pnl_pct"] for r in wins)  / len(wins)  if wins   else 0
    avg_loss = sum(r["pnl_pct"] for r in losses) / len(losses) if losses else 0
    exp      = (wr/100) * avg_win + (1 - wr/100) * avg_loss
    avg_hours = sum(r["hours_held"] or 0 for r in closed) / len(closed)

    print(f"\n  Win Rate:       {wr:.1f}%")
    print(f"  Wins: {len(wins)}   Losses: {len(losses)}")
    print(f"  Avg Win:        +{avg_win:.3f}%")
    print(f"  Avg Loss:       {avg_loss:.3f}%")
    print(f"  Expectancy:     {exp:+.3f}% por trade")
    print(f"  Avg Hold Time:  {avg_hours:.1f}h")

    print(f"\n  POR TIPO DE CIERRE:")
    flag_types = ["TARGET_HIT", "STOP_HIT", "BREAKEVEN", "TRAILING_BE"]
    for r in closed:
        for f in (r["error_flags"] or "").split(","):
            if f.startswith("EXPIRED_") and f not in flag_types:
                flag_types.append(f)

    for flag in flag_types:
        sub = [r for r in closed if flag in (r["error_flags"] or "")]
        if sub:
            sw = [r for r in sub if r["outcome"] == "WIN"]
            wr_s = len(sw) / len(sub) * 100 if sub else 0
            ap = sum(r["pnl_pct"] for r in sub) / len(sub)
            avg_h = sum(r["hours_held"] or 0 for r in sub) / len(sub)
            print(f"  {flag:<16} {len(sub):>4} trades  {wr_s:.0f}% WR  avg {ap:+.3f}%  ~{avg_h:.1f}h")

    print(f"\n{sep}\n")


# -- Comparacion entre modelos --

def compare_models():
    """Tabla comparativa con tiempos variables por modelo."""
    from bot.crypto_models import MODELS
    con      = _conn()
    all_rows = con.execute("SELECT * FROM predictions").fetchall()
    con.close()

    closed  = [r for r in all_rows if r["outcome"] in ("WIN", "LOSS")]
    pending = [r for r in all_rows if r["outcome"] == "PENDING"]

    sep = "=" * 78
    print(f"\n{sep}")
    print(f"  COMPARACION DE MODELOS -- TIEMPOS VARIABLES + TRAILING STOP")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}   |   Total: {len(all_rows)}  |  Pendientes: {len(pending)}")
    print(f"{sep}")
    print(f"  {'Mdl':<4} {'Nombre':<20} {'MaxH':>4} {'Trades':>6} {'Win':>4} {'Loss':>4} {'WR%':>7} {'Exp':>8} {'AvgH':>5}  St")
    print(f"  {'-'*76}")

    ganador_exp = -999
    ganador_mod = None

    for mid, minfo in MODELS.items():
        sub       = [r for r in closed if (r["model"] or "A") == mid]
        pending_m = [r for r in pending if (r["model"] or "A") == mid]
        total_m   = len(sub) + len(pending_m)
        max_h     = minfo.get("max_hours", 4)

        if not sub:
            print(f"  [{mid}]  {minfo['name']:<20} {max_h:>3}h {total_m:>6} {'--':>4} {'--':>4} {'--':>7} {'--':>8} {'--':>5}  ...")
            continue

        wins   = [r for r in sub if r["outcome"] == "WIN"]
        losses = [r for r in sub if r["outcome"] == "LOSS"]
        wr     = len(wins) / len(sub) * 100
        avg_p  = sum(r["pnl_pct"] for r in sub) / len(sub)
        avg_h  = sum(r["hours_held"] or 0 for r in sub) / len(sub)

        icon = "[OK]" if wr >= 60 else "[!!]" if wr >= 45 else "[ X]"
        print(f"  [{mid}]  {minfo['name']:<20} {max_h:>3}h {total_m:>6} {len(wins):>4} {len(losses):>4} "
              f"{wr:>6.1f}% {avg_p:>+7.3f}% {avg_h:>4.1f}h  {icon}")

        if avg_p > ganador_exp:
            ganador_exp = avg_p
            ganador_mod = mid

    print(f"{sep}")
    if ganador_mod and ganador_exp > -999:
        m = MODELS[ganador_mod]
        print(f"  LIDER: Modelo {ganador_mod} -- {m['name']} (max {m['max_hours']}h)")
        print(f"  {m['description']}")
        sub_lider = [r for r in closed if (r["model"] or "A") == ganador_mod]
        if len(sub_lider) >= 15:
            wr_l = sum(1 for r in sub_lider if r["outcome"] == "WIN") / len(sub_lider) * 100
            if wr_l >= 55 and ganador_exp > 0:
                print(f"  >>> CANDIDATO PARA AUTO_EXECUTE = True ({len(sub_lider)} trades, {wr_l:.0f}% WR) <<<")
            else:
                print(f"  Necesita WR >= 55% Y expectancy > 0 para auto-execute.")
        else:
            print(f"  Necesita >= 15 trades para evaluar. Tiene {len(sub_lider)}.")
    else:
        print(f"  Acumulando datos...")
    print(f"{sep}\n")


# -- Pending summary --

def pending_summary():
    """Muestra predicciones pendientes con P&L actual y estado trailing."""
    from bot.crypto_models import MODELS
    con  = _conn()
    rows = con.execute(
        "SELECT * FROM predictions WHERE outcome='PENDING' OR outcome IS NULL ORDER BY model, predicted_at DESC"
    ).fetchall()
    con.close()

    if not rows:
        print("\n  Sin predicciones pendientes.\n")
        return

    now = datetime.now()
    print(f"\n  PREDICCIONES PENDIENTES ({len(rows)})")
    print(f"  {'#':<4} {'Mdl':<4} {'Par':<10} {'Hora':<6} {'Precio':>10} {'P&L':>7} {'Stop':>10} {'Target':>10} {'Queda':>6} {'Trail':>6}")
    print(f"  {'-'*80}")

    for r in rows:
        pred_time = datetime.fromisoformat(r["predicted_at"])
        elapsed   = (now - pred_time).total_seconds() / 3600
        model_id  = r["model"] or "A"
        max_h     = r["max_hours"] or MODELS.get(model_id, {}).get("max_hours", 4)
        trail_pct = MODELS.get(model_id, {}).get("trail_after", 0.5)
        remaining = max(0, max_h - elapsed)

        current_price = get_price(r["symbol"])
        if current_price:
            pnl = (current_price - r["price_at_pred"]) / r["price_at_pred"] * 100
            pnl_s = f"{pnl:+.2f}%"
            time_ratio = elapsed / max_h if max_h > 0 else 1
            trailing = "BE" if (time_ratio >= trail_pct and pnl >= TRAIL_TRIGGER_PCT) else "--"
        else:
            pnl_s = "?"
            trailing = "--"

        hora = pred_time.strftime("%H:%M")
        quedan = f"{remaining:.1f}h" if remaining > 0 else "EXP!"
        print(f"  {r['id']:<4} [{model_id}]  {r['symbol']:<10} {hora:<6} "
              f"${r['price_at_pred']:>9.4f} {pnl_s:>7} "
              f"${r['stop_price']:>9.4f} ${r['target_price']:>9.4f} {quedan:>6} {trailing:>6}")
    print()
