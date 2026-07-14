"""
Reporte diario y veredicto de readiness para la prueba 24/7 de un mes.

- generate_daily_report(): escribe reports/daily_YYYY-MM-DD.md y agrega una
  fila a reports/summary.csv con exactamente las columnas que pide
  GUIA_DIARIA.md (fecha, trades, WR, Exp, P&L, entry accuracy, BAD_GO,
  MISSED_WIN). Con el CSV, al final del mes la tendencia se ve de un vistazo.

- readiness_report(): evalua los criterios de lanzamiento a mainnet
  (definidos en GUIA_DIARIA/CLAUDE.md) sobre los trades acumulados con la
  contabilidad honesta: >=14 dias operando, >=20 trades cerrados, WR>=55%,
  expectancy > 0, profit factor > 1.2.

Las metricas se calculan SOLO con trades post 2026-06-10 (contabilidad
honesta). BE y CANCELLED quedan fuera del WR, igual que en el resto del bot.
"""
import os
import sys
import json
import sqlite3
import csv
from datetime import datetime, date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bot.logger import log

DB_PATH = os.path.join(ROOT, "state", "crypto_predictions.db")
ML_DB_PATH = os.path.join(ROOT, "state", "ml_decisions.db")
REPORTS_DIR = os.path.join(ROOT, "reports")
SUMMARY_CSV = os.path.join(REPORTS_DIR, "summary.csv")

ACCOUNTING_FIX_DATE = "2026-06-10"
POSITION_PCT = 0.05  # mismo sizing simulado que runner._compute_simulated_balance


def _capital() -> float:
    return float(os.environ.get("CRYPTO_PORTFOLIO",
                 os.environ.get("CRYPTO_INITIAL_CAPITAL", "1000")))


def _conn():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    return con


# ── Metricas ─────────────────────────────────────────────────────────────

def _pos_usd(r, capital: float) -> float:
    """Posicion real del trade en USD. NULL (legacy sin sizing) usa el
    fallback de 5%; 0 (sizing vetado) no mueve la curva de equity."""
    try:
        v = r["position_usd"]
    except (IndexError, KeyError):
        v = None
    if v is None:
        return capital * POSITION_PCT
    return float(v)


def _trade_stats(rows) -> dict:
    """Estadisticas de una lista de trades cerrados (rows con outcome/pnl_pct)."""
    wins   = [r for r in rows if r["outcome"] == "WIN"]
    losses = [r for r in rows if r["outcome"] == "LOSS"]
    be     = [r for r in rows if r["outcome"] == "BE"]
    resolved = wins + losses
    n = len(resolved)

    wr = 100.0 * len(wins) / n if n else 0.0
    pnls = [r["pnl_pct"] or 0.0 for r in resolved]
    expectancy = sum(pnls) / n if n else 0.0
    gross_win  = sum((r["pnl_pct"] or 0.0) for r in wins)
    gross_loss = abs(sum((r["pnl_pct"] or 0.0) for r in losses))
    pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)

    capital = _capital()
    # P&L en dolares ponderado por el sizing REAL de cada trade
    pnl_usd = sum(_pos_usd(r, capital) * ((r["pnl_pct"] or 0.0) / 100.0)
                  for r in resolved)

    # Max drawdown de la curva de equity simulada (orden cronologico)
    equity = capital
    peak = capital
    max_dd = 0.0
    for r in sorted(resolved, key=lambda x: x["outcome_date"] or ""):
        equity += _pos_usd(r, capital) * ((r["pnl_pct"] or 0.0) / 100.0)
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100.0)

    return {
        "total": n, "wins": len(wins), "losses": len(losses), "be": len(be),
        "wr": round(wr, 1), "expectancy": round(expectancy, 3),
        "pf": round(pf, 2) if pf != float("inf") else None,
        "pnl_usd": round(pnl_usd, 2), "max_dd_pct": round(max_dd, 2),
        "avg_win": round(gross_win / len(wins), 3) if wins else 0.0,
        "avg_loss": round(-gross_loss / len(losses), 3) if losses else 0.0,
    }


def _per_model(rows) -> dict:
    out = {}
    for r in rows:
        m = r["model"] or "?"
        out.setdefault(m, []).append(r)
    return {m: _trade_stats(v) for m, v in sorted(out.items())}


def _query(sql: str, params=()) -> list:
    """Consulta tolerante: en el primer arranque la DB/tabla aun no existe."""
    try:
        con = _conn()
        rows = con.execute(sql, params).fetchall()
        con.close()
        return rows
    except sqlite3.Error:
        return []


def _closed_on(day_iso: str):
    return _query("""
        SELECT * FROM predictions
        WHERE outcome IN ('WIN','LOSS','BE') AND DATE(outcome_date) = ?
    """, (day_iso,))


def _closed_since_fix():
    return _query("""
        SELECT * FROM predictions
        WHERE outcome IN ('WIN','LOSS','BE') AND outcome_date >= ?
    """, (ACCOUNTING_FIX_DATE,))


def _open_positions():
    return _query("""
        SELECT id, symbol, model, predicted_at, price_at_pred
        FROM predictions WHERE outcome='PENDING' ORDER BY predicted_at
    """)


def _ml_quality(day_iso: str = None) -> dict:
    """Entry/skip accuracy, BAD_GO y MISSED_WIN desde ml_decisions.db."""
    out = {"evaluated": 0, "entry_acc": None, "skip_acc": None,
           "bad_go": 0, "missed_win": 0}
    if not os.path.exists(ML_DB_PATH):
        return out
    try:
        con = sqlite3.connect(ML_DB_PATH)
        con.row_factory = sqlite3.Row
        sql = "SELECT eval_verdict FROM ml_decisions WHERE eval_verdict IS NOT NULL"
        params = ()
        if day_iso:
            sql += " AND DATE(decided_at) = ?"
            params = (day_iso,)
        rows = con.execute(sql, params).fetchall()
        con.close()
    except Exception:
        return out

    v = {}
    for r in rows:
        v[r["eval_verdict"]] = v.get(r["eval_verdict"], 0) + 1
    go_total = v.get("GOOD_GO", 0) + v.get("WEAK_GO", 0) + v.get("BAD_GO", 0)
    skip_total = v.get("GOOD_SKIP", 0) + v.get("NEUTRAL_SKIP", 0) + v.get("MISSED_WIN", 0)
    out["evaluated"] = len(rows)
    out["bad_go"] = v.get("BAD_GO", 0)
    out["missed_win"] = v.get("MISSED_WIN", 0)
    if go_total:
        out["entry_acc"] = round(100.0 * (v.get("GOOD_GO", 0) + v.get("WEAK_GO", 0)) / go_total, 1)
    if skip_total:
        out["skip_acc"] = round(100.0 * (v.get("GOOD_SKIP", 0) + v.get("NEUTRAL_SKIP", 0)) / skip_total, 1)
    return out


def _guards_status() -> dict:
    out = {"risk_guard": "?", "circuit_breaker": "?", "model_health": "?"}
    try:
        from bot.risk_guard import is_tripped, trip_reason
        out["risk_guard"] = f"TRIPPED ({trip_reason()})" if is_tripped() else "OK"
    except Exception as e:
        out["risk_guard"] = f"error: {e}"
    try:
        from bot.circuit_breaker import check_circuit_breaker
        blocked, reason = check_circuit_breaker()
        out["circuit_breaker"] = f"BLOCKED ({reason})" if blocked else "OK"
    except Exception as e:
        out["circuit_breaker"] = f"error: {e}"
    try:
        from bot.model_health import status_line
        out["model_health"] = status_line()
    except Exception as e:
        out["model_health"] = f"error: {e}"
    try:
        from bot.market_regime import current_regime_label, today_status
        lbl = current_regime_label()
        out["regime"] = f"{lbl} [{today_status()}]" if lbl else "sin clasificar"
    except Exception as e:
        out["regime"] = f"error: {e}"
    return out


# ── Reporte diario ───────────────────────────────────────────────────────

def generate_daily_report(day_iso: str = None) -> str:
    """Genera el reporte del dia. Retorna el path del .md escrito."""
    day_iso = day_iso or date.today().isoformat()
    os.makedirs(REPORTS_DIR, exist_ok=True)

    day_rows = _closed_on(day_iso)
    day = _trade_stats(day_rows)
    day_models = _per_model(day_rows)

    cum_rows = _closed_since_fix()
    cum = _trade_stats(cum_rows)
    cum_models = _per_model(cum_rows)

    ml_day = _ml_quality(day_iso)
    ml_cum = _ml_quality()
    guards = _guards_status()
    open_pos = _open_positions()

    try:
        from bot.maintenance import data_freshness
        freshness = data_freshness()
    except Exception:
        freshness = {}

    lines = []
    a = lines.append
    a(f"# Reporte diario — {day_iso}")
    a("")
    a(f"_Generado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · "
      f"capital simulado ${_capital():.0f} · P&L ponderado por sizing real "
      f"(fallback {POSITION_PCT*100:.0f}% en trades sin sizing)_")
    a("")
    a("## Trades del dia")
    a("")
    a(f"- Cerrados: **{day['total']}** (W {day['wins']} / L {day['losses']} / BE {day['be']})")
    a(f"- Win rate: **{day['wr']:.1f}%** · Expectancy: **{day['expectancy']:+.3f}%** · "
      f"P&L: **${day['pnl_usd']:+.2f}**")
    a(f"- Avg win {day['avg_win']:+.3f}% · Avg loss {day['avg_loss']:+.3f}%")
    if day_models:
        a("")
        a("| Modelo | Trades | WR% | Exp% | P&L USD |")
        a("|--------|-------:|----:|-----:|--------:|")
        for m, s in day_models.items():
            a(f"| {m} | {s['total']} | {s['wr']:.1f} | {s['expectancy']:+.3f} | {s['pnl_usd']:+.2f} |")
    a("")
    a(f"## Acumulado desde el fix de contabilidad ({ACCOUNTING_FIX_DATE})")
    a("")
    a(f"- Cerrados: **{cum['total']}** (W {cum['wins']} / L {cum['losses']} / BE {cum['be']})")
    pf_s = f"{cum['pf']:.2f}" if cum['pf'] is not None else "inf"
    a(f"- Win rate: **{cum['wr']:.1f}%** · Expectancy: **{cum['expectancy']:+.3f}%** · "
      f"Profit factor: **{pf_s}**")
    a(f"- P&L acumulado: **${cum['pnl_usd']:+.2f}** · Max drawdown equity: {cum['max_dd_pct']:.2f}%")
    if cum_models:
        a("")
        a("| Modelo | Trades | WR% | Exp% | PF | P&L USD |")
        a("|--------|-------:|----:|-----:|---:|--------:|")
        for m, s in cum_models.items():
            mpf = f"{s['pf']:.2f}" if s['pf'] is not None else "inf"
            a(f"| {m} | {s['total']} | {s['wr']:.1f} | {s['expectancy']:+.3f} | {mpf} | {s['pnl_usd']:+.2f} |")
    a("")
    def _pct(v):
        return f"{v}%" if v is not None else "n/a"
    a("## Calidad de decisiones ML")
    a("")
    a(f"- Hoy: {ml_day['evaluated']} evaluadas · entry acc: {_pct(ml_day['entry_acc'])} · "
      f"skip acc: {_pct(ml_day['skip_acc'])} · BAD_GO: {ml_day['bad_go']} · MISSED_WIN: {ml_day['missed_win']}")
    a(f"- Acumulado: {ml_cum['evaluated']} evaluadas · entry acc: {_pct(ml_cum['entry_acc'])} · "
      f"skip acc: {_pct(ml_cum['skip_acc'])} · BAD_GO: {ml_cum['bad_go']} · MISSED_WIN: {ml_cum['missed_win']}")
    a("")
    a("## Estado operativo")
    a("")
    a(f"- Risk guard: {guards['risk_guard']}")
    a(f"- Circuit breaker: {guards['circuit_breaker']}")
    a(f"- Drift guard (ML): {guards['model_health']}")
    a(f"- Comportamiento (regimen): {guards['regime']}")
    a(f"- Posiciones abiertas: {len(open_pos)}"
      + (f" ({', '.join(r['symbol'] for r in open_pos)})" if open_pos else ""))
    if freshness:
        for db, age in freshness.items():
            estado = f"{age}h de antiguedad" if age is not None else "SIN DATOS"
            warn = " ⚠️" if (age is None or (age is not None and age > 48)) else ""
            a(f"- Datos {db}: {estado}{warn}")
    a("")

    path = os.path.join(REPORTS_DIR, f"daily_{day_iso}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    _append_summary_csv(day_iso, day, ml_day)
    log("INFO", f"daily_report: escrito {path}")
    return path


def _append_summary_csv(day_iso: str, day: dict, ml_day: dict):
    """Una fila por dia — el 'registro simple' que pide GUIA_DIARIA.md."""
    header = ["fecha", "trades", "wins", "losses", "be", "wr_pct",
              "expectancy_pct", "pnl_usd", "entry_acc_pct", "bad_go", "missed_win"]
    row = [day_iso, day["total"], day["wins"], day["losses"], day["be"],
           day["wr"], day["expectancy"], day["pnl_usd"],
           ml_day["entry_acc"] if ml_day["entry_acc"] is not None else "",
           ml_day["bad_go"], ml_day["missed_win"]]

    rows = []
    if os.path.exists(SUMMARY_CSV):
        with open(SUMMARY_CSV, newline="", encoding="utf-8") as f:
            rows = [r for r in csv.reader(f)]
    # Reemplazar la fila del dia si ya existe (reporte re-generado)
    rows = [r for r in rows if not (r and r[0] == day_iso)]
    if not rows or rows[0] != header:
        rows = [r for r in rows if r and r[0] != "fecha"]
        rows.insert(0, header)
    rows.append([str(x) for x in row])
    with open(SUMMARY_CSV, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)


# ── Readiness ────────────────────────────────────────────────────────────

def readiness_report() -> dict:
    """
    Evalua los criterios de lanzamiento. Imprime el veredicto y lo retorna.
    Criterios (de GUIA_DIARIA.md / CLAUDE.md, con contabilidad honesta):
      - >= 14 dias desde el primer trade post-fix
      - >= 20 trades cerrados (WIN/LOSS)
      - WR >= 55%
      - expectancy > 0 (neta de comisiones, FEE ya descontada en outcome)
      - profit factor > 1.2
      - max drawdown de equity < 15%
    """
    rows = _closed_since_fix()
    s = _trade_stats(rows)

    first = None
    resolved = [r for r in rows if r["outcome"] in ("WIN", "LOSS")]
    if resolved:
        first = min(r["outcome_date"] for r in resolved if r["outcome_date"])
    days_running = 0
    if first:
        days_running = (datetime.now() - datetime.fromisoformat(first)).days

    criteria = [
        ("Dias operando (>=14)", days_running, days_running >= 14),
        ("Trades cerrados (>=20)", s["total"], s["total"] >= 20),
        ("Win rate (>=55%)", f"{s['wr']:.1f}%", s["wr"] >= 55.0),
        ("Expectancy (>0%)", f"{s['expectancy']:+.3f}%", s["expectancy"] > 0),
        ("Profit factor (>1.2)", s["pf"], (s["pf"] or 0) > 1.2),
        ("Max DD equity (<15%)", f"{s['max_dd_pct']:.2f}%", s["max_dd_pct"] < 15.0),
    ]
    passed = sum(1 for _, _, ok in criteria if ok)
    ready = passed == len(criteria)

    print("\n  " + "=" * 60)
    print("  READINESS — ¿listo para mainnet?")
    print("  " + "=" * 60)
    for name, value, ok in criteria:
        print(f"  [{'OK ' if ok else 'NO '}] {name:<28} {value}")
    print("  " + "-" * 60)
    if ready:
        print("  VEREDICTO: CRITERIOS CUMPLIDOS — revisar manualmente antes de")
        print("  pasar a mainnet (empezar con 1% del capital, ver CLAUDE.md).")
    else:
        print(f"  VEREDICTO: AUN NO ({passed}/{len(criteria)} criterios). Seguir en testnet.")
    print("  " + "=" * 60 + "\n")

    return {"ready": ready, "passed": passed, "criteria": [
        {"name": n, "value": str(v), "ok": ok} for n, v, ok in criteria]}


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "readiness":
        readiness_report()
    else:
        print(generate_daily_report(sys.argv[1] if len(sys.argv) > 1 else None))
