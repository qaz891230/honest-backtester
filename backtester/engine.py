"""The backtest engine: turn a strategy's Signals into Trades and metrics.

Flow per signal (in chronological order):
  1. Resolve the entry fill (market = next open; limit = first later bar that
     trades back to the entry price within `entry_window`; else the idea expires).
  2. Skip the signal if a previous trade is still open (serial, one position at a
     time — `busy_until`). This mirrors a single-account bot that will not stack
     positions and is the conservative default.
  3. Size the position (R-based) and apply the pre-trade risk guard.
  4. Hand off to `simulate_exit` for the honest, no-lookahead exit.
  5. Record the Trade and update the equity curve.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List

import numpy as np

from .exits import simulate_exit
from .metrics import summary
from .sizing import risk_amount, size_position, cap_qty_by_leverage, order_risk_ok


@dataclass
class Trade:
    entry_index: int
    direction: str
    entry: float
    stop: float
    final_target: float
    exit_index: int
    exit_price: float
    pnl_r: float
    pnl_quote: float
    reason: str = ""
    meta: dict = field(default_factory=dict)


@dataclass
class BacktestConfig:
    equity0: float = 100.0
    # Sizing
    risk_mode: str = "fixed"          # "fixed" (R = fixed quote) or "percent" (R = equity*risk_per_trade)
    risk_per_trade: float = 10.0
    leverage: float = 25.0
    min_stop_dist_pct: float = 0.0    # reject stops closer than this fraction of price
    max_risk_mult: float = 3.0        # circuit breaker
    # Costs (fractions of notional)
    taker_fee: float = 0.0005
    maker_fee: float = 0.0002
    slippage: float = 0.0003
    funding_rate: float = 0.0001
    apply_funding: bool = True
    cost_mult: float = 1.0            # scale all costs (stress test, e.g. 1.5x)
    # Breakeven
    be_at_r: float = 0.0
    be_offset_r: float = 0.0
    be_offset_pct: float = 0.0
    # Exit realism
    tp_taker: bool = False            # pessimistic: assume resting TP misses -> market exit
    scan_cap: int = 400              # max bars to hold before mark-to-market


def _costs(cfg: BacktestConfig):
    m = cfg.cost_mult
    return (cfg.taker_fee * m, cfg.maker_fee * m, cfg.slippage * m,
            cfg.funding_rate * m, cfg.apply_funding)


def run_backtest(df, strategy, cfg: BacktestConfig = None):
    """Run `strategy` over OHLCV `df`. Returns a metrics dict; the trade list is
    under key "_trades"."""
    cfg = cfg or BacktestConfig()
    costs = _costs(cfg)

    high = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    opn = df["open"].values.astype(float)
    close = df["close"].values.astype(float)
    epoch_s = df.index.astype("int64").values // 1_000_000_000
    n = len(df)

    signals = sorted(strategy.generate_signals(df), key=lambda s: s.index)

    equity = float(cfg.equity0)
    start = equity
    trades: List[Trade] = []
    curve = [(0, round(equity, 2))]
    total_cost = 0.0
    busy_until = -1

    for sig in signals:
        i = sig.index
        if i < 1 or i <= busy_until or i + 1 >= n:
            continue
        d = sig.direction
        if d not in ("long", "short"):
            continue

        # --- 1. entry fill ---
        if sig.entry_mode == "market":
            entry = opn[i + 1]
            entry_j = i + 1
        else:
            level = sig.entry
            entry = level
            entry_j = None
            for j in range(i + 1, min(i + 1 + sig.entry_window, n)):
                if (d == "long" and low[j] <= level) or (d == "short" and high[j] >= level):
                    entry_j = j
                    break
            if entry_j is None:
                continue  # limit never filled -> idea expires

        stop = sig.stop
        if (d == "long" and stop >= entry) or (d == "short" and stop <= entry):
            continue  # stop on the wrong side

        targets = list(sig.targets) if sig.targets else []
        if not targets:
            continue
        t1 = targets[0]
        t_final = targets[-1]

        # --- 3. sizing + guard ---
        qty = size_position(equity, entry, stop, cfg.risk_mode, cfg.risk_per_trade,
                            cfg.min_stop_dist_pct)
        qty = cap_qty_by_leverage(equity, entry, qty, cfg.leverage)
        if qty <= 0:
            continue
        ok, _reason = order_risk_ok(entry, stop, qty, equity, cfg.risk_mode,
                                    cfg.risk_per_trade, cfg.max_risk_mult, cfg.leverage)
        if not ok:
            continue

        # --- 4. exit ---
        res = simulate_exit(high, low, close, epoch_s, entry_j, entry, stop, d,
                            t1, t_final, qty, sig.partial, costs,
                            be_at_r=cfg.be_at_r, be_offset_pct=cfg.be_offset_pct,
                            be_offset_r=cfg.be_offset_r, scan_cap=cfg.scan_cap,
                            tp_taker=cfg.tp_taker)
        if res is None:
            continue
        net, cost, exit_idx, reason = res.net, res.cost, res.exit_index, res.reason
        r_amt = risk_amount(equity, cfg.risk_mode, cfg.risk_per_trade)
        r_val = round(net / r_amt, 3) if r_amt else 0.0

        busy_until = exit_idx
        equity += net
        total_cost += cost
        curve.append((exit_idx, round(equity, 2)))
        meta = dict(sig.meta)
        meta["events"] = res.events          # every action taken (for plotting/verification)
        trades.append(Trade(entry_j, d, entry, stop, t_final, exit_idx,
                            res.exit_price, r_val, round(net, 2), reason, meta))

    span_days = max((df.index[-1] - df.index[0]).days, 1) if n else 1
    res = summary(trades, equity, start, total_cost, curve, span_days)
    res["_trades"] = trades
    res["_curve"] = curve
    return res
