"""
AlphaFlow - 参数优化框架
===========================
网格搜索，自动寻找最优参数组合。
用法: python optimize.py
"""

import sys
import io
import itertools
from datetime import datetime
from pathlib import Path

import backtrader as bt
import yaml

from alphaflow.config import load_config, params_from_config, strategy_params_to_bt
from alphaflow.data import fetch_data
from alphaflow.strategy import AlphaFlowStrategy

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def run_backtest(ticker, params, config, df):
    cash = config['backtest']['initial_cash']
    commission = config['backtest']['commission']

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission)
    cerebro.adddata(bt.feeds.PandasData(dataname=df), name=ticker)
    cerebro.addstrategy(AlphaFlowStrategy, portfolio_mode=False, **params)

    initial = cerebro.broker.getvalue()
    cerebro.run()
    final = cerebro.broker.getvalue()
    ret = (final - initial) / initial * 100

    return {'return': ret, 'final_value': final, 'total_return': ret}


def grid_search(ticker, config, base_params):
    print(f'\n🔍 网格搜索: {ticker}')
    print('=' * 50)

    start = config['backtest']['start_date']
    end = config['backtest']['end_date']
    df = fetch_data(ticker, start, end)
    if df is None or len(df) < 60:
        print(f"  [!] {ticker} 数据获取失败或条目不足，跳过")
        return []

    param_grid = {
        'fast_period': [8, 10, 12, 15],
        'slow_period': [20, 25, 30, 35],
        'rsi_upper': [60, 65, 70],
        'adx_threshold': [15, 20, 25],
        'atr_multiplier': [2.0, 2.5, 3.0],
        'trailing_stop': [0.10, 0.12, 0.15],
    }

    keys = list(param_grid.keys())
    combos = list(itertools.product(*param_grid.values()))
    total = len(combos)
    print(f'共 {total} 种参数组合...\n')

    results = []
    for i, combo in enumerate(combos, 1):
        overrides = dict(zip(keys, combo))
        params = {**base_params, **overrides}
        r = run_backtest(ticker, params, config, df)
        if r:
            r['params'] = overrides
            results.append(r)
        if i % 100 == 0:
            print(f'  进度: {i}/{total} ({i * 100 // total}%)')

    results.sort(key=lambda x: x['return'], reverse=True)
    return results


def print_top_results(results, top_n=10):
    if not results:
        print('无有效结果')
        return None

    print(f'\n🏆 Top-{top_n} 参数组合:')
    print(f"{'排名':<4} {'收益率':>8} {'最终价值':>10}  参数组合")
    print('-' * 65)

    for i, r in enumerate(results[:top_n], 1):
        p = r['params']
        print(
            f'{i:<4} {r["return"]:>+7.2f}%  ${r["final_value"]:>8.2f}  '
            f'EMA({p["fast_period"]},{p["slow_period"]}) '
            f'RSI<{p["rsi_upper"]} ADX>{p["adx_threshold"]} '
            f'ATR×{p["atr_multiplier"]} TS={p["trailing_stop"]}'
        )

    best = results[0]
    print(f'\n✅ 最优参数 (收益率: {best["return"]:+.2f}%):')
    for k, v in best['params'].items():
        print(f'   {k}: {v}')
    return best


def save_optimal_params(best_params, ticker, output_path='optimal_params.yaml'):
    existing = {}
    if Path(output_path).exists():
        with open(output_path, 'r', encoding='utf-8') as f:
            existing = yaml.safe_load(f) or {}

    existing[ticker] = {
        'params': best_params['params'],
        'return': best_params['return'],
        'final_value': best_params['final_value'],
        'optimized_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        yaml.dump(existing, f, allow_unicode=True, default_flow_style=False)

    print(f'\n💾 最优参数已保存: {output_path}')


if __name__ == '__main__':
    config = load_config()
    strategy, risk = params_from_config(config)
    base_params = strategy_params_to_bt(strategy, risk)
    tickers = config.get('tickers', ['VOO', 'QQQ'])

    print('=' * 60)
    print('  AlphaFlow 参数优化框架')
    print('=' * 60)

    for ticker in tickers:
        results = grid_search(ticker, config, base_params)
        if results:
            best = print_top_results(results)
            if best:
                save_optimal_params(best, ticker)
        print()

    print('✅ 参数优化完成！')
    print('📖 查看 optimal_params.yaml 获取各标的最优参数')
