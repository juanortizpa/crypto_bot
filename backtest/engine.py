"""
Motor de backtest por pesos de cartera (spot, long-only, sin apalancamiento).

Convencion anti look-ahead:
  W.loc[t] = pesos decididos con informacion hasta el CIERRE de la vela t.
  Se ejecutan en ese cierre (= apertura de t+1 en un mercado 24/7) y ganan el
  retorno de t -> t+1. Nunca se usa informacion de t+1 para decidir W[t].

Costes: cada cambio de peso paga COST por unidad de turnover
(comision 0.10% + deslizamiento 0.05% por lado, conservador para spot).
"""
import numpy as np
import pandas as pd

FEE = 0.0010
SLIPPAGE = 0.0005
COST = FEE + SLIPPAGE


def run_weights(close: pd.DataFrame, W: pd.DataFrame, cost: float = COST) -> pd.DataFrame:
    """Devuelve DataFrame con retorno neto por periodo, equity, exposicion y turnover."""
    W = W.reindex(close.index).fillna(0.0)
    rets = close.pct_change().shift(-1)            # retorno t -> t+1
    rets = rets.where(W > 0, 0.0).fillna(0.0)      # moneda sin dato = sin posicion
    gross = (W * rets).sum(axis=1)
    # turnover: los pesos derivan con el precio; se aproxima con el cambio de peso objetivo
    turnover = W.diff().abs().sum(axis=1)
    turnover.iloc[0] = W.iloc[0].abs().sum()
    net = gross - turnover * cost
    # el retorno de la fila t se materializa en t+1
    net = net.shift(1).fillna(0.0)
    out = pd.DataFrame({"ret": net, "exposure": W.sum(axis=1), "turnover": turnover})
    out["equity"] = (1 + out["ret"]).cumprod()
    return out


def metrics(res: pd.DataFrame, periods_per_year: float = 365.0) -> dict:
    r = res["ret"]
    if len(r) < 2:
        return {}
    eq = (1 + r).cumprod()
    years = len(r) / periods_per_year
    cagr = eq.iloc[-1] ** (1 / years) - 1 if eq.iloc[-1] > 0 else -1.0
    vol = r.std() * np.sqrt(periods_per_year)
    sharpe = (r.mean() * periods_per_year) / vol if vol > 0 else 0.0
    downside = r[r < 0].std() * np.sqrt(periods_per_year)
    sortino = (r.mean() * periods_per_year) / downside if downside > 0 else 0.0
    dd = eq / eq.cummax() - 1
    maxdd = dd.min()
    return {
        "total_%": round((eq.iloc[-1] - 1) * 100, 1),
        "CAGR_%": round(cagr * 100, 1),
        "vol_%": round(vol * 100, 1),
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "maxDD_%": round(maxdd * 100, 1),
        "calmar": round(cagr / abs(maxdd), 2) if maxdd < 0 else float("nan"),
        "expo_%": round(res["exposure"].mean() * 100, 0),
        "turnover_anual": round(res["turnover"].sum() / years, 1),
    }


def slice_metrics(res, start=None, end=None, ppy=365.0):
    s = res.loc[start:end]
    return metrics(s, ppy)


def episodes(close: pd.DataFrame, W: pd.DataFrame, cost: float = COST) -> pd.DataFrame:
    """
    Estadistica por operacion: cada tramo continuo con peso > 0 en una moneda
    es un trade (entrada al cierre de la primera vela, salida al cierre de la
    ultima+1). Retorno neto de comisiones de ida y vuelta.
    """
    rows = []
    held = (W.reindex(close.index).fillna(0.0) > 0)
    for sym in held.columns:
        h = held[sym].values
        px = close[sym].values
        idx = close.index
        i, n = 0, len(h)
        while i < n:
            if h[i]:
                j = i
                while j + 1 < n and h[j + 1]:
                    j += 1
                exit_i = min(j + 1, n - 1)
                if exit_i > i and px[i] > 0 and not np.isnan(px[exit_i]):
                    ret = px[exit_i] / px[i] - 1 - 2 * cost
                    rows.append((sym, idx[i], idx[exit_i], exit_i - i, ret))
                i = j + 1
            else:
                i += 1
    return pd.DataFrame(rows, columns=["symbol", "entry", "exit", "bars", "ret"])


def trade_stats(ep: pd.DataFrame) -> dict:
    if ep is None or not len(ep):
        return {"trades": 0}
    wins = ep[ep["ret"] > 0]["ret"]
    losses = ep[ep["ret"] <= 0]["ret"]
    pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else float("inf")
    return {
        "trades": len(ep),
        "WR_%": round(len(wins) / len(ep) * 100, 1),
        "gan_media_%": round(wins.mean() * 100, 2) if len(wins) else 0.0,
        "perd_media_%": round(losses.mean() * 100, 2) if len(losses) else 0.0,
        "payoff": round(wins.mean() / abs(losses.mean()), 2) if len(wins) and len(losses) else float("nan"),
        "PF": round(pf, 2),
        "expectancy_%": round(ep["ret"].mean() * 100, 2),
        "dias_medios": round(ep["bars"].mean(), 1),
    }
