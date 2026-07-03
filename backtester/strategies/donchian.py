"""Donchian channel breakout (example strategy).

Enter long when price closes above the highest high of the last `lookback` bars;
short on the mirror. Stop = `atr_mult` * ATR from entry. Targets at R multiples.

Everything the signal uses is available at the decision bar `i` (the channel is
computed from bars strictly before `i`), so there is no lookahead.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from ..strategy import Strategy, Signal


def _atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean().bfill().values


class DonchianBreakout(Strategy):
    name = "donchian_breakout"

    def __init__(self, lookback=20, atr_period=14, atr_mult=2.0,
                 first_rr=1.5, final_rr=3.0, direction="both",
                 entry_mode="market", partial=0.5):
        self.lookback = lookback
        self.atr_period = atr_period
        self.atr_mult = atr_mult
        self.first_rr = first_rr
        self.final_rr = final_rr
        self.direction = direction
        self.entry_mode = entry_mode
        self.partial = partial

    def generate_signals(self, df):
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values
        atr = _atr(df, self.atr_period)
        n = len(df)
        lb = self.lookback
        out = []
        for i in range(lb, n - 1):
            # channel from the `lb` bars BEFORE i (no current/future bar)
            hh = high[i - lb:i].max()
            ll = low[i - lb:i].min()
            a = atr[i]
            if a <= 0:
                continue
            if self.direction in ("both", "long") and close[i] > hh:
                entry = close[i]
                stop = entry - self.atr_mult * a
                r = entry - stop
                out.append(Signal(i, "long", entry, stop,
                                  [entry + self.first_rr * r, entry + self.final_rr * r],
                                  self.entry_mode, partial=self.partial))
            elif self.direction in ("both", "short") and close[i] < ll:
                entry = close[i]
                stop = entry + self.atr_mult * a
                r = stop - entry
                out.append(Signal(i, "short", entry, stop,
                                  [entry - self.first_rr * r, entry - self.final_rr * r],
                                  self.entry_mode, partial=self.partial))
        return out
