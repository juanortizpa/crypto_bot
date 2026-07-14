"""
Market Regime — catalogo de COMPORTAMIENTOS del mercado y clasificador diario.

Idea (regime-first): en vez de predecir resultados directamente sobre todo el
historico, primero se clasifica COMO se esta comportando el mercado hoy, y
las predicciones de resultados se condicionan a ese comportamiento:

  1. CATALOGO — se aprenden K comportamientos tipicos clusterizando (k-means)
     vectores diarios de estado del mercado desde 2024 HASTA HOY (velas 1d de
     Binance, se re-aprende cada semana: el catalogo nunca se queda viejo).
     Cada dia se describe con ~11 numeros: tendencia/vol/RSI/drawdown de BTC,
     amplitud del mercado (% de pares sobre su MA20), retorno y dispersion de
     las alts, correlacion media alt-BTC, volumen relativo.

  2. CLASIFICACION DIARIA — el dia actual se asigna al comportamiento mas
     cercano del catalogo y se responde exactamente lo que pide la operacion:
       SAME          -> seguimos en el mismo comportamiento de ayer
       KNOWN_SHIFT   -> cambiamos a un comportamiento YA VISTO antes
       NEW_BEHAVIOR  -> el dia de hoy NO se parece a nada del catalogo
                        (distancia al cluster mas cercano > p95 historico):
                        el mercado esta haciendo algo que los modelos nunca
                        vieron -> no confiar en predicciones de resultados.

  3. CONDICIONAMIENTO — el resto del bot usa la etiqueta:
       - Cada prediccion se graba con su regimen (columna `regime`): al final
         del mes se sabe QUE comportamientos son rentables y cuales no.
       - runner: en NEW_BEHAVIOR no se abren trades del Modelo D (su ML se
         entreno en comportamientos que hoy no aplican).
       - meta_model: al reentrenar, los trades de comportamientos DISTINTOS
         al actual pesan menos (sample_weight) — "descartar valores de un
         comportamiento anterior que ya no esta sucediendo".
       - model_health: dias NEW_BEHAVIOR sostenidos son señal de drift.

El clasificador en vivo es matematica pura sobre un JSON (centroides +
media/desv del estandarizado): no necesita sklearn ni pickle, y leer el
regimen del dia (para runner/predict) no toca la red — lo escribe forever
una vez al dia.

CLI:  python bot_crypto.py regime          (clasifica hoy + stats por regimen)
      python bot_crypto.py regime --fit    (re-aprende el catalogo)
"""
import os
import sys
import json
import math
import random
import sqlite3
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bot.logger import log

STATE_DIR = os.path.join(ROOT, "state")
MODEL_JSON = os.path.join(STATE_DIR, "regime_model.json")
HISTORY_JSON = os.path.join(STATE_DIR, "regime_history.json")
PRED_DB = os.path.join(STATE_DIR, "crypto_predictions.db")

K_REGIMES = int(os.environ.get("CRYPTO_REGIME_K", "6"))
NOVELTY_RATIO = float(os.environ.get("CRYPTO_REGIME_NOVELTY_RATIO", "1.30"))
FIT_DAYS = int(os.environ.get("CRYPTO_REGIME_FIT_DAYS", "1000"))  # ~2.7 anios
HISTORY_KEEP = 180

# Pares usados para medir la "amplitud" del mercado (subset liquido del TOP20)
BREADTH_PAIRS = [
    "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT",
    "AVAXUSDT", "DOTUSDT", "LINKUSDT", "DOGEUSDT", "NEARUSDT",
]

FEATURE_NAMES = [
    "btc_ret_1d", "btc_vol30", "btc_dist_ma20", "btc_dist_ma50",
    "btc_rsi14", "btc_dd90", "btc_volratio20",
    "breadth_ma20", "alts_ret7_mean", "alts_ret7_std", "corr30_mean",
]

WARMUP = 90  # dias necesarios antes del primer vector


# ══════════════════════════════════════════════════════════════════════════
# Construccion de vectores de comportamiento
# ══════════════════════════════════════════════════════════════════════════

def _rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains = losses = 0.0
    for i in range(len(closes) - period, len(closes)):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100 - 100 / (1 + rs)


def _corr(xs, ys):
    n = len(xs)
    if n < 3 or n != len(ys):
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return 0.0
    return sxy / math.sqrt(sxx * syy)


def _day_key(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def build_daily_vectors(limit: int = FIT_DAYS):
    """
    Baja velas 1d de BTC + pares de amplitud y construye (fechas, matriz).
    Cada fila describe el comportamiento del mercado en UN dia, usando solo
    informacion disponible hasta ese dia (sin lookahead).
    """
    from bot.crypto_data import get_bars

    btc = get_bars("BTCUSDT", "1d", limit)
    if not btc or len(btc) < WARMUP + 10:
        return [], []

    pair_bars = {}
    for p in BREADTH_PAIRS:
        try:
            bars = get_bars(p, "1d", limit)
            if bars and len(bars) >= 40:
                pair_bars[p] = {_day_key(b["t"]): b for b in bars}
        except Exception:
            continue

    # Series de closes por par alineadas a las fechas de BTC
    btc_days = [_day_key(b["t"]) for b in btc]
    pair_closes = {}
    for p, by_day in pair_bars.items():
        closes = []
        for d in btc_days:
            b = by_day.get(d)
            closes.append(b["c"] if b else None)
        pair_closes[p] = closes

    btc_closes = [b["c"] for b in btc]
    btc_vols = [b["v"] for b in btc]

    dates, matrix = [], []
    for i in range(WARMUP, len(btc)):
        c = btc_closes
        price = c[i]
        ret_1d = (c[i] / c[i - 1] - 1) * 100

        rets30 = [math.log(c[j] / c[j - 1]) for j in range(i - 29, i + 1)]
        m30 = sum(rets30) / len(rets30)
        var30 = sum((r - m30) ** 2 for r in rets30) / (len(rets30) - 1)
        vol30 = math.sqrt(var30) * math.sqrt(365) * 100

        ma20 = sum(c[i - 19:i + 1]) / 20
        ma50 = sum(c[i - 49:i + 1]) / 50
        dist_ma20 = (price / ma20 - 1) * 100
        dist_ma50 = (price / ma50 - 1) * 100
        rsi14 = _rsi(c[max(0, i - 20):i + 1], 14)
        high90 = max(c[i - 89:i + 1])
        dd90 = (price / high90 - 1) * 100
        avg_vol20 = sum(btc_vols[i - 20:i]) / 20
        volratio = btc_vols[i] / avg_vol20 if avg_vol20 > 0 else 1.0

        # Amplitud del mercado (alts)
        above = total = 0
        rets7 = []
        corrs = []
        btc_rets30 = [(c[j] / c[j - 1] - 1) for j in range(i - 29, i + 1)]
        for p, closes in pair_closes.items():
            window = closes[max(0, i - 60):i + 1]
            if closes[i] is None or any(v is None for v in window[-30:]):
                continue
            total += 1
            pma20 = sum(v for v in closes[i - 19:i + 1]) / 20 \
                if all(v is not None for v in closes[i - 19:i + 1]) else None
            if pma20 and closes[i] > pma20:
                above += 1
            if closes[i - 7] and closes[i - 7] > 0:
                rets7.append((closes[i] / closes[i - 7] - 1) * 100)
            alt_rets30 = [(closes[j] / closes[j - 1] - 1)
                          for j in range(i - 29, i + 1)
                          if closes[j] is not None and closes[j - 1]]
            if len(alt_rets30) == 30:
                corrs.append(_corr(alt_rets30, btc_rets30))

        breadth = (above / total * 100) if total else 50.0
        ret7_mean = sum(rets7) / len(rets7) if rets7 else 0.0
        if len(rets7) >= 2:
            m7 = ret7_mean
            ret7_std = math.sqrt(sum((r - m7) ** 2 for r in rets7) / (len(rets7) - 1))
        else:
            ret7_std = 0.0
        corr_mean = sum(corrs) / len(corrs) if corrs else 0.7

        dates.append(btc_days[i])
        matrix.append([ret_1d, vol30, dist_ma20, dist_ma50, rsi14, dd90,
                       volratio, breadth, ret7_mean, ret7_std, corr_mean])

    return dates, matrix


# ══════════════════════════════════════════════════════════════════════════
# K-means propio (sin sklearn, sin pickle: el modelo es un JSON)
# ══════════════════════════════════════════════════════════════════════════

def _dist2(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b))


def _kmeans(X, k, seed=42, iters=60, restarts=5):
    """Lloyd con init k-means++. Retorna (centroids, labels, inertia)."""
    best = None
    for r in range(restarts):
        rnd = random.Random(seed + r)
        # k-means++
        centroids = [list(rnd.choice(X))]
        while len(centroids) < k:
            d2 = [min(_dist2(x, c) for c in centroids) for x in X]
            total = sum(d2)
            if total <= 0:
                centroids.append(list(rnd.choice(X)))
                continue
            pick = rnd.random() * total
            acc = 0.0
            for x, d in zip(X, d2):
                acc += d
                if acc >= pick:
                    centroids.append(list(x))
                    break
        labels = [0] * len(X)
        for _ in range(iters):
            changed = False
            for i, x in enumerate(X):
                j = min(range(k), key=lambda c: _dist2(x, centroids[c]))
                if labels[i] != j:
                    labels[i] = j
                    changed = True
            for j in range(k):
                members = [X[i] for i in range(len(X)) if labels[i] == j]
                if members:
                    centroids[j] = [sum(col) / len(members)
                                    for col in zip(*members)]
            if not changed:
                break
        inertia = sum(_dist2(x, centroids[labels[i]]) for i, x in enumerate(X))
        if best is None or inertia < best[2]:
            best = (centroids, labels, inertia)
    return best


def _standardize(matrix):
    cols = list(zip(*matrix))
    means = [sum(c) / len(c) for c in cols]
    stds = []
    for c, m in zip(cols, means):
        v = sum((x - m) ** 2 for x in c) / max(1, len(c) - 1)
        stds.append(math.sqrt(v) or 1.0)
    Z = [[(x - m) / s for x, m, s in zip(row, means, stds)] for row in matrix]
    return Z, means, stds


def _auto_label(centroid_z):
    """Nombre descriptivo del comportamiento a partir del centroide (z)."""
    idx = {n: i for i, n in enumerate(FEATURE_NAMES)}
    t = centroid_z[idx["btc_dist_ma50"]]
    v = centroid_z[idx["btc_vol30"]]
    b = centroid_z[idx["breadth_ma20"]]
    trend = "ALCISTA" if t > 0.4 else ("BAJISTA" if t < -0.4 else "LATERAL")
    vol = "VOL_ALTA" if v > 0.4 else ("VOL_BAJA" if v < -0.4 else "VOL_MEDIA")
    extra = "_ALTSEASON" if b > 0.8 else ("_SOLO_BTC" if b < -0.8 else "")
    return f"{trend}_{vol}{extra}"


# ══════════════════════════════════════════════════════════════════════════
# Fit / persistencia
# ══════════════════════════════════════════════════════════════════════════

def fit_from_vectors(dates, matrix, k: int = K_REGIMES) -> dict | None:
    """Aprende el catalogo desde vectores ya construidos (testeable offline)."""
    if len(matrix) < max(120, k * 20):
        log("WARN", f"market_regime: solo {len(matrix)} dias — insuficiente para fit")
        return None
    Z, means, stds = _standardize(matrix)
    centroids, labels, inertia = _kmeans(Z, k)

    # p95 de distancia intra-cluster: umbral de "esto ya no se parece a nada"
    p95 = []
    shares = []
    for j in range(k):
        dists = sorted(math.sqrt(_dist2(Z[i], centroids[j]))
                       for i in range(len(Z)) if labels[i] == j)
        p95.append(dists[int(0.95 * (len(dists) - 1))] if dists else 1.0)
        shares.append(round(100.0 * len(dists) / len(Z), 1))

    model = {
        "fitted_at": datetime.now().isoformat(),
        "k": k,
        "n_days": len(matrix),
        "date_from": dates[0] if dates else None,
        "date_to": dates[-1] if dates else None,
        "feature_names": FEATURE_NAMES,
        "means": means,
        "stds": stds,
        "centroids": centroids,
        "p95_dist": p95,
        "share_pct": shares,
        "labels": [_auto_label(c) for c in centroids],
    }
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = MODEL_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(model, f, indent=2)
    os.replace(tmp, MODEL_JSON)
    log("INFO", f"market_regime: catalogo aprendido — {len(matrix)} dias "
                f"({model['date_from']}→{model['date_to']}), k={k}: "
                + ", ".join(f"{l} {s}%" for l, s in zip(model["labels"], shares)))
    return model


def fit(k: int = K_REGIMES) -> dict | None:
    """Aprende el catalogo desde Binance (2024 → HOY). Corre semanal."""
    dates, matrix = build_daily_vectors(FIT_DAYS)
    if not matrix:
        log("WARN", "market_regime: sin datos de Binance para el fit")
        return None
    return fit_from_vectors(dates, matrix, k)


def load_model() -> dict | None:
    try:
        with open(MODEL_JSON, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════
# Clasificacion
# ══════════════════════════════════════════════════════════════════════════

def _load_history() -> dict:
    try:
        with open(HISTORY_JSON, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_history(h: dict):
    try:
        keys = sorted(h.keys())[-HISTORY_KEEP:]
        h = {k: h[k] for k in keys}
        tmp = HISTORY_JSON + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(h, f, indent=2)
        os.replace(tmp, HISTORY_JSON)
    except Exception as e:
        log("WARN", f"market_regime: no se pudo guardar historia: {e}")


def classify_vector(vector, model: dict, prev_regime=None) -> dict:
    """Clasifica un vector de comportamiento (matematica pura, testeable)."""
    z = [(x - m) / s for x, m, s in
         zip(vector, model["means"], model["stds"])]
    dists = [math.sqrt(_dist2(z, c)) for c in model["centroids"]]
    j = min(range(len(dists)), key=lambda i: dists[i])
    ratio = dists[j] / (model["p95_dist"][j] or 1.0)

    if ratio > NOVELTY_RATIO:
        status = "NEW_BEHAVIOR"
    elif prev_regime is None or prev_regime == j:
        status = "SAME"
    else:
        status = "KNOWN_SHIFT"

    return {
        "regime": j,
        "label": model["labels"][j],
        "distance_ratio": round(ratio, 3),
        "share_pct": model["share_pct"][j],
        "status": status,
    }


def classify_today() -> dict | None:
    """Construye el vector de HOY (red), lo clasifica y persiste en historia."""
    model = load_model()
    if not model:
        log("WARN", "market_regime: no hay catalogo — correr `regime --fit` primero")
        return None
    dates, matrix = build_daily_vectors(140)  # warmup 90 + margen
    if not matrix:
        return None

    hist = _load_history()
    prev = None
    for d in sorted(hist.keys(), reverse=True):
        if d < dates[-1]:
            prev = hist[d].get("regime")
            break

    res = classify_vector(matrix[-1], model, prev_regime=prev)
    res["date"] = dates[-1]
    hist[dates[-1]] = {"regime": res["regime"], "label": res["label"],
                       "status": res["status"],
                       "distance_ratio": res["distance_ratio"],
                       "classified_at": datetime.now().isoformat()}
    _save_history(hist)
    log("INFO", f"market_regime: {dates[-1]} -> {res['label']} "
                f"[{res['status']}] (dist {res['distance_ratio']:.2f}x)")
    return res


# ── Lecturas baratas (sin red) para runner / predict / model_health ──────

def _latest_entry(max_age_days: float = 2.5):
    hist = _load_history()
    if not hist:
        return None
    last_day = max(hist.keys())
    try:
        age = (datetime.now(timezone.utc)
               - datetime.strptime(last_day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
               ).total_seconds() / 86400
        if age > max_age_days:
            return None  # clasificacion vieja: no fiarse
    except Exception:
        return None
    return hist[last_day]


def today_status() -> str | None:
    """SAME | KNOWN_SHIFT | NEW_BEHAVIOR | None (sin clasificacion fresca)."""
    e = _latest_entry()
    return e.get("status") if e else None


def current_regime_label() -> str | None:
    e = _latest_entry()
    return e.get("label") if e else None


def recent_novelty(days: int = 3) -> int:
    """Cuantos de los ultimos `days` dias clasificados fueron NEW_BEHAVIOR."""
    hist = _load_history()
    recent = sorted(hist.keys())[-days:]
    return sum(1 for d in recent if hist[d].get("status") == "NEW_BEHAVIOR")


# ══════════════════════════════════════════════════════════════════════════
# Stats por regimen + reporte
# ══════════════════════════════════════════════════════════════════════════

def regime_trade_stats() -> list:
    """WR / expectancy de los trades cerrados agrupados por regimen."""
    try:
        con = sqlite3.connect(PRED_DB, timeout=30)
        con.row_factory = sqlite3.Row
        rows = con.execute("""
            SELECT COALESCE(regime,'(sin etiqueta)') rg,
                   COUNT(*) n,
                   SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) wins,
                   ROUND(AVG(pnl_pct), 3) exp
            FROM predictions
            WHERE outcome IN ('WIN','LOSS')
            GROUP BY rg ORDER BY n DESC
        """).fetchall()
        con.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def report(do_fit: bool = False) -> str:
    lines = ["", "  " + "=" * 62, "  MARKET REGIME — catalogo de comportamientos",
             "  " + "=" * 62]
    model = load_model()
    if do_fit or not model:
        lines.append("  Aprendiendo catalogo desde Binance (esto tarda ~1 min)...")
        print("\n".join(lines))
        lines = []
        model = fit()
        if not model:
            return "  No se pudo aprender el catalogo (¿sin red?)\n"

    lines.append(f"  Catalogo: {model['n_days']} dias "
                 f"({model['date_from']} → {model['date_to']}), "
                 f"k={model['k']} · aprendido {model['fitted_at'][:16]}")
    lines.append("  Comportamientos conocidos:")
    for i, (lab, sh) in enumerate(zip(model["labels"], model["share_pct"])):
        lines.append(f"    R{i} {lab:<28} {sh:>5.1f}% de los dias")

    res = classify_today()
    if res:
        icon = {"SAME": "(continua)", "KNOWN_SHIFT": "(cambio a uno YA VISTO)",
                "NEW_BEHAVIOR": ">>> COMPORTAMIENTO NUEVO <<<"}[res["status"]]
        lines += [
            "  " + "-" * 62,
            f"  HOY {res['date']}: R{res['regime']} {res['label']} {icon}",
            f"  Distancia al comportamiento: {res['distance_ratio']:.2f}x "
            f"(>{NOVELTY_RATIO:.2f}x = nunca visto)",
        ]

    stats = regime_trade_stats()
    if stats:
        lines += ["  " + "-" * 62, "  Rentabilidad por comportamiento (trades cerrados):"]
        for s in stats:
            wr = 100.0 * s["wins"] / s["n"] if s["n"] else 0
            lines.append(f"    {s['rg']:<32} {s['n']:>4} trades  "
                         f"WR {wr:5.1f}%  exp {s['exp']:+.3f}%")
    lines += [
        "  " + "-" * 62,
        "  NEW_BEHAVIOR => runner no abre Modelo D y el drift guard lo",
        "  cuenta como señal. El catalogo se re-aprende cada 7 dias.",
        "  " + "=" * 62, "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(report(do_fit="--fit" in sys.argv))
