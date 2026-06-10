"""
train_directional.py — ¿Los factores actuales predicen BAJADAS o solo subidas?

Entrena DOS clasificadores con exactamente los mismos 13 factores del bot:
    LONG : P(precio sube a +target antes de caer a -stop)
    SHORT: P(precio baja a -target antes de subir a +stop)

y los valida con WALK-FORWARD (entrenar en pasado, probar en futuro,
con embargo de max_hours para evitar fuga de datos por labels forward).

Esto responde empiricamente la pregunta: si el AUC/expectancy del modelo
SHORT es comparable al del LONG, los factores SI sirven para predecir
bajadas (los features son simetricos: RSI alto + momentum negativo +
distancia sobre MA50 son señales bajistas igual que sus opuestos son
alcistas). Lo que era long-only no eran los factores, era el PIPELINE:
labels, gate y modelos A-F solo simulaban compras.

Metricas con comisiones incluidas (0.25% round-trip). Sin numeros inflados:
    - TIMEOUT con pnl ~0 NO cuenta como WIN
    - ambos niveles tocados en la misma vela => LOSS (peor caso)

Salidas:
    results/directional_report.json   — metricas por fold y veredicto
    results/directional_models.pkl    — modelos LONG y SHORT entrenados

Uso (desde la raiz del proyecto, con el venv activado):
    python -m model_d_training.train_directional
"""
import os
import sys
import json
import pickle
import sqlite3
from datetime import datetime, timezone

ROOT_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_PARENT)

from bot.top20_pairs import TOP_20
from model_d_training.features import (
    sma, rsi, atr, bisect_le,
    load_pair_bars, load_fng_map, fng_at, compute_btc_dom_proxy,
)

DB_PATH    = os.path.join(os.path.dirname(__file__), "state", "data_2026.db")
OUT_JSON   = os.path.join(os.path.dirname(__file__), "results", "directional_report.json")
OUT_PKL    = os.path.join(os.path.dirname(__file__), "results", "directional_models.pkl")

FEE_RT_PCT = 0.25          # comisiones + slippage round-trip, en %
SAMPLE_EVERY = 2           # 1 fila cada 2 velas 1h (controla tamano del dataset)
N_FOLDS = 5                # walk-forward folds

# Combos (stop_pct, target_pct, max_hours) — simetricos para long y short
COMBOS = [
    (0.025, 0.040, 8),
    (0.020, 0.030, 6),
]

FEATURE_COLS = [
    "rsi14", "drawdown_7d", "runup_7d", "atr_pct", "vol_ratio",
    "mom_4h", "mom_12h", "mom_24h",
    "dist_ma20", "dist_ma50",
    "btc_trend_24h", "btc_dom_proxy", "fng_value",
    "hour_of_day",
]


# ── Simulacion de trades (ambas direcciones, criterio conservador) ───────

def simulate_long(bars, i, entry, stop_pct, target_pct, max_h):
    stop, target = entry * (1 - stop_pct), entry * (1 + target_pct)
    for h, b in enumerate(bars[i + 1: i + 1 + max_h], 1):
        hit_stop, hit_tgt = b["l"] <= stop, b["h"] >= target
        if hit_stop:                      # ambos en la misma vela => LOSS
            return "LOSS", (stop - entry) / entry * 100, h
        if hit_tgt:
            return "WIN", (target - entry) / entry * 100, h
    fwd = bars[i + 1: i + 1 + max_h]
    if not fwd:
        return "TIMEOUT", 0.0, 0
    return "TIMEOUT", (fwd[-1]["c"] - entry) / entry * 100, len(fwd)


def simulate_short(bars, i, entry, stop_pct, target_pct, max_h):
    stop, target = entry * (1 + stop_pct), entry * (1 - target_pct)
    for h, b in enumerate(bars[i + 1: i + 1 + max_h], 1):
        hit_stop, hit_tgt = b["h"] >= stop, b["l"] <= target
        if hit_stop:                      # conservador: stop primero
            return "LOSS", (entry - stop) / entry * 100, h
        if hit_tgt:
            return "WIN", (entry - target) / entry * 100, h
    fwd = bars[i + 1: i + 1 + max_h]
    if not fwd:
        return "TIMEOUT", 0.0, 0
    return "TIMEOUT", (entry - fwd[-1]["c"]) / entry * 100, len(fwd)


# ── Dataset ───────────────────────────────────────────────────────────────

def build_dataset():
    conn = sqlite3.connect(DB_PATH)
    fng_map = load_fng_map(conn)
    bars_by_pair = {p: load_pair_bars(conn, p) for p in TOP_20}
    conn.close()

    btc_bars = bars_by_pair.get("BTCUSDT", [])
    max_label_h = max(c[2] for c in COMBOS)
    rows = []

    for pair in TOP_20:
        bars = bars_by_pair[pair]
        if len(bars) < 250:
            continue
        for i in range(200, len(bars) - max_label_h - 1, SAMPLE_EVERY):
            window = bars[i - 200: i + 1]
            closes = [b["c"] for b in window]
            price, ts = closes[-1], bars[i]["ts"]

            look = min(168, len(closes))
            hi, lo = max(closes[-look:]), min(closes[-look:])
            ma20, ma50 = sma(closes, 20), sma(closes, 50)
            atr_v = atr(window, 14)
            vols = [b["v"] for b in window]
            vol_24h = sum(vols[-24:])
            vol_7d = sum(vols[-168:]) / 7 if len(vols) >= 168 else vol_24h

            btc_idx = bisect_le(btc_bars, ts)
            btc_trend = 0.0
            if btc_idx >= 24:
                btc_trend = (btc_bars[btc_idx]["c"] - btc_bars[btc_idx - 24]["c"]) / btc_bars[btc_idx - 24]["c"] * 100

            row = {
                "pair": pair, "ts": ts,
                "rsi14": round(rsi(closes, 14), 2),
                "drawdown_7d": round((price - hi) / hi * 100, 3),
                "runup_7d": round((price - lo) / lo * 100, 3),
                "atr_pct": round(atr_v / price * 100, 3) if price else 0,
                "vol_ratio": round(vol_24h / vol_7d, 3) if vol_7d > 0 else 1.0,
                "mom_4h": round((closes[-1] - closes[-5]) / closes[-5] * 100, 3),
                "mom_12h": round((closes[-1] - closes[-13]) / closes[-13] * 100, 3),
                "mom_24h": round((closes[-1] - closes[-25]) / closes[-25] * 100, 3),
                "dist_ma20": round((price - ma20) / ma20 * 100, 3) if ma20 else 0,
                "dist_ma50": round((price - ma50) / ma50 * 100, 3) if ma50 else 0,
                "btc_trend_24h": round(btc_trend, 3),
                "btc_dom_proxy": round(compute_btc_dom_proxy(bars_by_pair, ts), 2),
                "fng_value": fng_at(fng_map, ts),
                "hour_of_day": datetime.fromtimestamp(ts, tz=timezone.utc).hour,
            }
            for stop_pct, target_pct, max_h in COMBOS:
                key = f"s{int(stop_pct*1000):03d}_t{int(target_pct*1000):03d}_h{max_h}"
                for side, sim in (("long", simulate_long), ("short", simulate_short)):
                    res, pnl, held = sim(bars, i, price, stop_pct, target_pct, max_h)
                    row[f"{side}_{key}_res"] = res
                    row[f"{side}_{key}_pnl"] = round(pnl, 3)
            rows.append(row)

    return rows


# ── Walk-forward ──────────────────────────────────────────────────────────

def walk_forward(rows, side, combo_key, max_h):
    import numpy as np
    try:
        from xgboost import XGBClassifier as Clf
        clf_kwargs = dict(n_estimators=150, max_depth=3, learning_rate=0.05,
                          subsample=0.8, colsample_bytree=0.8,
                          reg_alpha=0.5, reg_lambda=1.0, eval_metric="logloss",
                          random_state=42)
    except ImportError:
        from sklearn.ensemble import GradientBoostingClassifier as Clf
        clf_kwargs = dict(n_estimators=120, max_depth=3, learning_rate=0.05,
                          random_state=42)
    from sklearn.metrics import roc_auc_score

    rows = sorted(rows, key=lambda r: r["ts"])
    ts_arr = np.array([r["ts"] for r in rows])
    X = np.array([[r[c] for c in FEATURE_COLS] for r in rows])
    y = np.array([1 if r[f"{side}_{combo_key}_res"] == "WIN" else 0 for r in rows])
    pnl = np.array([r[f"{side}_{combo_key}_pnl"] for r in rows]) - FEE_RT_PCT

    # 5 bloques de test consecutivos sobre el ultimo 50% de los datos
    n = len(rows)
    test_start0 = n // 2
    block = (n - test_start0) // N_FOLDS
    embargo_s = max_h * 3600

    folds = []
    oof_p = np.full(n, np.nan)
    last_model = None

    for k in range(N_FOLDS):
        t0 = test_start0 + k * block
        t1 = n if k == N_FOLDS - 1 else t0 + block
        # embargo: el train no puede ver bars cuyo label se solapa con el test
        train_mask = ts_arr < (ts_arr[t0] - embargo_s)
        if train_mask.sum() < 500:
            continue
        model = Clf(**clf_kwargs)
        model.fit(X[train_mask], y[train_mask])
        p = model.predict_proba(X[t0:t1])[:, 1]
        oof_p[t0:t1] = p
        last_model = model
        try:
            auc = roc_auc_score(y[t0:t1], p) if 0 < y[t0:t1].mean() < 1 else None
        except ValueError:
            auc = None
        folds.append({
            "fold": k + 1, "n_test": int(t1 - t0),
            "base_win_rate": round(float(y[t0:t1].mean()), 4),
            "auc": round(float(auc), 4) if auc else None,
        })

    # Con las probabilidades out-of-fold: barrido de umbral honesto
    mask_oof = ~np.isnan(oof_p)
    thresholds = {}
    for thr in (0.5, 0.55, 0.6, 0.65, 0.7):
        m = mask_oof & (oof_p >= thr)
        nt = int(m.sum())
        if nt < 30:
            continue
        thresholds[thr] = {
            "trades": nt,
            "win_rate": round(float(y[m].mean()) * 100, 1),
            "expectancy_pct": round(float(pnl[m].mean()), 4),
            "total_pnl_pct": round(float(pnl[m].sum()), 1),
        }

    aucs = [f["auc"] for f in folds if f["auc"]]
    return {
        "side": side, "combo": combo_key,
        "n_rows": n, "base_win_rate": round(float(y.mean()) * 100, 2),
        "folds": folds,
        "mean_auc": round(sum(aucs) / len(aucs), 4) if aucs else None,
        "thresholds_oof": thresholds,
    }, last_model


def main():
    print("Construyendo dataset (long + short)...")
    rows = build_dataset()
    print(f"Filas: {len(rows)}")
    if len(rows) < 2000:
        print("X Muy pocos datos. Revisa state/data_2026.db")
        sys.exit(1)

    report = {"generated_at": datetime.now().isoformat(),
              "fee_rt_pct": FEE_RT_PCT, "results": []}
    models = {}

    for stop_pct, target_pct, max_h in COMBOS:
        key = f"s{int(stop_pct*1000):03d}_t{int(target_pct*1000):03d}_h{max_h}"
        for side in ("long", "short"):
            print(f"\n=== {side.upper()} {key} ===")
            res, model = walk_forward(rows, side, key, max_h)
            report["results"].append(res)
            if model is not None:
                models[f"{side}_{key}"] = {"model": model, "features": FEATURE_COLS}
            print(f"  base WR: {res['base_win_rate']}%  |  AUC medio: {res['mean_auc']}")
            for thr, m in res["thresholds_oof"].items():
                print(f"  thr {thr}: {m['trades']} trades, WR {m['win_rate']}%, "
                      f"exp {m['expectancy_pct']:+.4f}%/trade (con fees)")

    # Veredicto
    def best_exp(side):
        vals = [m["expectancy_pct"]
                for r in report["results"] if r["side"] == side
                for m in r["thresholds_oof"].values()]
        return max(vals) if vals else None

    bl, bs = best_exp("long"), best_exp("short")
    print("\n" + "=" * 64)
    print("VEREDICTO (expectancy out-of-fold, con comisiones):")
    print(f"  LONG : mejor expectancy {bl:+.4f}%/trade" if bl is not None else "  LONG : sin datos")
    print(f"  SHORT: mejor expectancy {bs:+.4f}%/trade" if bs is not None else "  SHORT: sin datos")
    verdict = []
    if bs is not None and bs > 0:
        verdict.append("Los factores actuales SI contienen senal bajista explotable.")
    elif bs is not None:
        verdict.append("Senal bajista debil: el modelo SHORT no es rentable neto de fees.")
    if bl is not None and bl <= 0:
        verdict.append("OJO: el LONG tampoco es rentable neto de fees en este periodo.")
    for v in verdict:
        print("  " + v)
    report["verdict"] = verdict

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    with open(OUT_PKL, "wb") as f:
        pickle.dump(models, f)
    print(f"\nReporte: {OUT_JSON}")
    print(f"Modelos: {OUT_PKL}")
    print("\nNOTA: shorts en spot no son posibles. Para operar bajadas se")
    print("necesita Binance Futures/Margin, o usar la senal SHORT solo como")
    print("filtro de salida/no-entrada para los longs.")


if __name__ == "__main__":
    main()
