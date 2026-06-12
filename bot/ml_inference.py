"""
ml_inference.py — Conector entre los modelos entrenados (XGB / RF / Hybrid)
y el bot en vivo.

Carga los .pkl producidos por model_d_training/train_full.py, computa las
features extendidas en vivo (reutilizando features_extended.compute_features)
y emite un veredicto de ensemble usado por bot/runner.py como validador final
antes de ejecutar un trade.

Flujo:
  1. predict(symbol) baja velas 1m del symbol + BTC + ETH desde Binance,
     agrega a 5m/1h/4h en memoria, lee F&G/macro/funding desde
     data_extended.db (cacheado 5 min).
  2. Llama features_extended.compute_features() para obtener el dict de
     features. Esto garantiza alineacion exacta con lo que se entreno.
  3. Para cada modelo cargado, hace predict_proba y compara contra su
     threshold (leido desde xgb_best.json, rf_best.json, hybrid_best.json).
  4. Devuelve un veredicto de ensemble:
       FULL     -> los 3 modelos dicen GO
       HALF     -> mayoria (>=2/3) dice GO
       WATCH    -> 1/3 dice GO
       ABORT    -> ninguno dice GO

Cache:
  - Modelos cargados al primer uso, despues mantenidos en memoria.
  - Auxiliares (F&G, macro) refrescados cada 5 minutos.
  - Funding por par cargado on-demand.

Si los .pkl no existen, predict() devuelve {"decision":"UNKNOWN"} y el bot
opera normalmente sin ML (solo gate). Esto preserva compatibilidad si el
training nunca corrio.
"""

import os
import sys
import time
import json
import pickle
import sqlite3
import urllib.request
import urllib.parse
from datetime import datetime, timezone

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bot.logger import log

# Reuso de funciones de features_extended (mismo codigo que entrenamos)
from model_d_training.features_extended import (
    compute_features,
    aggregate,
    build_index_map,
    load_fng_map,
    load_macro_map,
    load_funding_map,
)

RESULTS_DIR = os.path.join(ROOT, "model_d_training", "results")
DB_PATH = os.path.join(ROOT, "model_d_training", "state", "data_extended.db")

# Cache global
_models_cache = {}
_aux_cache = None
_aux_cache_ts = 0.0
AUX_TTL_SEC = 300  # refrescar fng/macro cada 5 min
_funding_cache = {}


# ── Carga de modelos ─────────────────────────────────────────────────────

def _load_model(filename, json_basename):
    """
    filename: 'xgb_models.pkl' | 'rf_model.pkl' | 'hybrid_model.pkl'
    json_basename: 'xgb_best.json' | 'rf_best.json' | 'hybrid_best.json'
    """
    if filename in _models_cache:
        return _models_cache[filename]

    pkl_path = os.path.join(RESULTS_DIR, filename)
    json_path = os.path.join(RESULTS_DIR, json_basename)

    if not os.path.exists(pkl_path):
        log("WARN", f"ml_inference: no existe {pkl_path}")
        _models_cache[filename] = None
        return None

    try:
        with open(pkl_path, "rb") as f:
            data = pickle.load(f)
    except Exception as e:
        log("WARN", f"ml_inference: error cargando {pkl_path}: {e}")
        _models_cache[filename] = None
        return None

    meta = {}
    if os.path.exists(json_path):
        try:
            with open(json_path) as f:
                meta = json.load(f)
        except Exception:
            pass

    feature_cols = data.get("feature_cols") or meta.get("feature_cols") or []
    # Un modelo sin features es un artefacto guardado "solo para diagnostico"
    # (descartado por el quality gate del entrenamiento). No puede predecir:
    # ignorarlo para que no aparezca como cargado en los logs.
    if not feature_cols:
        log("WARN", f"ml_inference: {filename} sin feature_cols "
                    f"(descartado en entrenamiento) — ignorado")
        _models_cache[filename] = None
        return None
    # El JSON tiene prioridad sobre el .pkl para el threshold, para que el
    # usuario pueda ajustarlo manualmente editando solo xgb_best.json sin
    # re-entrenar el modelo entero.
    threshold = meta.get("threshold")
    if threshold is None:
        threshold = data.get("threshold", 0.5)

    _models_cache[filename] = {
        "data": data,
        "threshold": float(threshold),
        "feature_cols": list(feature_cols),
        "loaded_at": datetime.now().isoformat(),
    }
    log("INFO", f"ml_inference: cargado {filename} (thr={threshold:.3f}, {len(feature_cols)} features)")
    return _models_cache[filename]


def _load_all_models():
    """Carga los tres modelos. Devuelve dict {short_name: info or None}."""
    return {
        "xgb":    _load_model("xgb_models.pkl",   "xgb_best.json"),
        "rf":     _load_model("rf_model.pkl",     "rf_best.json"),
        "hybrid": _load_model("hybrid_model.pkl", "hybrid_best.json"),
    }


def reload_models():
    """
    Limpia el cache de modelos para que se recarguen con los thresholds
    actuales desde los JSON (xgb_best.json, rf_best.json, hybrid_best.json).
    Útil cuando se editan los thresholds manualmente sin reiniciar el proceso.
    """
    global _models_cache
    _models_cache = {}
    log("INFO", "ml_inference: cache de modelos limpiado — se recargarán en próxima predicción")


# ── Cache de datos auxiliares ────────────────────────────────────────────

def _ensure_aux_loaded():
    global _aux_cache, _aux_cache_ts
    now = time.time()
    if _aux_cache and (now - _aux_cache_ts) < AUX_TTL_SEC:
        return _aux_cache

    if not os.path.exists(DB_PATH):
        log("WARN", f"ml_inference: data_extended.db no existe en {DB_PATH}, macro=0")
        _aux_cache = {"fng": [], "macro": {}}
    else:
        con = sqlite3.connect(DB_PATH)
        try:
            _aux_cache = {
                "fng":   load_fng_map(con),
                "macro": load_macro_map(con),
            }
        finally:
            con.close()
    _aux_cache_ts = now
    return _aux_cache


def _get_funding_for(pair):
    if pair in _funding_cache:
        # refresh cada 1h
        fcache, fts = _funding_cache[pair]
        if (time.time() - fts) < 3600:
            return fcache
    if not os.path.exists(DB_PATH):
        return []
    con = sqlite3.connect(DB_PATH)
    try:
        rows = load_funding_map(con, pair)
    finally:
        con.close()
    _funding_cache[pair] = (rows, time.time())
    return rows


# ── Fetch de velas con formato extendido ─────────────────────────────────

BINANCE_KLINES = "https://api.binance.com/api/v3/klines"


def _fetch_klines_paged(symbol, interval="1m", total_limit=10080):
    """
    Baja `total_limit` velas paginando en chunks de 1000 (limite de Binance).
    Devuelve formato extendido (con taker_buy_base, quote_vol, trades).

    Default 10080 velas 1m = 7 dias, suficiente para drawdown_7d y mom_24h
    como en training.
    """
    all_bars = []
    remaining = total_limit
    end_ms = None  # primera pagina sin endTime = velas mas recientes
    max_pages = 15  # cota de seguridad

    for _ in range(max_pages):
        if remaining <= 0:
            break
        batch = min(remaining, 1000)
        params = {"symbol": symbol, "interval": interval, "limit": batch}
        if end_ms is not None:
            params["endTime"] = end_ms
        url = BINANCE_KLINES + "?" + urllib.parse.urlencode(params)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ml_inference/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = json.loads(resp.read())
        except Exception as e:
            log("WARN", f"ml_inference: fetch klines {symbol} {interval} fallo: {e}")
            break

        if not raw:
            break

        # raw viene en orden ascendente (mas viejo primero)
        chunk = []
        for b in raw:
            chunk.append({
                "ts": int(b[0]), "o": float(b[1]), "h": float(b[2]),
                "l": float(b[3]), "c": float(b[4]), "v": float(b[5]),
                "qv": float(b[7]), "tr": int(b[8]),
                "tbb": float(b[9]), "tbq": float(b[10]),
            })
        # Anteponer al resultado (las paginas anteriores son las mas viejas)
        all_bars = chunk + all_bars
        remaining -= len(chunk)
        if len(chunk) < batch:
            break  # no hay mas historico
        end_ms = chunk[0]["ts"] - 1  # siguiente pagina termina antes de la actual
        time.sleep(0.05)  # respeto rate limit

    return all_bars


def _fetch_klines_extended(symbol, interval="1m", limit=300):
    """Wrapper de compatibilidad. Para inferencia usar _fetch_klines_paged."""
    return _fetch_klines_paged(symbol, interval, limit)


# ── Predict ──────────────────────────────────────────────────────────────

# Cache BTC y ETH (validos por 60 segundos)
_btc_cache = None
_btc_cache_ts = 0.0
_eth_cache = None
_eth_cache_ts = 0.0
REF_TTL_SEC = 60


# Cantidad de velas 1m a bajar por evaluacion.
# 10080 = 7 dias, lo necesario para drawdown_7d, vol_zscore_7d y mom_24h
# tal como se calcularon en training.
LIVE_BARS_1M = 10080


def _get_btc():
    global _btc_cache, _btc_cache_ts
    if _btc_cache and (time.time() - _btc_cache_ts) < REF_TTL_SEC:
        return _btc_cache
    bars = _fetch_klines_paged("BTCUSDT", "1m", LIVE_BARS_1M)
    if bars:
        _btc_cache = bars
        _btc_cache_ts = time.time()
    return bars


def _get_eth():
    global _eth_cache, _eth_cache_ts
    if _eth_cache and (time.time() - _eth_cache_ts) < REF_TTL_SEC:
        return _eth_cache
    bars = _fetch_klines_paged("ETHUSDT", "1m", LIVE_BARS_1M)
    if bars:
        _eth_cache = bars
        _eth_cache_ts = time.time()
    return bars


def compute_features_live(symbol):
    """Calcula el vector de features en vivo para el symbol dado."""
    bars_1m = _fetch_klines_paged(symbol, "1m", LIVE_BARS_1M)
    if not bars_1m or len(bars_1m) < 1800:
        log("WARN", f"ml_inference: {symbol} solo {len(bars_1m) if bars_1m else 0} velas 1m disponibles")
        return None

    btc_1m = _get_btc() if symbol != "BTCUSDT" else bars_1m
    eth_1m = _get_eth() if symbol != "ETHUSDT" else bars_1m
    if not btc_1m or not eth_1m:
        return None

    bars_5m = aggregate(bars_1m, 5)
    bars_1h = aggregate(bars_1m, 60)
    bars_4h = aggregate(bars_1m, 240)
    ts_idx_5m = build_index_map(bars_5m)
    ts_idx_1h = build_index_map(bars_1h)
    ts_idx_4h = build_index_map(bars_4h)

    btc_1h = aggregate(btc_1m, 60)
    btc_1h_closes = [b["c"] for b in btc_1h]
    btc_1m_closes = [b["c"] for b in btc_1m]
    eth_1h = aggregate(eth_1m, 60)
    eth_1h_closes = [b["c"] for b in eth_1h]

    aux = _ensure_aux_loaded()
    funding_arr = _get_funding_for(symbol)

    idx = len(bars_1m) - 1
    try:
        feats = compute_features(
            bars_1m, idx, bars_5m, ts_idx_5m, bars_1h, ts_idx_1h, bars_4h, ts_idx_4h,
            btc_1h_closes, eth_1h_closes, aux["fng"], aux["macro"], funding_arr,
            symbol, btc_1m_closes,
        )
    except Exception as e:
        log("WARN", f"ml_inference: compute_features {symbol} fallo: {e}")
        return None

    return feats


def _model_predict_proba(info, feats_dict):
    """Aplica un modelo a un dict de features."""
    cols = info["feature_cols"]
    if not cols:
        return None
    X = np.array([[float(feats_dict.get(c, 0) or 0) for c in cols]], dtype=np.float32)
    data = info["data"]

    try:
        if "scaler" in data:
            # hybrid: (model, scaler)
            X = data["scaler"].transform(X)
            prob = float(data["model"].predict_proba(X)[0, 1])
        else:
            model = data.get("model") or data.get("xgb_model") or data
            prob = float(model.predict_proba(X)[0, 1])
        return prob
    except Exception as e:
        log("WARN", f"ml_inference: predict_proba fallo: {e}")
        return None


def predict(symbol):
    """
    Devuelve un dict con la prediccion ensemble:
      {
        "decision":  "FULL" | "HALF" | "WATCH" | "ABORT" | "UNKNOWN",
        "votes":     "n/total",
        "details":   { "xgb": {prob, threshold, go}, "rf": {...}, "hybrid": {...} },
      }
    """
    models = _load_all_models()
    loaded = {k: v for k, v in models.items() if v is not None}
    if not loaded:
        return {"decision": "UNKNOWN", "reason": "no hay modelos cargados"}

    feats = compute_features_live(symbol)
    if feats is None:
        return {"decision": "UNKNOWN", "reason": "features no disponibles"}

    details = {}
    votes = 0
    total = 0
    for name, info in loaded.items():
        prob = _model_predict_proba(info, feats)
        if prob is None:
            continue
        thr = info["threshold"]
        go = prob >= thr
        details[name] = {"prob": round(prob, 4), "threshold": thr, "go": go}
        total += 1
        if go:
            votes += 1

    if total == 0:
        return {"decision": "UNKNOWN", "reason": "no se pudo evaluar ningun modelo"}

    if votes == total:
        decision = "FULL"
    elif votes >= (total // 2) + 1:
        decision = "HALF"
    elif votes >= 1:
        decision = "WATCH"
    else:
        decision = "ABORT"

    return {
        "decision": decision,
        "votes":    f"{votes}/{total}",
        "details":  details,
    }


# ── CLI util para testear desde terminal ─────────────────────────────────

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol", help="Par a evaluar (ej. BTCUSDT)")
    args = ap.parse_args()

    sym = args.symbol.upper()
    if not sym.endswith("USDT"):
        sym += "USDT"

    log("INFO", f"Evaluando {sym}...")
    result = predict(sym)
    print(json.dumps(result, indent=2))
