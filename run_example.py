"""End-to-end demo.

If a real OHLCV CSV exists in ./data it uses the first one it finds; otherwise it
generates a synthetic random-walk series so the example runs offline with no
downloads. Either way it runs an example strategy and prints the metrics, then
saves the equity curve to equity_curve.csv.

    python run_example.py
    python run_example.py --data data/BTC-USDT_1h.csv

The synthetic path is for smoke-testing the plumbing only — the resulting
"performance" is meaningless (a random walk has no edge). Point --data at real
downloaded klines (see download_data.py) for anything real.
"""
from __future__ import annotations
import argparse
import glob
import os

import numpy as np
import pandas as pd

from backtester import BacktestConfig, run_backtest
from backtester.data import load_ohlcv
from backtester.strategies import DonchianBreakout
from backtester.sweep import walk_forward

HERE = os.path.dirname(os.path.abspath(__file__))


def synthetic(n=6000, seed=7, tf_minutes=60):
    """A GBM random walk with OHLC built from an intrabar wiggle."""
    rng = np.random.default_rng(seed)
    ret = rng.normal(0, 0.006, n)
    close = 30000 * np.exp(np.cumsum(ret))
    idx = pd.date_range("2022-01-01", periods=n, freq=f"{tf_minutes}min", tz="UTC")
    o = np.empty(n); h = np.empty(n); l = np.empty(n)
    prev = close[0]
    for k in range(n):
        o[k] = prev
        wig = abs(rng.normal(0, 0.004)) * close[k]
        h[k] = max(o[k], close[k]) + wig
        l[k] = min(o[k], close[k]) - wig
        prev = close[k]
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": close,
                         "volume": rng.uniform(1, 100, n)}, index=idx)


def print_metrics(res):
    keys = ["n_trades", "win_rate", "profit_factor", "expectancy_r", "total_r",
            "avg_win_r", "avg_loss_r", "max_drawdown_pct", "max_loss_streak",
            "return_pct", "per_year_r", "trades_per_week", "total_cost"]
    for k in keys:
        if k in res:
            print(f"  {k:<18} {res[k]}")
    print(f"  reasons            {res.get('reasons')}")
    print(f"  R distribution     {res.get('r_dist')}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default=None, help="path to an OHLCV csv (else synthetic)")
    a = ap.parse_args()

    if a.data:
        df = load_ohlcv(a.data)
        src = a.data
    else:
        # Prefer BTC 1h from the bundled data, else the first csv we find.
        preferred = os.path.join(HERE, "data", "BTC-USDT-USDT_1h.csv")
        found = [preferred] if os.path.exists(preferred) else sorted(
            glob.glob(os.path.join(HERE, "data", "*.csv")))
        if found:
            df = load_ohlcv(found[0])
            src = found[0]
        else:
            df = synthetic()
            src = "SYNTHETIC random walk (no edge — plumbing smoke test only)"
    print(f"data: {src}  ({len(df)} bars, {df.index[0]} -> {df.index[-1]})\n")

    cfg = BacktestConfig(equity0=10000.0, risk_mode="fixed", risk_per_trade=100.0,
                         be_at_r=0.5, be_offset_r=0.1)
    strat = DonchianBreakout(lookback=20, atr_mult=2.0, first_rr=1.5, final_rr=3.0)

    print("=== full-sample backtest ===")
    res = run_backtest(df, strat, cfg)
    print_metrics(res)

    # Save equity curve.
    curve = res["_curve"]
    pd.DataFrame(curve, columns=["bar", "equity"]).to_csv(
        os.path.join(HERE, "equity_curve.csv"), index=False)
    print("\nequity curve saved -> equity_curve.csv")

    print("\n=== walk-forward (5 folds) — is the result stable across time? ===")
    for k, t0, t1, r in walk_forward(df, strat, cfg, n_folds=5):
        print(f"  fold {k}: {str(t0)[:10]}..{str(t1)[:10]}  "
              f"n={r['n_trades']:>4}  PF={r['profit_factor']}  "
              f"totalR={r['total_r']:>7}  MDD={r['max_drawdown_pct']}%")


if __name__ == "__main__":
    main()
