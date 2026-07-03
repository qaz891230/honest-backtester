"""Example strategies.

These are simple, well-known textbook setups included ONLY to demonstrate the
framework and to give you something runnable out of the box. They are not tuned,
not recommended, and not financial advice. Replace them with your own.
"""
from .donchian import DonchianBreakout
from .ma_cross import MACross

__all__ = ["DonchianBreakout", "MACross"]
