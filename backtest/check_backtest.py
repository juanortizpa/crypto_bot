"""
Pruebas del backtest:  python -m backtest.check_backtest
  1. Sin look-ahead: alterar el futuro no cambia los pesos del pasado.
  2. Costes: mas comision => menos retorno.
  3. Un activo plano no genera ganancias de la nada.
"""
import numpy as np
import pandas as pd

from backtest.data import load_panel
from backtest.engine import run_weights, COST
from backtest.strategies import rotation, trend_momentum
from bot.rotation import PARAMS


def main():
    close = load_panel("1d")
    cut = len(close) - 200
    fut = close.copy()
    rng = np.random.default_rng(0)
    fut.iloc[cut:] = fut.iloc[cut:] * rng.uniform(0.3, 3.0, size=fut.iloc[cut:].shape)
    for name, fn, kw in (("rotation", rotation, PARAMS), ("trend_momentum", trend_momentum, {})):
        a = fn(close, **kw).iloc[:cut]
        b = fn(fut, **kw).iloc[:cut]
        assert np.allclose(a.values, b.values), f"LOOK-AHEAD en {name}"
        print(f"OK  sin look-ahead: {name}")
    W = rotation(close, **PARAMS)
    r1 = run_weights(close, W, cost=COST)["equity"].iloc[-1]
    r2 = run_weights(close, W, cost=COST * 3)["equity"].iloc[-1]
    assert r2 < r1
    print("OK  los costes reducen el retorno")
    flat = pd.DataFrame(1.0, index=close.index, columns=close.columns)
    assert run_weights(flat, W)["equity"].iloc[-1] <= 1.0
    print("OK  precio plano no genera ganancia")
    assert (W.sum(axis=1) <= 1.0 + 1e-9).all() and (W.max(axis=1) <= PARAMS["w_max"] + 1e-9).all()
    print("OK  sin apalancamiento y tope por moneda respetado")


if __name__ == "__main__":
    main()
