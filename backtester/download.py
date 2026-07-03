"""Reusable data download + local cache (keyless, public klines via ccxt).

This module powers both the `download_data.py` CLI and the cache-aware
`backtester.data.load_or_download` loader. Fetching is incremental: an existing
cache file is topped up from its last bar rather than re-downloaded, so repeated
backtests read straight from disk and never re-pull the whole history.

`ccxt` is imported lazily inside the functions, so importing the rest of the
`backtester` package never requires it.
"""
from __future__ import annotations
import os
import time

import pandas as pd

from .data import cache_name, load_ohlcv


def get_exchange(name="binance", market_type="spot"):
    import ccxt  # lazy: only needed when actually downloading
    return getattr(ccxt, name)({"enableRateLimit": True,
                                "options": {"defaultType": market_type}})


def cache_path(data_dir, symbol, timeframe):
    return os.path.join(data_dir, cache_name(symbol, timeframe))


def fetch_since(ex, symbol, timeframe, since_ms):
    """Page forward from since_ms to now. Returns a df indexed by ts (may be empty)."""
    tf_ms = ex.parse_timeframe(timeframe) * 1000
    since = int(since_ms)
    rows, guard = [], 0
    while guard < 8000:
        guard += 1
        batch = ex.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=500)
        if not batch:
            break
        rows += batch
        since = batch[-1][0] + tf_ms
        if len(batch) < 500:
            break
        time.sleep(max(ex.rateLimit, 200) / 1000)
    d = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    if len(d):
        d = d.drop_duplicates("ts").sort_values("ts")
        d["ts"] = pd.to_datetime(d["ts"], unit="ms")
        d = d.set_index("ts")
    return d


def _load_raw(path):
    try:
        if not os.path.exists(path):
            return None
        d = pd.read_csv(path)
        d["ts"] = pd.to_datetime(d["ts"])
        return d.set_index("ts").sort_index()
    except Exception:
        return None


def update_cache(data_dir, symbol, timeframe, exchange="binance", market_type="spot",
                 years=3, full=False, ex=None):
    """Fetch (incrementally) and write the cache CSV. Returns (n_bars, mode).

    - If a cache file exists and `full` is False, only bars after the last cached
      bar are fetched and merged (the last bar is re-fetched in case it was still
      forming).
    - Otherwise the last `years` years are fetched fresh.
    """
    os.makedirs(data_dir, exist_ok=True)
    path = cache_path(data_dir, symbol, timeframe)
    ex = ex or get_exchange(exchange, market_type)
    span_ms = int(years * 365 * 24 * 3600 * 1000)
    old = None if full else _load_raw(path)
    now_ms = ex.milliseconds()
    if old is not None and len(old):
        since = int(old.index[-1].timestamp() * 1000)
        new = fetch_since(ex, symbol, timeframe, since)
        merged = pd.concat([old, new]) if len(new) else old
        merged = merged[~merged.index.duplicated(keep="last")].sort_index()
        mode = "incremental"
    else:
        merged = fetch_since(ex, symbol, timeframe, now_ms - span_ms)
        mode = "full"
    cutoff = pd.to_datetime(now_ms, unit="ms") - pd.Timedelta(days=int(years * 365))
    if len(merged):
        merged = merged[merged.index >= cutoff]
        merged.to_csv(path)
    return len(merged), mode


def download(symbols, timeframes, data_dir="data", exchange="binance",
             market_type="spot", years=3, full=False, verbose=True):
    """Batch download/refresh many symbols x timeframes into the cache."""
    ex = get_exchange(exchange, market_type)
    total = len(symbols) * len(timeframes)
    done = 0
    for sym in symbols:
        for tf in timeframes:
            done += 1
            if verbose:
                print(f"[{done}/{total}] {sym} {tf} ...", end=" ", flush=True)
            try:
                n, mode = update_cache(data_dir, sym, tf, years=years, full=full, ex=ex)
                if verbose:
                    print(f"{mode} -> {n} bars" if n else "no data")
            except Exception as e:
                if verbose:
                    print(f"failed: {e}")
