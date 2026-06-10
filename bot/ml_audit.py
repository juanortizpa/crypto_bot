"""
ml_audit.py — Auditor retrospectivo de las decisiones del ML.

Para cada decisión del ensemble ML (FULL/HALF/WATCH/ABORT/UNKNOWN) se registra
el momento, el símbolo, el precio y las probabilidades de cada modelo. Más
tarde (típicamente 8h después, cuando el trade hipotético habría expirado),
el auditor revisa el precio real para responder:

  - Si el ML dijo ABORT/skip:
      ¿el precio bajó al stop antes que subir al target? -> ACERTO (te salvó de loss)
      ¿subió al target? -> ERROR (oportunidad perdida)
      ¿se quedó plano? -> NEUTRO (skip fue OK)

  - Si el ML dijo GO (FULL o HALF) y se abrió un trade:
      el outcome real ya está en `predictions`; el auditor sólo lo enlaza.

Tabla: state/ml_decisions.db  (no toca crypto_predictions.db).

Comandos:
  python bot_crypto.py ml-eval      Evalua decisiones pendientes (>= max_hours)
  python bot_crypto.py ml-report    Muestra métricas agregadas
"""

import os
import sys
import json
import sqlite3
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bot.logger import log

DB_PATH = os.path.join(ROOT, "state", "ml_decisions.db")


def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("""
        CREATE TABLE IF NOT EXISTS ml_decisions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            decided_at      TEXT NOT NULL,
            symbol          TEXT NOT NULL,
            gate_decision   TEXT,
            gate_green      INTEGER,
            ml_decision     TEXT,
            ml_votes        TEXT,
            xgb_prob        REAL,
            xgb_thr         REAL,
            xgb_go          INTEGER,
            rf_prob         REAL,
            rf_thr          REAL,
            rf_go           INTEGER,
            hybrid_prob     REAL,
            hybrid_thr      REAL,
            hybrid_go       INTEGER,
            price           REAL,
            stop_pct        REAL DEFAULT 2.5,
            target_pct      REAL DEFAULT 4.0,
            max_hours       REAL DEFAULT 8.0,
            opened_pred_id  INTEGER,
            evaluated_at    TEXT,
            eval_outcome    TEXT,
            eval_pnl_pct    REAL,
            eval_max_pnl    REAL,
            eval_min_pnl    REAL,
            eval_verdict    TEXT
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_mld_sym ON ml_decisions(symbol, decided_at)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_mld_pending ON ml_decisions(evaluated_at)")
    con.commit()
    return con


def record_decision(symbol, gate_decision, gate_green, ml_result, price,
                    stop_pct=2.5, target_pct=4.0, max_hours=8.0,
                    opened_pred_id=None):
    """
    Registra una decisión ML para auditoría posterior.

    ml_result: el dict que devuelve bot.ml_inference.predict()
    """
    details = ml_result.get("details", {})
    xgb = details.get("xgb", {})
    rf  = details.get("rf",  {})
    hyb = details.get("hybrid", {})

    con = _conn()
    con.execute("""
        INSERT INTO ml_decisions
        (decided_at, symbol, gate_decision, gate_green,
         ml_decision, ml_votes,
         xgb_prob, xgb_thr, xgb_go,
         rf_prob,  rf_thr,  rf_go,
         hybrid_prob, hybrid_thr, hybrid_go,
         price, stop_pct, target_pct, max_hours, opened_pred_id)
        VALUES (?,?,?,?,?,?, ?,?,?, ?,?,?, ?,?,?, ?,?,?,?,?)
    """, (
        datetime.now(timezone.utc).isoformat(),
        symbol, gate_decision, gate_green,
        ml_result.get("decision"), ml_result.get("votes"),
        xgb.get("prob"), xgb.get("threshold"), 1 if xgb.get("go") else 0,
        rf.get("prob"),  rf.get("threshold"),  1 if rf.get("go")  else 0,
        hyb.get("prob"), hyb.get("threshold"), 1 if hyb.get("go") else 0,
        price, stop_pct, target_pct, max_hours, opened_pred_id,
    ))
    con.commit()
    con.close()


# ── Evaluacion retrospectiva ───────────────────────────────────────────────

def _simulate_outcome(symbol, entry_price, entry_ts_ms, stop_pct, target_pct, max_hours):
    """
    Baja velas 1m desde entry_ts hasta entry_ts + max_hours y determina:
      - outcome: WIN si tocó target primero, LOSS si tocó stop, TIMEOUT si nada.
      - pnl_pct final, mfe (mejor ganancia), mae (peor pérdida)
    """
    try:
        from bot.ml_inference import _fetch_klines_paged
    except Exception:
        return None

    bars_needed = int(max_hours * 60)  # bars de 1 min
    # Bajamos ventana desde entry hasta entry + max_hours
    # _fetch_klines_paged baja las MÁS RECIENTES; usamos una function distinta
    # para rango específico. Pero como el ML auditing es post-evento,
    # las velas ya están en el pasado y _fetch_klines_paged sirve si traemos
    # más velas y luego filtramos. Sin embargo es ineficiente.
    # Solución simple: bajar velas con endTime = entry_ts + max_hours_ms
    import urllib.request, urllib.parse
    end_ms = entry_ts_ms + int(max_hours * 3600 * 1000) + 60000
    out = []
    cur_end = end_ms
    remaining = bars_needed + 2
    for _ in range(int((bars_needed / 1000) + 2)):
        if remaining <= 0:
            break
        batch = min(remaining, 1000)
        params = {"symbol": symbol, "interval": "1m", "limit": batch, "endTime": cur_end}
        url = "https://api.binance.com/api/v3/klines?" + urllib.parse.urlencode(params)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ml_audit/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = json.loads(resp.read())
        except Exception:
            return None
        if not raw:
            break
        chunk = [{
            "ts": int(b[0]), "o": float(b[1]), "h": float(b[2]),
            "l": float(b[3]), "c": float(b[4])
        } for b in raw]
        out = chunk + out
        remaining -= len(chunk)
        if len(chunk) < batch:
            break
        cur_end = chunk[0]["ts"] - 1

    # Filtrar solo las velas >= entry_ts
    bars = [b for b in out if b["ts"] >= entry_ts_ms]
    if not bars:
        return None

    # Guard contra entry_price <= 0 (tokens de muy baja decimales como SHIB
    # que el record_decision guardó truncado a 4 decimales como 0.0)
    if entry_price <= 0:
        # Usar el primer close real como entry_price (precio del momento del
        # decided_at no esta disponible, asi que aproximamos con la 1a vela)
        entry_price = bars[0]["c"]
        if entry_price <= 0:
            return None

    target_price = entry_price * (1 + target_pct / 100)
    stop_price   = entry_price * (1 - stop_pct / 100)

    mfe = 0.0
    mae = 0.0
    outcome = None
    last_price = entry_price

    for b in bars:
        last_price = b["c"]
        pnl_h = (b["h"] / entry_price - 1) * 100
        pnl_l = (b["l"] / entry_price - 1) * 100
        if pnl_h > mfe: mfe = pnl_h
        if pnl_l < mae: mae = pnl_l
        if b["h"] >= target_price and b["l"] <= stop_price:
            # Ambos: decidimos por cercanía al open
            if abs(b["o"] - target_price) <= abs(b["o"] - stop_price):
                outcome = ("WIN", target_pct - 0.20)
            else:
                outcome = ("LOSS", -stop_pct - 0.20)
            break
        if b["h"] >= target_price:
            outcome = ("WIN", target_pct - 0.20)
            break
        if b["l"] <= stop_price:
            outcome = ("LOSS", -stop_pct - 0.20)
            break

    if outcome is None:
        # TIMEOUT: usar el cierre del último bar
        pnl = (last_price / entry_price - 1) * 100 - 0.20
        outcome = ("TIMEOUT", pnl)

    return {
        "outcome": outcome[0],
        "pnl_pct": round(outcome[1], 4),
        "mfe":     round(mfe, 4),
        "mae":     round(mae, 4),
    }


def _verdict(decision, outcome, pnl_pct, mfe, mae, stop_pct, target_pct):
    """
    Clasifica la calidad de la decisión:
      Si dijo skip (ABORT, WATCH, o UNKNOWN-skipped):
        - GOOD_SKIP    si pnl_pct <= -stop_pct/2 (te ahorró pérdida)
        - MISSED_WIN   si pnl_pct >= target_pct*0.5 (perdiste ganancia)
        - NEUTRAL_SKIP si quedó en medio
      Si dijo GO (FULL o HALF):
        - GOOD_GO   si outcome WIN
        - BAD_GO    si outcome LOSS
        - WEAK_GO   si TIMEOUT pero positivo
        - BAD_GO    si TIMEOUT negativo
    """
    if decision in ("ABORT", "WATCH", "UNKNOWN"):
        if pnl_pct <= -stop_pct * 0.5:
            return "GOOD_SKIP"
        if pnl_pct >= target_pct * 0.5:
            return "MISSED_WIN"
        return "NEUTRAL_SKIP"
    if decision in ("FULL", "HALF"):
        if outcome == "WIN":
            return "GOOD_GO"
        if outcome == "LOSS":
            return "BAD_GO"
        if outcome == "TIMEOUT" and pnl_pct > 0:
            return "WEAK_GO"
        return "BAD_GO"
    return "UNKNOWN"


def evaluate_pending(only_n=None):
    """
    Itera decisiones sin eval_outcome cuyo decided_at + max_hours ya pasó,
    baja precios reales y calcula outcome retrospectivo.
    """
    con = _conn()
    rows = con.execute("""
        SELECT * FROM ml_decisions
        WHERE evaluated_at IS NULL
        ORDER BY decided_at ASC
    """).fetchall()
    if only_n:
        rows = rows[:only_n]
    if not rows:
        log("INFO", "ml_audit: no hay decisiones pendientes de evaluar")
        con.close()
        return 0

    now = datetime.now(timezone.utc)
    evaluated = 0
    for r in rows:
        decided = datetime.fromisoformat(r["decided_at"])
        # Normalizar a UTC si es naive (compatibilidad con registros antiguos)
        if decided.tzinfo is None:
            decided = decided.replace(tzinfo=timezone.utc)
        max_h = r["max_hours"] or 8.0
        # Solo evaluar si ya pasó max_hours (con margen de 5 min)
        if (now - decided).total_seconds() / 3600 < (max_h + 0.1):
            continue

        # Si hay un trade real abierto, usar su resultado real en vez de simular
        sim = None
        if r["opened_pred_id"]:
            try:
                pred_db = os.path.join(ROOT, "state", "crypto_predictions.db")
                pcon = sqlite3.connect(pred_db)
                pcon.row_factory = sqlite3.Row
                pred = pcon.execute(
                    "SELECT outcome, pnl_pct FROM predictions WHERE id=?",
                    (r["opened_pred_id"],)
                ).fetchone()
                pcon.close()
                if pred and pred["outcome"] in ("WIN", "LOSS", "TIMEOUT"):
                    real_outcome = pred["outcome"]
                    real_pnl = pred["pnl_pct"] or 0.0
                    sim = {
                        "outcome": real_outcome,
                        "pnl_pct": real_pnl,
                        "mfe": real_pnl if real_pnl > 0 else 0.0,
                        "mae": real_pnl if real_pnl < 0 else 0.0,
                    }
            except Exception:
                pass

        # Si no hay trade real o el trade sigue PENDING, simular con precios
        if sim is None:
            sim = _simulate_outcome(
                r["symbol"], r["price"], int(decided.timestamp() * 1000),
                r["stop_pct"] or 2.5, r["target_pct"] or 4.0, max_h
            )
        if sim is None:
            log("WARN", f"ml_audit: no se pudo simular {r['symbol']} pred_decided={r['decided_at']}")
            continue

        verdict = _verdict(
            r["ml_decision"], sim["outcome"], sim["pnl_pct"],
            sim["mfe"], sim["mae"], r["stop_pct"] or 2.5, r["target_pct"] or 4.0
        )

        con.execute("""
            UPDATE ml_decisions
            SET evaluated_at=?, eval_outcome=?, eval_pnl_pct=?,
                eval_max_pnl=?, eval_min_pnl=?, eval_verdict=?
            WHERE id=?
        """, (now.isoformat(), sim["outcome"], sim["pnl_pct"],
              sim["mfe"], sim["mae"], verdict, r["id"]))
        con.commit()
        evaluated += 1
        log("INFO", f"ml_audit: {r['symbol']} ML={r['ml_decision']} -> {sim['outcome']} pnl={sim['pnl_pct']:+.2f}% -> {verdict}")

    con.close()
    return evaluated


# ── Reportes ───────────────────────────────────────────────────────────────

def report(last_n=None):
    """Imprime un resumen de la calidad de las decisiones ML."""
    con = _conn()
    sql = """
        SELECT * FROM ml_decisions
        WHERE eval_verdict IS NOT NULL
        ORDER BY decided_at DESC
    """
    rows = con.execute(sql).fetchall()
    if last_n:
        rows = rows[:last_n]
    con.close()

    if not rows:
        print("\n  No hay decisiones evaluadas todavía.")
        print("  Corré primero:  python bot_crypto.py ml-eval")
        print("  (las decisiones necesitan haber pasado >= 8h desde que se tomaron)")
        return

    # Agregados
    total = len(rows)
    by_verdict = {}
    by_ml = {}
    for r in rows:
        v = r["eval_verdict"]
        ml = r["ml_decision"] or "UNKNOWN"
        by_verdict[v] = by_verdict.get(v, 0) + 1
        by_ml.setdefault(ml, {"n": 0, "verdicts": {}})
        by_ml[ml]["n"] += 1
        by_ml[ml]["verdicts"][v] = by_ml[ml]["verdicts"].get(v, 0) + 1

    print("\n  " + "=" * 66)
    print("  ML AUDIT — calidad retrospectiva de decisiones")
    print("  " + "=" * 66)
    print(f"  Total evaluadas: {total}")
    print()

    print("  Veredictos:")
    order = ["GOOD_SKIP", "NEUTRAL_SKIP", "MISSED_WIN", "GOOD_GO", "WEAK_GO", "BAD_GO"]
    for v in order:
        n = by_verdict.get(v, 0)
        pct = n / total * 100 if total else 0
        bar = "#" * int(pct / 2)
        print(f"    {v:<14s} {n:>4d}  ({pct:5.1f}%) {bar}")
    print()

    print("  Por decisión ML:")
    for ml, info in sorted(by_ml.items(), key=lambda x: -x[1]["n"]):
        n = info["n"]
        print(f"    {ml:<8s} (n={n}):")
        for v, count in sorted(info["verdicts"].items(), key=lambda x: -x[1]):
            pct = count / n * 100
            print(f"        {v:<14s} {count:>4d}  ({pct:5.1f}%)")
    print()

    # Métricas clave
    skip_total  = sum(v for k, v in by_verdict.items() if k in ("GOOD_SKIP", "NEUTRAL_SKIP", "MISSED_WIN"))
    skip_good   = by_verdict.get("GOOD_SKIP", 0)
    skip_neutral= by_verdict.get("NEUTRAL_SKIP", 0)
    skip_miss   = by_verdict.get("MISSED_WIN", 0)
    go_total = sum(v for k, v in by_verdict.items() if k in ("GOOD_GO", "WEAK_GO", "BAD_GO"))
    go_good  = by_verdict.get("GOOD_GO", 0) + by_verdict.get("WEAK_GO", 0)
    go_bad   = by_verdict.get("BAD_GO", 0)

    if skip_total > 0:
        skip_acc = (skip_good + skip_neutral) / skip_total * 100
        opp_loss = skip_miss / skip_total * 100
        print(f"  SKIPS:  {skip_total} totales")
        print(f"    Skip accuracy:    {skip_acc:.1f}%  (te ahorraron pérdida + neutrales)")
        print(f"    Opportunity loss: {opp_loss:.1f}%  (precio subió al target tras vetar)")
    if go_total > 0:
        go_acc = go_good / go_total * 100
        print(f"  GOS:    {go_total} totales")
        print(f"    Entry accuracy:   {go_acc:.1f}%  (trades que terminaron en ganancia)")
    print("  " + "=" * 66 + "\n")


# ── CLI ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd")
    sp.add_parser("eval")
    sp.add_parser("report")
    args = ap.parse_args()
    if args.cmd == "eval":
        n = evaluate_pending()
        print(f"\n  Evaluadas: {n} decisiones")
    elif args.cmd == "report":
        report()
    else:
        ap.print_help()
