"""
AlphaFlow - Options replay with historical chain data
用法:
  python scripts/options_chain_replay.py --fast --symbol QQQ --start 2025-01-01 --end 2025-03-31
"""

from __future__ import annotations

import argparse
import io
import sys
from dataclasses import replace

from _bootstrap import setup_path

setup_path(__file__)

from alphaflow.config import load_config
from alphaflow.options.chain_data.base import create_chain_provider
from alphaflow.options.chain_replay import run_chain_replay
from alphaflow.options.options_config import options_config_from_yaml

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description='Options chain replay')
    parser.add_argument('--provider', choices=['polygon', 'csv', 'yfinance'], default=None)
    parser.add_argument('--csv', default=None, help='CSV path when provider=csv')
    parser.add_argument('--start', default=None)
    parser.add_argument('--end', default=None)
    parser.add_argument('--symbol', default=None, help='Single underlying, e.g. QQQ')
    parser.add_argument('--fast', action='store_true', help='Fast mode: BS pricing, stride entries')
    parser.add_argument('--full', action='store_true', help='Disable fast mode (more API calls)')
    args = parser.parse_args()

    config = load_config()
    opt = options_config_from_yaml(config)
    replay = config.get('options_trading', {}).get('replay', {})
    start = args.start or replay.get('start_date', '2023-01-01')
    end = args.end or replay.get('end_date', '2026-06-03')
    cash = float(replay.get('initial_cash', 50_000))

    chain_data = opt.chain_data
    overrides = {}
    if args.provider:
        overrides['provider'] = args.provider
    if args.csv:
        overrides['csv_path'] = args.csv
    if args.fast:
        overrides['fast_mode'] = True
    if args.full:
        overrides['fast_mode'] = False
    if overrides:
        chain_data = replace(chain_data, **overrides)

    symbols = (args.symbol,) if args.symbol else None
    fast = None if not args.fast and not args.full else chain_data.fast_mode
    provider = create_chain_provider(chain_data)
    trades, summary = run_chain_replay(start, end, cash, config, provider, symbols=symbols, fast=fast)

    if summary.get('error'):
        print(f"Error: {summary['error']}")
        sys.exit(1)

    print('=== Options Chain Replay ===')
    print(f"Provider: {chain_data.provider}")
    print(f"Fast mode: {summary.get('fast_mode', False)} | Stride: {summary.get('stride_days', 1)}d")
    print(f"Symbols: {', '.join(summary.get('symbols', []))}")
    print(f"Period: {summary['start']} -> {summary['end']}")
    print(f"Opens: {summary['opens']} | Closes: {summary['closes']}")
    print(f"Total PnL: ${summary['total_pnl']:,.2f}")
    print(f"Return: {summary['return_pct'] * 100:.2f}%")
    print(f"Ending cash: ${summary['ending_cash']:,.2f}")
    if summary.get('by_intent'):
        print('Opens by intent:')
        for k, v in sorted(summary['by_intent'].items()):
            print(f'  {k}: {v}')


if __name__ == '__main__':
    main()
