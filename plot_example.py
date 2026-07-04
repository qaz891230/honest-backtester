"""Render a backtest to candlestick charts for visual verification.

Runs the demo strategy on the bundled BTC 1h data and saves:
  * charts/overview.png            — a window with every trade's entry/exit
  * charts/trade_00.png ...        — a few single-trade zooms showing every
                                     action (entry, breakeven, partial, exit)

    python plot_example.py
    python plot_example.py --data data/ETH-USDT-USDT_15m.csv --n 6

Requires matplotlib (pip install matplotlib).
"""
from __future__ import annotations
import argparse
import glob
import os

from backtester import BacktestConfig, run_backtest
from backtester.data import load_ohlcv
from backtester.strategies import DonchianBreakout
from backtester.plot import plot_trade, plot_run

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=None, help="OHLCV csv (default: bundled BTC 1h)")
    ap.add_argument("--n", type=int, default=4, help="how many single-trade zooms")
    ap.add_argument("--out", default=os.path.join(HERE, "charts"))
    a = ap.parse_args()

    path = a.data
    if path is None:
        pref = os.path.join(HERE, "data", "BTC-USDT-USDT_1h.csv")
        found = [pref] if os.path.exists(pref) else sorted(glob.glob(os.path.join(HERE, "data", "*.csv")))
        if not found:
            raise SystemExit("No data found — pass --data or run download_data.py first.")
        path = found[0]
    df = load_ohlcv(path)
    os.makedirs(a.out, exist_ok=True)

    cfg = BacktestConfig(equity0=10000, risk_per_trade=100, be_at_r=0.5, be_offset_r=0.1)
    res = run_backtest(df, DonchianBreakout(lookback=20, atr_mult=2.0,
                                            first_rr=1.5, final_rr=3.0), cfg)
    trades = res["_trades"]
    print(f"{len(trades)} trades from {os.path.basename(path)}")

    # Overview around the busiest region.
    if trades:
        mid = trades[len(trades) // 2].entry_index
        plot_run(df, res, start=mid - 150, end=mid + 200,
                 path=os.path.join(a.out, "overview.png"))
        print("saved charts/overview.png")

    # Prefer zooms on trades that exercise the most actions.
    def richness(t):
        return len(t.meta.get("events", []))
    picks = sorted(trades, key=richness, reverse=True)[:a.n]
    for k, t in enumerate(picks):
        p = os.path.join(a.out, f"trade_{k:02d}.png")
        plot_trade(df, t, pad=25, path=p)
        acts = "+".join(e["type"] for e in t.meta.get("events", []))
        print(f"saved {os.path.relpath(p, HERE)}  ({t.reason}, R={t.pnl_r:+.2f}, {acts})")


if __name__ == "__main__":
    main()
