"""
Estrategias candidatas. Cada una recibe paneles (fechas x simbolos) y devuelve
una matriz de pesos W (ver convencion en engine.py). Todas usan solo datos
hasta el cierre de la vela t para decidir W[t].
"""
import numpy as np
import pandas as pd


def _eligible(close, min_hist):
    """Una moneda es operable cuando ya tiene min_hist velas de historia."""
    return close.notna().cumsum() >= min_hist


def buy_hold(close, symbols=("BTCUSDT",)):
    W = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    for s in symbols:
        W[s] = np.where(close[s].notna(), 1.0 / len(symbols), 0.0)
    return W


def equal_weight_basket(close, min_hist=30):
    el = _eligible(close, min_hist)
    return el.div(el.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)


def trend_momentum(close, *, regime_ma=100, entry_n=50, exit_n=20, mom_n=60,
                   top_k=5, vol_n=30, pos_vol=0.20, w_max=0.25, gross_max=1.0,
                   regime_symbol="BTCUSDT", exclude=(), periods_per_year=365):
    """
    Seguimiento de tendencia + momentum relativo, con filtro de regimen.

    - Regimen: solo se abre riesgo si BTC cierra sobre su media de `regime_ma`.
      Con BTC bajo la media -> 100% en USDT (asi se evitan los mercados bajistas).
    - Entrada (por moneda): cierre = maximo de `entry_n` velas (ruptura Donchian).
    - Salida (por moneda): cierre < minimo de `exit_n` velas previas, o regimen OFF.
      Es un trailing stop estructural: corta rapido lo que falla y deja correr
      lo que funciona (pocas ganadoras grandes, muchas perdedoras pequenas).
    - Seleccion: como maximo `top_k` posiciones; si hay mas candidatas entran
      las de mayor retorno en `mom_n` velas.
    - Tamano: volatilidad inversa (cada posicion aporta ~`pos_vol` de vol anual),
      tope `w_max` por moneda y `gross_max` total (sin apalancamiento).
    """
    cols = [c for c in close.columns if c not in exclude]
    c = close[cols]
    el = _eligible(c, max(entry_n, mom_n, vol_n) + 5)
    hi = c.rolling(entry_n).max()
    lo = c.rolling(exit_n).min().shift(1)
    mom = c / c.shift(mom_n) - 1
    vol = c.pct_change().rolling(vol_n).std() * np.sqrt(periods_per_year)
    reg_px = close[regime_symbol]
    regime = (reg_px > reg_px.rolling(regime_ma).mean()).values

    cv, hv, lv, mv, vv, ev = (x.values for x in (c, hi, lo, mom, vol, el))
    n, m = cv.shape
    W = np.zeros((n, m))
    held = np.zeros(m, dtype=bool)
    w_prev = np.zeros(m)
    for t in range(n):
        if not regime[t]:
            held[:] = False
            w_prev[:] = 0.0
            continue
        # salidas
        for i in range(m):
            if held[i] and (np.isnan(cv[t, i]) or cv[t, i] < lv[t, i]):
                held[i] = False
                w_prev[i] = 0.0
        # entradas
        slots = top_k - held.sum()
        if slots > 0:
            cand = [i for i in range(m)
                    if not held[i] and ev[t, i] and not np.isnan(hv[t, i])
                    and cv[t, i] >= hv[t, i] and not np.isnan(mv[t, i]) and mv[t, i] > 0]
            cand.sort(key=lambda i: mv[t, i], reverse=True)
            for i in cand[:slots]:
                held[i] = True
                v = vv[t, i]
                w_prev[i] = min(pos_vol / v, w_max) if v and v > 0 else 0.0
        w = np.where(held, w_prev, 0.0)
        g = w.sum()
        if g > gross_max:
            w = w * gross_max / g
        W[t] = w
    out = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    out[cols] = W
    return out


def ma_regime_single(close, symbol="BTCUSDT", ma=100):
    """Referencia simple: mantener `symbol` solo si cierra sobre su media."""
    W = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    px = close[symbol]
    W[symbol] = (px > px.rolling(ma).mean()).astype(float)
    return W


def rotation(close, *, regime_ma=100, mom_n=30, top_k=3, rebalance=7, trend_ma=50,
             vol_n=30, port_vol=0.50, regime_symbol="BTCUSDT", periods_per_year=365,
             offset=0, weekday=None, w_max=1.0):
    """
    Rotacion por momentum: cada `rebalance` velas, comprar las `top_k` monedas
    con mayor retorno en `mom_n` que ademas esten sobre su media `trend_ma`.
    Solo con regimen BTC ON. Exposicion total escalada a `port_vol` (tope 100%).

    `weekday` (0=lunes..6=domingo, segun la fecha de APERTURA de la vela diaria)
    ancla el rebalanceo a un dia fijo de la semana: es lo que usa el bot en vivo
    para que backtest y operacion real calculen exactamente lo mismo.
    """
    c = close
    el = _eligible(c, max(mom_n, trend_ma, vol_n) + 5)
    mom = c / c.shift(mom_n) - 1
    above = c > c.rolling(trend_ma).mean()
    vol = c.pct_change().rolling(vol_n).std() * np.sqrt(periods_per_year)
    reg_px = close[regime_symbol]
    regime = (reg_px > reg_px.rolling(regime_ma).mean()).values
    n, m = c.shape
    W = np.zeros((n, m))
    w = np.zeros(m)
    dow = close.index.dayofweek
    for t in range(n):
        due = (dow[t] == weekday) if weekday is not None else ((t + offset) % rebalance == 0)
        if not regime[t]:
            w = np.zeros(m)
        elif due or w.sum() == 0:
            score = mom.values[t].copy()
            ok = el.values[t] & above.values[t] & ~np.isnan(score) & (score > 0)
            idx = [i for i in np.argsort(-np.nan_to_num(score, nan=-9)) if ok[i]][:top_k]
            w = np.zeros(m)
            if idx:
                iv = np.array([1.0 / max(vol.values[t, i], 1e-6) for i in idx])
                iv = iv / iv.sum()
                avg_vol = np.mean([vol.values[t, i] for i in idx])
                scale = min(1.0, port_vol / avg_vol) if avg_vol > 0 else 0.0
                for k, i in enumerate(idx):
                    w[i] = min(iv[k] * scale, w_max)   # tope por moneda
        W[t] = w
    return pd.DataFrame(W, index=close.index, columns=close.columns)
