"""Download / refresh the local kline cache (keyless, public data via ccxt).

Data is cached under ./data as CSV. Re-running is incremental: only bars newer
than what's already cached are fetched, so updates are fast. Backtests then read
straight from this cache (see backtester.data.load_symbol / load_or_download).

Usage:
    python download_data.py                         # defaults below
    python download_data.py --exchange binance --market-type swap \
        --symbols BTC/USDT:USDT,ETH/USDT:USDT --timeframes 1h,15m --years 3
    python download_data.py --full                  # force a full re-fetch

File naming matches the loader, e.g. BTC/USDT:USDT , 15m -> data/BTC-USDT-USDT_15m.csv
"""
from __future__ import annotations
import argparse
import os

from backtester.download import download

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exchange", default="binance")
    ap.add_argument("--market-type", default="spot", help="spot / swap / future")
    ap.add_argument("--symbols", default="BTC/USDT,ETH/USDT")
    ap.add_argument("--timeframes", default="1h,15m")
    ap.add_argument("--years", type=float, default=3.0)
    ap.add_argument("--full", action="store_true", help="force full re-fetch")
    ap.add_argument("--data-dir", default=os.path.join(HERE, "data"))
    a = ap.parse_args()

    symbols = [s.strip() for s in a.symbols.split(",") if s.strip()]
    timeframes = [t.strip() for t in a.timeframes.split(",") if t.strip()]
    print(f"exchange={a.exchange} market={a.market_type} years={a.years} "
          f"mode={'full re-fetch' if a.full else 'incremental'}\n")
    download(symbols, timeframes, data_dir=a.data_dir, exchange=a.exchange,
             market_type=a.market_type, years=a.years, full=a.full)
    print(f"\nDone. Cache in: {a.data_dir}")


if __name__ == "__main__":
    main()
