"""Download public historical OHLCV (klines) into ./data as CSV.

Uses ccxt against a public endpoint — NO API KEYS needed (klines are public).
Incremental: re-running only fetches new bars and merges into the existing file.

Usage:
    python download_data.py                     # defaults below
    python download_data.py --exchange binance --symbols BTC/USDT,ETH/USDT \
                            --timeframes 1h,15m --years 3
    python download_data.py --full              # force a full re-fetch

File naming matches backtester.data.load_symbol, e.g.
    BTC/USDT:USDT , 15m  ->  data/BTC-USDT-USDT_15m.csv
"""
from __future__ import annotations
import argparse
import os
import time

import pandas as pd

try:
    import ccxt
except ImportError:
    raise SystemExit("ccxt is required: pip install ccxt")

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")


def cache_path(sym, tf):
    return os.path.join(DATA_DIR, sym.replace("/", "-").replace(":", "-") + "_" + tf + ".csv")


def _fetch_since(ex, sym, tf, since_ms):
    tf_ms = ex.parse_timeframe(tf) * 1000
    since = int(since_ms)
    rows, guard = [], 0
    while guard < 8000:
        guard += 1
        batch = ex.fetch_ohlcv(sym, timeframe=tf, since=since, limit=500)
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


def _load_existing(path):
    try:
        if not os.path.exists(path):
            return None
        d = pd.read_csv(path)
        d["ts"] = pd.to_datetime(d["ts"])
        return d.set_index("ts").sort_index()
    except Exception:
        return None


def update_cache(ex, sym, tf, years, full=False):
    path = cache_path(sym, tf)
    span_ms = int(years * 365 * 24 * 3600 * 1000)
    old = None if full else _load_existing(path)
    now_ms = ex.milliseconds()
    if old is not None and len(old):
        since = int(old.index[-1].timestamp() * 1000)  # refetch last (maybe unclosed) bar + newer
        new = _fetch_since(ex, sym, tf, since)
        merged = pd.concat([old, new]) if len(new) else old
        merged = merged[~merged.index.duplicated(keep="last")].sort_index()
        added, mode = len(merged) - len(old), "incremental"
    else:
        merged = _fetch_since(ex, sym, tf, now_ms - span_ms)
        added, mode = len(merged), "full"
    cutoff = pd.to_datetime(now_ms, unit="ms") - pd.Timedelta(days=int(years * 365))
    if len(merged):
        merged = merged[merged.index >= cutoff]
    return merged, added, mode


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--exchange", default="binance")
    ap.add_argument("--market-type", default="spot", help="spot / swap / future (ccxt defaultType)")
    ap.add_argument("--symbols", default="BTC/USDT,ETH/USDT")
    ap.add_argument("--timeframes", default="1h,15m")
    ap.add_argument("--years", type=float, default=3.0)
    ap.add_argument("--full", action="store_true")
    a = ap.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)
    symbols = [s.strip() for s in a.symbols.split(",") if s.strip()]
    timeframes = [t.strip() for t in a.timeframes.split(",") if t.strip()]
    ex = getattr(ccxt, a.exchange)({"enableRateLimit": True,
                                    "options": {"defaultType": a.market_type}})
    print(f"exchange={a.exchange} market={a.market_type} years={a.years} "
          f"mode={'full re-fetch' if a.full else 'incremental'}\n")
    total = len(symbols) * len(timeframes)
    done = 0
    for sym in symbols:
        for tf in timeframes:
            done += 1
            print(f"[{done}/{total}] {sym} {tf} ...", end=" ", flush=True)
            try:
                d, added, mode = update_cache(ex, sym, tf, a.years, full=a.full)
                if len(d):
                    d.to_csv(cache_path(sym, tf))
                    print(f"{mode} +{added} -> {len(d)} bars (latest {d.index[-1].date()})")
                else:
                    print("no data")
            except Exception as e:
                print(f"failed: {e}")
    print(f"\nDone. Cache in: {DATA_DIR}")


if __name__ == "__main__":
    main()
