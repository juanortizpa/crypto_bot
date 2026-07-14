"""
Model Health / Drift Guard — detecta cuando los modelos ML dejan de predecir
porque el mercado cambio (concept drift).

Los modelos del ensemble (XGB / RF / Hybrid) aprendieron de una foto estatica
(2024). En crypto esa foto caduca: el mercado cambia de regimen y los modelos
siguen emitiendo probabilidades con la misma confianza aunque ya no acierten.
Este modulo vigila TRES capas independientes y las agrega en un estado:

  A) PERFORMANCE DRIFT — ¿los trades del Modelo D (los que el ensemble
     aprueba) rinden peor de lo que el entrenamiento prometio?
       - Test binomial: con los ultimos N trades cerrados y su WR vivo,
         probabilidad de un resultado tan malo si el WR real fuera el del
         test out-of-sample. p < 0.05 => el modelo YA NO predice.
       - CUSUM sobre la secuencia de pnl_pct: acumula el deficit contra un
         margen de tolerancia; detecta deterioro gradual que el test
         binomial tarda en ver.
  B) FEATURE DRIFT (PSI) — ¿la distribucion de las features que ve el ML
     en vivo (ultimos 7 dias) se parece a la de las semanas anteriores?
       PSI (Population Stability Index): <0.10 estable, 0.10-0.25 cambio
       moderado, >0.25 cambio fuerte. Ademas detecta features macro
       congeladas en 0 (data_extended.db sin refrescar).
  C) REGIME SHIFT — ¿la volatilidad / extension de tendencia actual de BTC
     esta fuera del rango que los modelos vieron en 2024?
       La referencia se construye una vez desde data_2026.db (si existe en
       el portatil) y se cachea en state/regime_reference.json.

Agregacion (fail-open: sin datos suficientes NINGUNA capa acusa drift):
  - Capa A fuerte                          => DEGRADED (el modelo no acierta)
  - Capa B/C fuerte + otra señal cualquiera => DEGRADED
  - Cualquier señal suelta                  => WATCH
  - Nada                                    => HEALTHY

Efectos:
  - DEGRADED => runner trata la opinion del ensemble para el Modelo D como
    NO CONFIABLE (no abre dips) hasta que un retrain con quality gate OOS
    recupere el estado. forever adelanta ese retrain.
  - WATCH    => se loguea y aparece en el reporte diario. No bloquea.

CLI: python bot_crypto.py drift
Desactivar: CRYPTO_DRIFT_GUARD=off
"""
import os
import sys
import json
import math
import sqlite3
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bot.logger import log

STATE_DIR = os.path.join(ROOT, "state")
HEALTH_JSON = os.path.join(STATE_DIR, "model_health.json")
SNAPSHOT_DB = os.path.join(STATE_DIR, "model_health.db")
PRED_DB = os.path.join(STATE_DIR, "crypto_predictions.db")
REGIME_REF_JSON = os.path.join(STATE_DIR, "regime_reference.json")
TRAIN_DB = os.path.join(ROOT, "model_d_training", "state", "data_2026.db")
RESULTS_DIR = os.path.join(ROOT, "model_d_training", "results")

ACCOUNTING_FIX_DATE = "2026-06-10"

# ── Umbrales (todos configurables por env) ────────────────────────────────
PERF_WINDOW = int(os.environ.get("CRYPTO_DRIFT_PERF_WINDOW", "25"))
# Solo trades de los ultimos N dias: al bloquear D no entran trades nuevos,
# asi que sin este limite una racha mala dejaria DEGRADED para siempre.
# Con el, los trades malos caducan y el sistema reintenta solo (probation).
PERF_MAX_AGE_DAYS = float(os.environ.get("CRYPTO_DRIFT_PERF_DAYS", "14"))
PERF_MIN_TRADES = int(os.environ.get("CRYPTO_DRIFT_MIN_TRADES", "15"))
PERF_PVALUE = float(os.environ.get("CRYPTO_DRIFT_PVALUE", "0.05"))
CUSUM_SLACK = float(os.environ.get("CRYPTO_DRIFT_CUSUM_SLACK", "0.15"))   # % por trade
CUSUM_ALARM = float(os.environ.get("CRYPTO_DRIFT_CUSUM_ALARM", "10.0"))   # % acumulado
PSI_MODERATE = float(os.environ.get("CRYPTO_DRIFT_PSI_MODERATE", "0.10"))
PSI_MAJOR = float(os.environ.get("CRYPTO_DRIFT_PSI_MAJOR", "0.25"))
PSI_MIN_SAMPLES = int(os.environ.get("CRYPTO_DRIFT_PSI_MIN_SAMPLES", "60"))
PSI_MAJOR_FEATS_STRONG = int(os.environ.get("CRYPTO_DRIFT_PSI_FEATS", "3"))
SNAPSHOT_RETENTION_DAYS = 60

# Features que se monitorean para PSI (subset estable de las 49 del ensemble)
TRACKED_FEATURES = [
    "rsi14_1h", "rsi14_4h", "atr_pct_1h", "atr_pct_5m",
    "drawdown_7d", "vol_zscore_7d", "mom_24h", "mom_4h",
    "btc_trend_24h", "rs_vs_btc_4h", "funding_last",
    "fng_value", "vix_close", "dxy_close",
]
MACRO_FEATURES = ("dxy_close", "vix_close", "sp500_close")


# ══════════════════════════════════════════════════════════════════════════
# Persistencia
# ══════════════════════════════════════════════════════════════════════════

def _snap_conn():
    os.makedirs(STATE_DIR, exist_ok=True)
    con = sqlite3.connect(SNAPSHOT_DB, timeout=30)
    con.execute("""
        CREATE TABLE IF NOT EXISTS feature_snapshots (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            ts      TEXT NOT NULL,
            symbol  TEXT NOT NULL,
            feats   TEXT NOT NULL
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_snap_ts ON feature_snapshots(ts)")
    return con


def record_features(symbol: str, feats: dict):
    """Graba las features que vio el ML (llamado desde ml_inference.predict).
    Best-effort: nunca lanza excepcion hacia el caller."""
    try:
        slim = {k: feats.get(k) for k in TRACKED_FEATURES if feats.get(k) is not None}
        if not slim:
            return
        con = _snap_conn()
        con.execute(
            "INSERT INTO feature_snapshots (ts, symbol, feats) VALUES (?,?,?)",
            (datetime.now().isoformat(), symbol, json.dumps(slim)))
        # Retencion: no acumular mas alla de SNAPSHOT_RETENTION_DAYS
        cutoff = (datetime.now() - timedelta(days=SNAPSHOT_RETENTION_DAYS)).isoformat()
        con.execute("DELETE FROM feature_snapshots WHERE ts < ?", (cutoff,))
        con.commit()
        con.close()
    except Exception as e:
        log("DEBUG", f"model_health: record_features fallo: {e}")


def _load_health() -> dict:
    try:
        with open(HEALTH_JSON, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_health(h: dict):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = HEALTH_JSON + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(h, f, indent=2)
        os.replace(tmp, HEALTH_JSON)
    except Exception as e:
        log("WARN", f"model_health: no se pudo guardar estado: {e}")


# ══════════════════════════════════════════════════════════════════════════
# Capa A — Performance drift
# ══════════════════════════════════════════════════════════════════════════

def _baseline_wr() -> float:
    """WR baseline del entrenamiento: el minimo de los WR de test OOS de los
    modelos cargables con muestra decente (n>=200). El RF con n=101 y WR 84%
    queda excluido a proposito (muestra chica, probable sobreajuste)."""
    wrs = []
    for name in ("xgb_best.json", "hybrid_best.json", "rf_best.json"):
        try:
            with open(os.path.join(RESULTS_DIR, name), encoding="utf-8") as f:
                d = json.load(f)
            mt = d.get("metrics_test") or {}
            if (mt.get("n_trades") or 0) >= 200 and mt.get("wr"):
                wrs.append(float(mt["wr"]))
        except Exception:
            continue
    if wrs:
        return max(0.40, min(wrs))  # nunca por debajo de 40%
    return float(os.environ.get("CRYPTO_DRIFT_BASELINE_WR", "0.55"))


def _binom_tail_p(n: int, wins: int, p0: float) -> float:
    """P(X <= wins) con X ~ Binomial(n, p0): probabilidad de un resultado
    tan malo (o peor) si el WR real fuera p0."""
    p = 0.0
    for k in range(0, wins + 1):
        p += math.comb(n, k) * (p0 ** k) * ((1 - p0) ** (n - k))
    return min(1.0, p)


def _recent_d_trades(window_start: str) -> list:
    """Ultimos PERF_WINDOW trades cerrados del Modelo D (los que vetó/aprobo
    el ensemble), en orden cronologico."""
    try:
        age_cut = (datetime.now() - timedelta(days=PERF_MAX_AGE_DAYS)).isoformat()
        start = max(window_start, age_cut)
        con = sqlite3.connect(PRED_DB, timeout=30)
        con.row_factory = sqlite3.Row
        rows = con.execute("""
            SELECT outcome, pnl_pct, outcome_date FROM predictions
            WHERE model='D' AND outcome IN ('WIN','LOSS')
              AND pnl_pct IS NOT NULL AND outcome_date >= ?
            ORDER BY outcome_date DESC LIMIT ?
        """, (start, PERF_WINDOW)).fetchall()
        con.close()
        return list(reversed(rows))
    except Exception:
        return []


def _check_performance(window_start: str) -> list:
    """Retorna lista de señales (severity, code, detail)."""
    signals = []
    trades = _recent_d_trades(window_start)
    n = len(trades)
    if n < PERF_MIN_TRADES:
        return signals  # fail-open: sin muestra no se acusa

    wins = sum(1 for t in trades if t["outcome"] == "WIN")
    wr_live = wins / n
    p0 = _baseline_wr()
    pval = _binom_tail_p(n, wins, p0)
    if pval < PERF_PVALUE:
        signals.append(("STRONG", "PERF_BINOMIAL",
                        f"WR vivo {wr_live:.0%} en {n} trades vs baseline "
                        f"{p0:.0%} OOS (p={pval:.3f}) — el modelo ya no acierta"))

    # CUSUM: deficit acumulado de pnl contra el margen de tolerancia.
    # Detecta expectancy negativa sostenida aunque el WR no colapse.
    s = 0.0
    s_max = 0.0
    for t in trades:
        s = max(0.0, s + (-(t["pnl_pct"] or 0.0) - CUSUM_SLACK))
        s_max = max(s_max, s)
    if s_max >= CUSUM_ALARM:
        signals.append(("STRONG", "PERF_CUSUM",
                        f"Deficit acumulado {s_max:.1f}% en los ultimos {n} "
                        f"trades D (alarma en {CUSUM_ALARM:.0f}%)"))
    return signals


# ══════════════════════════════════════════════════════════════════════════
# Capa B — Feature drift (PSI)
# ══════════════════════════════════════════════════════════════════════════

def _psi(reference: list, current: list, bins: int = 10) -> float:
    """Population Stability Index entre dos muestras de una feature."""
    if len(reference) < 10 or len(current) < 10:
        return 0.0
    ref = sorted(reference)
    # Bordes por deciles de la referencia
    edges = [ref[int(len(ref) * i / bins)] for i in range(1, bins)]

    def _proportions(values):
        counts = [0] * bins
        for v in values:
            b = 0
            while b < len(edges) and v > edges[b]:
                b += 1
            counts[b] += 1
        total = len(values)
        return [max(c / total, 1e-4) for c in counts]

    p_ref = _proportions(reference)
    p_cur = _proportions(current)
    return sum((c - r) * math.log(c / r) for r, c in zip(p_ref, p_cur))


def _check_features() -> list:
    signals = []
    try:
        con = _snap_conn()
        now = datetime.now()
        recent_cut = (now - timedelta(days=7)).isoformat()
        ref_cut = (now - timedelta(days=37)).isoformat()
        recent_rows = con.execute(
            "SELECT feats FROM feature_snapshots WHERE ts >= ?", (recent_cut,)
        ).fetchall()
        ref_rows = con.execute(
            "SELECT feats FROM feature_snapshots WHERE ts >= ? AND ts < ?",
            (ref_cut, recent_cut)).fetchall()
        last_row = con.execute(
            "SELECT feats FROM feature_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        con.close()
    except Exception:
        return signals

    # Macro congelada: la señal mas comun y silenciosa (data_extended vieja)
    if last_row:
        try:
            last = json.loads(last_row[0])
            frozen = [k for k in MACRO_FEATURES if k in last and not last[k]]
            if frozen:
                signals.append(("MODERATE", "MACRO_STALE",
                                f"Features macro en 0: {', '.join(frozen)} — "
                                f"data_extended.db sin refrescar"))
        except Exception:
            pass

    if len(recent_rows) < PSI_MIN_SAMPLES or len(ref_rows) < PSI_MIN_SAMPLES:
        return signals  # fail-open: aun sin historial suficiente

    def _extract(rows):
        out = {k: [] for k in TRACKED_FEATURES}
        for (blob,) in rows:
            try:
                d = json.loads(blob)
            except Exception:
                continue
            for k in TRACKED_FEATURES:
                v = d.get(k)
                if v is not None:
                    out[k].append(float(v))
        return out

    ref_f = _extract(ref_rows)
    cur_f = _extract(recent_rows)
    major, moderate = [], []
    for k in TRACKED_FEATURES:
        val = _psi(ref_f[k], cur_f[k])
        if val >= PSI_MAJOR:
            major.append(f"{k}={val:.2f}")
        elif val >= PSI_MODERATE:
            moderate.append(f"{k}={val:.2f}")

    if len(major) >= PSI_MAJOR_FEATS_STRONG:
        signals.append(("STRONG", "PSI_SHIFT",
                        f"{len(major)} features con shift fuerte: "
                        f"{', '.join(major[:5])} — el mercado que ve el ML "
                        f"ya no se parece al de hace semanas"))
    elif major or len(moderate) >= 4:
        det = ", ".join((major + moderate)[:5])
        signals.append(("MODERATE", "PSI_SHIFT", f"Drift de features: {det}"))
    return signals


# ══════════════════════════════════════════════════════════════════════════
# Capa C — Regime shift vs entrenamiento (2024)
# ══════════════════════════════════════════════════════════════════════════

def _percentile(sorted_vals: list, q: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, max(0, int(q * (len(sorted_vals) - 1))))
    return sorted_vals[idx]


def _build_regime_reference() -> dict | None:
    """Percentiles de vol realizada 30d y extension |precio vs MA50| de BTC
    durante el periodo de entrenamiento. Se calcula una vez y se cachea."""
    try:
        with open(REGIME_REF_JSON, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        pass
    if not os.path.exists(TRAIN_DB):
        return None
    try:
        con = sqlite3.connect(TRAIN_DB, timeout=30)
        cols = [r[1] for r in con.execute("PRAGMA table_info(ohlcv)")]
        symcol = "pair" if "pair" in cols else ("symbol" if "symbol" in cols else None)
        tscol = "timestamp" if "timestamp" in cols else ("ts" if "ts" in cols else None)
        ccol = "close" if "close" in cols else ("c" if "c" in cols else None)
        if not (symcol and tscol and ccol):
            con.close()
            return None
        rows = con.execute(
            f"SELECT DATE({tscol}) d, MAX({tscol}) mt, {ccol} FROM ohlcv "
            f"WHERE {symcol}='BTCUSDT' GROUP BY DATE({tscol}) ORDER BY d"
        ).fetchall()
        con.close()
        closes = [float(r[2]) for r in rows if r[2]]
        if len(closes) < 90:
            return None
        # Vol realizada 30d anualizada (%) y |dist MA50| (%) dia a dia
        vols, exts = [], []
        for i in range(50, len(closes)):
            rets = [math.log(closes[j] / closes[j - 1])
                    for j in range(i - 29, i + 1)]
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
            vols.append(math.sqrt(var) * math.sqrt(365) * 100)
            ma50 = sum(closes[i - 49:i + 1]) / 50
            exts.append(abs(closes[i] / ma50 - 1) * 100)
        vols.sort(); exts.sort()
        ref = {
            "built_at": datetime.now().isoformat(),
            "days": len(vols),
            "vol30_p05": round(_percentile(vols, 0.05), 2),
            "vol30_p95": round(_percentile(vols, 0.95), 2),
            "ext50_p95": round(_percentile(exts, 0.95), 2),
        }
        with open(REGIME_REF_JSON, "w", encoding="utf-8") as f:
            json.dump(ref, f, indent=2)
        log("INFO", f"model_health: referencia de regimen construida: {ref}")
        return ref
    except Exception as e:
        log("WARN", f"model_health: no se pudo construir referencia de regimen: {e}")
        return None


def _check_regime() -> list:
    signals = []
    ref = _build_regime_reference()
    if not ref:
        return signals  # sin data de entrenamiento local: se omite la capa
    try:
        from bot.crypto_data import get_bars
        bars = get_bars("BTCUSDT", "1d", 120)
        closes = [b["c"] for b in bars]
        if len(closes) < 60:
            return signals
        rets = [math.log(closes[i] / closes[i - 1])
                for i in range(len(closes) - 29, len(closes))]
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        vol30 = math.sqrt(var) * math.sqrt(365) * 100
        ma50 = sum(closes[-50:]) / 50
        ext50 = abs(closes[-1] / ma50 - 1) * 100

        if vol30 > ref["vol30_p95"] * 1.25 or vol30 < ref["vol30_p05"] * 0.75:
            signals.append(("STRONG", "REGIME_VOL",
                            f"Vol BTC 30d {vol30:.0f}% muy fuera del rango de "
                            f"entrenamiento [{ref['vol30_p05']:.0f}-{ref['vol30_p95']:.0f}]%"))
        elif vol30 > ref["vol30_p95"] or vol30 < ref["vol30_p05"]:
            signals.append(("MODERATE", "REGIME_VOL",
                            f"Vol BTC 30d {vol30:.0f}% fuera del rango de "
                            f"entrenamiento [{ref['vol30_p05']:.0f}-{ref['vol30_p95']:.0f}]%"))
        if ext50 > ref["ext50_p95"] * 1.25:
            signals.append(("MODERATE", "REGIME_EXT",
                            f"BTC a {ext50:.1f}% de su MA50 (entrenamiento p95: "
                            f"{ref['ext50_p95']:.1f}%) — tendencia mas extendida "
                            f"que todo lo visto en training"))
    except Exception as e:
        log("DEBUG", f"model_health: check regimen fallo: {e}")
    return signals


# ══════════════════════════════════════════════════════════════════════════
# Capa D — Comportamiento del mercado (catalogo de regimenes)
# ══════════════════════════════════════════════════════════════════════════

def _check_behavior() -> list:
    """Dias recientes clasificados como COMPORTAMIENTO NUEVO (nunca visto en
    el catalogo 2024→hoy) son evidencia directa de que los modelos estan
    operando fuera de lo que conocen."""
    signals = []
    try:
        from bot.market_regime import recent_novelty, current_regime_label
        n_new = recent_novelty(days=3)
        if n_new >= 2:
            signals.append(("STRONG", "BEHAVIOR_NEW",
                            f"{n_new} de los ultimos 3 dias en comportamiento "
                            f"NUNCA VISTO en el catalogo de regimenes"))
        elif n_new == 1:
            signals.append(("MODERATE", "BEHAVIOR_NEW",
                            "Hoy el mercado no se parece a ningun "
                            "comportamiento conocido del catalogo"))
    except Exception:
        pass  # sin catalogo/historia: fail-open
    return signals


# ══════════════════════════════════════════════════════════════════════════
# Agregacion + API publica
# ══════════════════════════════════════════════════════════════════════════

def evaluate() -> dict:
    """Corre las 3 capas y persiste el estado agregado."""
    prev = _load_health()
    window_start = prev.get("perf_window_start") or ACCOUNTING_FIX_DATE

    signals = []
    signals += _check_performance(window_start)
    signals += _check_features()
    signals += _check_regime()
    signals += _check_behavior()

    strong = [s for s in signals if s[0] == "STRONG"]
    moderate = [s for s in signals if s[0] == "MODERATE"]

    perf_strong = any(s[1].startswith("PERF_") for s in strong)
    if perf_strong or (strong and (len(strong) + len(moderate)) >= 2):
        status = "DEGRADED"
    elif strong or moderate:
        status = "WATCH"
    else:
        status = "HEALTHY"

    result = {
        "status": status,
        "checked_at": datetime.now().isoformat(),
        "perf_window_start": window_start,
        "baseline_wr": round(_baseline_wr(), 4),
        "signals": [{"severity": sv, "code": c, "detail": d}
                    for sv, c, d in signals],
    }
    _save_health(result)

    if status != "HEALTHY":
        lvl = "ERROR" if status == "DEGRADED" else "WARN"
        log(lvl, f"model_health: {status} — " +
            "; ".join(s[2] for s in signals[:3]))
    return result


def reset_performance_window():
    """Llamar cuando se ADOPTA un ensemble nuevo: los trades anteriores ya no
    describen al modelo actual. La ventana de performance arranca de cero."""
    h = _load_health()
    h["perf_window_start"] = datetime.now().isoformat()
    if h.get("status") == "DEGRADED":
        h["status"] = "WATCH"  # en observacion hasta juntar trades nuevos
    _save_health(h)
    log("INFO", "model_health: ventana de performance reseteada (ensemble nuevo)")


def current_status() -> str:
    if os.environ.get("CRYPTO_DRIFT_GUARD", "").lower() in ("off", "0", "false"):
        return "DISABLED"
    h = _load_health()
    if not h.get("status"):
        return "HEALTHY"  # nunca evaluado: fail-open
    try:
        age_h = (datetime.now() - datetime.fromisoformat(h["checked_at"])).total_seconds() / 3600
        if age_h > 48:
            return "HEALTHY"  # evaluacion vieja: no bloquear con datos rancios
    except Exception:
        pass
    return h["status"]


def is_ml_trusted() -> bool:
    """False solo cuando hay evidencia de que el ensemble dejo de predecir."""
    return current_status() != "DEGRADED"


def status_line() -> str:
    st = current_status()
    if st == "DISABLED":
        return "drift guard desactivado (CRYPTO_DRIFT_GUARD=off)"
    h = _load_health()
    if not h.get("signals"):
        return f"{st}"
    return f"{st} ({'; '.join(s['detail'] for s in h['signals'][:2])})"


def report() -> str:
    res = evaluate()
    lines = [
        "",
        "  " + "=" * 60,
        "  MODEL HEALTH / DRIFT GUARD",
        "  " + "=" * 60,
        f"  Estado:        {res['status']}",
        f"  Baseline WR:   {res['baseline_wr']:.0%} (test OOS del entrenamiento)",
        f"  Ventana perf.: desde {res['perf_window_start'][:19]}",
        f"  Evaluado:      {res['checked_at'][:19]}",
    ]
    if res["signals"]:
        lines.append("  Señales:")
        for s in res["signals"]:
            lines.append(f"    [{s['severity']:<8}] {s['code']}: {s['detail']}")
    else:
        lines.append("  Señales:       ninguna — sin evidencia de drift")
    lines += [
        "  " + "-" * 60,
        "  DEGRADED => el runner no abre trades del Modelo D (el ensemble",
        "  no es confiable) y forever adelanta el retrain con quality gate.",
        "  " + "=" * 60,
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(report())
