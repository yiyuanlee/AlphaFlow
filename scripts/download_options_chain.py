"""
Prefetch Polygon option chain data into local cache for faster replay.
用法:
  set POLYGON_API_KEY=your_key
  python scripts/download_options_chain.py --symbol QQQ --start 2024-01-01 --end 2024-03-31
"""

from __future__ import annotations

import argparse
import io
import sys
from datetime import date, timedelta

from _bootstrap import setup_path

setup_path(__file__)

from alphaflow.config import load_config
from alphaflow.options.chain_data.base import create_chain_provider
from alphaflow.options.options_config import options_config_from_yaml

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def trading_days(start: str, end: str) -> list[str]:
    from alphaflow.data import fetch_data

    df = fetch_data('QQQ', start, end)
    if df is None or df.empty:
        return []
    return [str(idx.date()) for idx in df.index]


def main():
    parser = argparse.ArgumentParser(description='Prefetch option chain cache')
    parser.add_argument('--symbol', default='QQQ')
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    args = parser.parse_args()

    config = load_config()
    opt = options_config_from_yaml(config)
    provider = create_chain_provider(opt.chain_data)
    days = trading_days(args.start, args.end)
    print(f'Prefetching {args.symbol} chain for {len(days)} sessions...')
    for i, day in enumerate(days, 1):
        provider.get_chain(args.symbol, day, 'P')
        provider.get_chain(args.symbol, day, 'C')
        if i % 10 == 0 or i == len(days):
            print(f'  {i}/{len(days)} ({day})')
    print('Done. Cache stored under output/options_chain_cache/')


if __name__ == '__main__':
    main()
