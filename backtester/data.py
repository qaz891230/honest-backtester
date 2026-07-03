"""Load OHLCV CSV files produced by download_data.py.

Expected columns: ts, open, high, low, close, volume (ts is a datetime).
Returns a DataFrame indexed by timestamp with float OHLCV columns, de-duplicated
and sorted ascending.
"""
from __future__ import annotations
import os
import pandas as pd


def load_ohlcv(path):
    d = pd.read_csv(path)
    d["ts"] = pd.to_datetime(d["ts"], errors="coerce")
    for c in ["open", "high", "low", "close", "volume"]:
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors="coerce")
    keep = ["open", "high", "low", "close"] + (["volume"] if "volume" in d.columns else [])
    d = (d.dropna(subset=["ts", "open", "high", "low", "close"])
           .drop_duplicates("ts").sort_values("ts"))
    return d.set_index("ts")[keep]


def cache_name(symbol, timeframe):
    """Filename convention matching download_data.py, e.g. BTC/USDT:USDT,15m ->
    BTC-USDT-USDT_15m.csv"""
    return symbol.replace("/", "-").replace(":", "-") + "_" + timeframe + ".csv"


def load_symbol(data_dir, symbol, timeframe):
    return load_ohlcv(os.path.join(data_dir, cache_name(symbol, timeframe)))


def load_or_download(symbol, timeframe, data_dir="data", exchange="binance",
                     market_type="spot", years=3, update=False):
    """Cache-first loader — the fast path for repeated backtests.

    * If the cache CSV already exists and `update` is False, it is loaded
      straight from disk (no network, instant) — this is why re-running
      backtests is fast.
    * If it's missing, the data is downloaded once and cached, then loaded.
    * With `update=True`, the cache is incrementally topped up to the latest
      bars first (only the new bars are fetched), then loaded.

    Requires `ccxt` only when a download/update actually happens.
    """
    path = os.path.join(data_dir, cache_name(symbol, timeframe))
    if os.path.exists(path) and not update:
        return load_ohlcv(path)                       # cache hit — no network
    from .download import update_cache                # lazy import (needs ccxt)
    update_cache(data_dir, symbol, timeframe, exchange=exchange,
                 market_type=market_type, years=years, full=not os.path.exists(path))
    return load_ohlcv(path)
