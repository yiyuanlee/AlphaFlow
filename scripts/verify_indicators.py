"""
AlphaFlow - 指标对齐验证
========================
对比 Backtrader（回测）与 alphaflow.indicators（实盘）在相同 OHLCV 上的计算结果。

用法:
  python scripts/verify_indicators.py
  python scripts/verify_indicators.py --ticker QQQ --ticker VOO
"""

from __future__ import annotations

import argparse
import sys
import io

from _bootstrap import setup_path

setup_path(__file__)

from alphaflow.config import load_config
from alphaflow.parity import run_parity_check

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def print_result(res) -> bool:
    if res is None:
        print('  [!] 数据不足，跳过')
        return False

    status = 'PASS' if res.passed else 'FAIL'
    print(f'\n{"=" * 60}')
    print(f'  {res.ticker}  对齐结果: {status}')
    print(f'  对比行数: {res.rows_compared}  通过率: {res.pass_rate:.2f}%')
    print('=' * 60)

    if res.summary:
        print('\n  最大偏差:')
        for field, info in res.summary.items():
            print(f'    {field:<14} max_diff={info["max_diff"]:.4f}')

    if res.failures:
        print(f'\n  失败样本 (最多显示 {len(res.failures)} 条):')
        for item in res.failures[:10]:
            print(f'    {item["date"]}:')
            for issue in item['issues']:
                print(
                    f'      {issue["field"]}: BT={issue["backtrader"]} '
                    f'PY={issue["alphaflow"]} diff={issue["diff"]:.4f}'
                )

    return res.passed


def main():
    parser = argparse.ArgumentParser(description='Verify indicator parity')
    parser.add_argument('--ticker', action='append', help='Ticker symbol (repeatable)')
    args = parser.parse_args()

    config = load_config()
    tickers = args.ticker or config.get('index_tickers', ['QQQ', 'VOO'])

    print('=' * 65)
    print('  AlphaFlow 指标对齐验证 (Backtrader vs alphaflow.indicators)')
    print('=' * 65)

    all_passed = True
    for ticker in tickers:
        res = run_parity_check(ticker, config)
        if not print_result(res):
            all_passed = False

    print('\n' + ('✅ 全部标的指标对齐通过' if all_passed else '❌ 存在指标偏差，请检查上方失败样本'))
    sys.exit(0 if all_passed else 1)


if __name__ == '__main__':
    main()
