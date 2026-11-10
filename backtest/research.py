"""
Investigacion: compara estrategias en muestra (IS) y fuera de muestra (OOS).

    python -m backtest.research            # tabla comparativa
    python -m backtest.research grid       # robustez de parametros (solo IS)
"""
import sys
import itertools

import pandas as pd

from backtest.data import load_panel
from backtest.engine import run_weights, slice_metrics, episodes, trade_stats
from backtest import strategies as S
from bot.rotation import PARAMS as BOT_PARAMS

IS = ("2019-06-01", "2022-12-31")     # diseno
OOS = ("2023-01-01", None)            # validacion: no se toca al disenar

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 30)


def table(close, strategies, periods):
    rows = []
    for name, W in strategies.items():
        res = run_weights(close, W)
        for pname, (a, b) in periods.items():
            m = slice_metrics(res, a, b)
            ep = episodes(close.loc[a:b], W.loc[a:b])
            ts = trade_stats(ep)
            rows.append({"estrategia": name, "periodo": pname, **m,
                         **{k: ts.get(k) for k in ("trades", "WR_%", "payoff", "PF", "expectancy_%")}})
    return pd.DataFrame(rows)


def main():
    close = load_panel("1d")
    strategies = {
        "BTC buy&hold": S.buy_hold(close),
        "Cesta igual-peso": S.equal_weight_basket(close),
        "BTC > MA100": S.ma_regime_single(close),
        "Tendencia+Momentum": S.trend_momentum(close),
        "Rotacion (generica)": S.rotation(close),
        "ROTACION (config del bot)": S.rotation(close, **BOT_PARAMS),
    }
    periods = {"IS 2019-22": IS, "OOS 2023-26": OOS,
               "2022 (bajista)": ("2022-01-01", "2022-12-31"),
               "ult. 12 meses": (str((close.index[-1] - pd.Timedelta(days=365)).date()), None)}
    print(table(close, strategies, periods).to_string(index=False))
    print()
    print("ROTACION (config del bot) por ano:")
    res = run_weights(close, strategies["ROTACION (config del bot)"])
    btc = run_weights(close, strategies["BTC buy&hold"])
    for y in range(2019, close.index[-1].year + 1):
        m, b = slice_metrics(res, f"{y}-01-01", f"{y}-12-31"), slice_metrics(btc, f"{y}-01-01", f"{y}-12-31")
        print(f"  {y}: bot {m.get('total_%'):>7}%  (maxDD {m.get('maxDD_%')}%, expo {m.get('expo_%')}%)   BTC {b.get('total_%'):>7}%")


def grid():
    close = load_panel("1d")
    rows = []
    for rm, en, ex, k in itertools.product((50, 100, 150, 200), (20, 30, 50, 80),
                                           (10, 20, 30), (3, 5, 8)):
        if ex >= en:
            continue
        W = S.trend_momentum(close, regime_ma=rm, entry_n=en, exit_n=ex, top_k=k)
        res = run_weights(close, W)
        m = slice_metrics(res, *IS)
        rows.append({"regime_ma": rm, "entry_n": en, "exit_n": ex, "top_k": k, **m})
    df = pd.DataFrame(rows)
    print(df.sort_values("sharpe", ascending=False).to_string(index=False))
    print("\nResumen IS: sharpe mediana=%.2f  min=%.2f  max=%.2f  | %% combos con CAGR>0: %.0f%%" % (
        df["sharpe"].median(), df["sharpe"].min(), df["sharpe"].max(), (df["CAGR_%"] > 0).mean() * 100))
    return df


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "grid":
        grid()
    else:
        main()
