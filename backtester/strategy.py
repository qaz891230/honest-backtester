"""Strategy plug-in API.

A strategy's only job is to look at OHLCV bars and emit `Signal`s. The engine
handles everything else: entry fills, stops, targets, breakeven, costs, sizing,
and accounting.

NO-LOOKAHEAD CONTRACT (important):
    A Signal decided "at" bar `index` may only use information available at the
    close of bar `index`. The engine will only ever *fill* the trade on bar
    `index + 1` onwards, and only scans forward from there. If your
    `generate_signals` peeks at future bars to decide a signal, you break the
    backtest's realism — the framework cannot detect that for you, so keep the
    discipline in your strategy code.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List


@dataclass
class Signal:
    """One trade idea produced by a strategy.

    index       : bar index at which the idea is decided (uses data <= index only)
    direction   : "long" or "short"
    entry       : desired entry price
    stop        : protective stop price (must be on the losing side of entry)
    targets     : one or more take-profit prices, nearest first.
                  targets[0]  = first target (a `partial` fraction is closed there)
                  targets[-1] = final target for the remainder
    entry_mode  : "market" -> filled at next bar's open
                  "limit"  -> filled only if price trades back to `entry`
                              within `entry_window` bars (else the idea expires)
    entry_window: bars to wait for a limit fill
    partial     : fraction (0..1) of the position closed at the first target
    """
    index: int
    direction: str
    entry: float
    stop: float
    targets: List[float]
    entry_mode: str = "limit"
    entry_window: int = 12
    partial: float = 1.0
    meta: dict = field(default_factory=dict)


class Strategy(ABC):
    """Subclass this and implement `generate_signals`."""

    name: str = "strategy"

    @abstractmethod
    def generate_signals(self, df) -> List[Signal]:
        """Return a list of Signal objects for the given OHLCV DataFrame.

        `df` is indexed by timestamp with columns: open, high, low, close, volume.
        """
        raise NotImplementedError
