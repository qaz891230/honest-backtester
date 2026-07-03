"""Moving-average crossover (example strategy).

Go long when the fast SMA crosses above the slow SMA, short on the reverse.
Stop = `atr_mult` * ATR, targets at R multiples. The cross is detected using
bars i-1 and i only (no lookahead).
"""
from __future__ import annotations
import pandas as pd

from ..strategy import Strategy, Signal


def _atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean().bfill().values


class MACross(Strategy):
    name = "ma_cross"

    def __init__(self, fast=20, slow=50, atr_period=14, atr_mult=2.0,
                 first_rr=1.5, final_rr=3.0, direction="both", partial=0.5):
        self.fast = fast
        self.slow = slow
        self.atr_period = atr_period
        self.atr_mult = atr_mult
        self.first_rr = first_rr
        self.final_rr = final_rr
        self.direction = direction
        self.partial = partial

    def generate_signals(self, df):
        close = df["close"]
        fast = close.rolling(self.fast).mean().values
        slow = close.rolling(self.slow).mean().values
        c = close.values
        atr = _atr(df, self.atr_period)
        n = len(df)
        out = []
        for i in range(self.slow + 1, n - 1):
            if fast[i - 1] != fast[i - 1] or slow[i - 1] != slow[i - 1]:
                continue  # NaN guard
            up = fast[i - 1] <= slow[i - 1] and fast[i] > slow[i]
            dn = fast[i - 1] >= slow[i - 1] and fast[i] < slow[i]
            a = atr[i]
            if a <= 0:
                continue
            if up and self.direction in ("both", "long"):
                entry = c[i]
                stop = entry - self.atr_mult * a
                r = entry - stop
                out.append(Signal(i, "long", entry, stop,
                                  [entry + self.first_rr * r, entry + self.final_rr * r],
                                  "market", partial=self.partial))
            elif dn and self.direction in ("both", "short"):
                entry = c[i]
                stop = entry + self.atr_mult * a
                r = stop - entry
                out.append(Signal(i, "short", entry, stop,
                                  [entry - self.first_rr * r, entry - self.final_rr * r],
                                  "market", partial=self.partial))
        return out
