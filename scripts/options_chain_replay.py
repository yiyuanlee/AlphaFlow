"""
AlphaFlow - Options replay with historical chain data
用法:
  set POLYGON_API_KEY=your_key
  python scripts/options_chain_replay.py
  python scripts/options_chain_replay.py --provider csv --csv data/sample_options_chain.csv
"""

from __future__ import annotations

import argparse
import io
import sys

from _bootstrap import setup_path

setup_path(__file__)

from alphaflow.config import load_config
from alphaflow.options.chain_data.base import create_chain_provider
from alphaflow.options.chain_replay import run_chain_replay
from alphaflow.options.options_config import OptionsChainDataParams, options_config_from_yaml

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description='Options chain replay')
    parser.add_argument('--provider', choices=['polygon', 'csv', 'yfinance'], default=None)
    parser.add_argument('--csv', default=None, help='CSV path when provider=csv')
    parser.add_argument('--start', default=None)
    parser.add_argument('--end', default=None)
    args = parser.parse_args()

    config = load_config()
    opt = options_config_from_yaml(config)
    replay = config.get('options_trading', {}).get('replay', {})
    start = args.start or replay.get('start_date', '2023-01-01')
    end = args.end or replay.get('end_date', '2026-06-03')
    cash = float(replay.get('initial_cash', 50_000))

    chain_data = opt.chain_data
    if args.provider or args.csv:
        chain_data = OptionsChainDataParams(
            provider=args.provider or chain_data.provider,
            api_key_env=chain_data.api_key_env,
            rate_limit_seconds=chain_data.rate_limit_seconds,
            csv_path=args.csv or chain_data.csv_path,
            dte_min=chain_data.dte_min,
            dte_max=chain_data.dte_max,
        )

    provider = create_chain_provider(chain_data)
    trades, summary = run_chain_replay(start, end, cash, config, provider)

    if summary.get('error'):
        print(f"Error: {summary['error']}")
        sys.exit(1)

    print('=== Options Chain Replay ===')
    print(f"Provider: {chain_data.provider}")
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
