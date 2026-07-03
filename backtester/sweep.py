"""Parameter sweeps and walk-forward evaluation.

These are thin harnesses over `run_backtest`. They deliberately do not do any
optimisation magic — they just run many configurations so you can inspect the
*stability* of results, which matters far more than a single best number.
"""
from __future__ import annotations
import itertools
from dataclasses import replace

from .engine import run_backtest, BacktestConfig


def grid_sweep(df, strategy_factory, param_grid, base_cfg=None, metric="per_year_r"):
    """Run every combination in `param_grid`.

    strategy_factory: callable(**params) -> Strategy
    param_grid      : dict of param_name -> list of values
    Returns a list of (params, metrics) sorted by `metric` descending.
    """
    base_cfg = base_cfg or BacktestConfig()
    keys = list(param_grid.keys())
    results = []
    for combo in itertools.product(*[param_grid[k] for k in keys]):
        params = dict(zip(keys, combo))
        strat = strategy_factory(**params)
        res = run_backtest(df, strat, base_cfg)
        results.append((params, res))
    results.sort(key=lambda pr: (pr[1].get(metric) or float("-inf")), reverse=True)
    return results


def walk_forward(df, strategy, cfg=None, n_folds=5):
    """Split the data into `n_folds` contiguous, non-overlapping windows and run
    the (already-parameterised) strategy on each. If performance only holds in
    one window and collapses in others, the edge is probably curve-fit.

    Returns a list of (fold_index, start_ts, end_ts, metrics).
    """
    cfg = cfg or BacktestConfig()
    n = len(df)
    fold = n // n_folds
    out = []
    for k in range(n_folds):
        lo = k * fold
        hi = n if k == n_folds - 1 else (k + 1) * fold
        sub = df.iloc[lo:hi]
        if len(sub) < 50:
            continue
        res = run_backtest(sub, strategy, cfg)
        out.append((k, sub.index[0], sub.index[-1], res))
    return out
