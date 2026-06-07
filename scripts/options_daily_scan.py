"""
AlphaFlow - 日期权信号快扫（无需 IBKR，约 10 秒）
用法: python scripts/options_daily_scan.py
      python scripts/options_daily_scan.py --no-chain   # 仅路由，不拉链
"""

import argparse
import io
import sys

from _bootstrap import setup_path

setup_path(__file__)

from alphaflow.options.daily_scan import format_daily_scan, run_daily_scan

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-chain', action='store_true', help='Skip chain quotes (faster)')
    parser.add_argument('--date', default=None)
    args = parser.parse_args()
    report = run_daily_scan(as_of=args.date, use_chain=not args.no_chain)
    print(format_daily_scan(report))


if __name__ == '__main__':
    main()
