"""
AlphaFlow - 参数优化框架
===========================
网格搜索 + 贝叶斯优化，自动寻找最优参数组合。
用法: python optimize.py
"""

import backtrader as bt
import yfinance as yf
import pandas as pd
import numpy as np
import sys
import io
import yaml
import itertools
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def load_config():
    with open('config.yaml', 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


# ============================================================
# 策略（与 backtest_main.py 一致）
# ============================================================
class AlphaFlowStrategy(bt.Strategy):
    params = dict(
        fast_period=10, slow_period=25, trend_period=200,
        rsi_period=14, rsi_upper=65,
        adx_period=14, adx_threshold=20,
        atr_period=14, atr_multiplier=2.5,
        trailing_stop=0.12,
        risk_per_trade=0.015, index_multiplier=3.0,
    )

    def __init__(self):
        self.inds = {}
        for d in self.datas:
            self.inds[d] = {
                'ema_fast':  bt.indicators.EMA(d, period=self.p.fast_period),
                'ema_slow':  bt.indicators.EMA(d, period=self.p.slow_period),
                'ema_trend': bt.indicators.EMA(d, period=self.p.trend_period),
                'rsi':       bt.indicators.RSI(d, period=self.p.rsi_period),
                'atr':       bt.indicators.ATR(d, period=self.p.atr_period),
                'adx':       bt.indicators.ADX(d, period=self.p.adx_period),
                'crossover': bt.indicators.CrossOver(
                    bt.indicators.EMA(d, period=self.p.fast_period),
                    bt.indicators.EMA(d, period=self.p.slow_period)
                ),
                'stop_price':    None,
                'highest_price': None,
            }

    def notify_order(self, order):
        if order.status in [order.Completed]:
            d = order.data
            if order.isbuy():
                self.inds[d]['stop_price']    = order.executed.price - self.inds[d]['atr'][0] * self.p.atr_multiplier
                self.inds[d]['highest_price'] = order.executed.price
            else:
                self.inds[d]['stop_price']    = None
                self.inds[d]['highest_price'] = None

    def next(self):
        for d in self.datas:
            pos = self.getposition(d)
            ind = self.inds[d]

            if pos:
                ind['highest_price'] = max(ind['highest_price'], d.close[0])
                if d.close[0] < ind['stop_price']:
                    self.close(d)
                    continue
                if d.close[0] < ind['highest_price'] * (1.0 - self.p.trailing_stop):
                    self.close(d)
                    continue
                if ind['crossover'] < 0:
                    self.close(d)
            else:
                if (d.close[0] > ind['ema_trend'][0]
                        and ind['crossover'] > 0
                        and ind['rsi'][0] < self.p.rsi_upper
                        and ind['adx'][0] > self.p.adx_threshold):
                    total_value = self.broker.getvalue()
                    risk_mult   = self.p.index_multiplier if d._name in ['QQQ', 'VOO'] else 1.0
                    risk_amount = total_value * self.p.risk_per_trade * risk_mult
                    atr_stop    = ind['atr'][0] * self.p.atr_multiplier
                    if atr_stop <= 0:
                        continue
                    size = int(risk_amount / atr_stop)
                    if size > 0:
                        self.buy(d, size=size)


# ============================================================
# 数据获取
# ============================================================
def fetch_data(ticker, start, end):
    try:
        df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        df['openinterest'] = 0
        return df
    except Exception:
        return None


# ============================================================
# 单次回测
# ============================================================
def run_backtest(ticker, params, config, df):
    cash      = config['backtest']['initial_cash']
    commission = config['backtest']['commission']

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission)
    cerebro.addsizer(bt.sizers.FixedSize)
    data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data, name=ticker)
    cerebro.addstrategy(AlphaFlowStrategy, **params)

    initial = cerebro.broker.getvalue()
    cerebro.run()
    final   = cerebro.broker.getvalue()
    ret     = (final - initial) / initial * 100

    return {
        'return':     ret,
        'final_value': final,
        'total_return': ret,
    }


# ============================================================
# 网格搜索
# ============================================================
def grid_search(ticker, config):
    print(f'\n🔍 网格搜索: {ticker}')
    print('=' * 50)

    start = config['backtest']['start_date']
    end   = config['backtest']['end_date']
    
    # 提前下载数据，避免在网格搜索循环中重复请求网络
    df = fetch_data(ticker, start, end)
    if df is None or len(df) < 60:
        print(f"  [!] {ticker} 数据获取失败或条目不足，跳过")
        return []

    param_grid = {
        'fast_period':    [8, 10, 12, 15],
        'slow_period':    [20, 25, 30, 35],
        'rsi_upper':      [60, 65, 70],
        'adx_threshold':  [15, 20, 25],
        'atr_multiplier': [2.0, 2.5, 3.0],
        'trailing_stop':  [0.10, 0.12, 0.15],
    }

    keys = list(param_grid.keys())
    combos = list(itertools.product(*param_grid.values()))
    total = len(combos)
    print(f'共 {total} 种参数组合...\n')

    results = []
    for i, combo in enumerate(combos, 1):
        params = dict(zip(keys, combo))
        r = run_backtest(ticker, params, config, df)
        if r:
            r['params'] = params
            results.append(r)
        if i % 100 == 0:
            print(f'  进度: {i}/{total} ({i*100//total}%)')

    results.sort(key=lambda x: x['return'], reverse=True)
    return results


# ============================================================
# 输出 Top-10 结果
# ============================================================
def print_top_results(results, top_n=10):
    if not results:
        print('无有效结果')
        return

    print(f'\n🏆 Top-{top_n} 参数组合:')
    print(f'{'排名':<4} {'收益率':>8} {'最终价值':>10}  参数组合')
    print('-' * 65)

    for i, r in enumerate(results[:top_n], 1):
        p = r['params']
        print(f'{i:<4} {r["return"]:>+7.2f}%  ${r["final_value"]:>8.2f}  '
              f'EMA({p["fast_period"]},{p["slow_period"]}) '
              f'RSI<{p["rsi_upper"]} ADX>{p["adx_threshold"]} '
              f'ATR×{p["atr_multiplier"]} TS={p["trailing_stop"]}')

    best = results[0]
    print(f'\n✅ 最优参数 (收益率: {best["return"]:+.2f}%):')
    for k, v in best['params'].items():
        print(f'   {k}: {v}')

    return best


# ============================================================
# 保存最优参数
# ============================================================
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


# ============================================================
# 主入口
# ============================================================
if __name__ == '__main__':
    config = load_config()
    tickers = config.get('tickers', ['VOO', 'QQQ'])

    print('=' * 60)
    print('  AlphaFlow V8.1 参数优化框架')
    print('=' * 60)

    for ticker in tickers:
        results = grid_search(ticker, config)
        if results:
            best = print_top_results(results)
            if best:
                save_optimal_params(best, ticker)
        print()

    print('✅ 参数优化完成！')
    print('📖 查看 optimal_params.yaml 获取各标的最优参数')