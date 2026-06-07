"""
AlphaFlow - Simplified options routing replay (proxy PnL, not chain-accurate)
用法: python scripts/options_replay_proxy.py
"""

import io
import sys

from _bootstrap import setup_path

setup_path(__file__)

from alphaflow.config import load_config
from alphaflow.options.replay_proxy import run_proxy_replay, summarize_proxy

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def main():
    config = load_config()
    replay = config.get('options_trading', {}).get('replay', {})
    start = replay.get('start_date', '2023-01-01')
    end = replay.get('end_date', '2026-06-03')
    cash = float(replay.get('initial_cash', 50_000))
    trades = run_proxy_replay(start, end, cash, config)
    summary = summarize_proxy(trades)
    print('=== Options Proxy Replay ===')
    print(f'Period: {start} -> {end}')
    print(f"Trades: {summary['trades']}")
    print(f"Proxy PnL: ${summary['total_pnl']:,.2f}")
    if summary['by_intent']:
        print('By intent:')
        for k, v in sorted(summary['by_intent'].items()):
            print(f'  {k}: {v}')


if __name__ == '__main__':
    main()
