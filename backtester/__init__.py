"""A small, honest, no-lookahead event-driven backtest framework.

Public API:
    from backtester import Strategy, Signal, BacktestConfig, run_backtest
    from backtester.data import load_ohlcv, load_symbol
    from backtester.sweep import grid_sweep, walk_forward
"""
from .strategy import Strategy, Signal
from .engine import Trade, BacktestConfig, run_backtest

__all__ = ["Strategy", "Signal", "Trade", "BacktestConfig", "run_backtest"]
__version__ = "0.1.0"
