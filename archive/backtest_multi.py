"""
AlphaFlow - 多标的回测汇总脚本
==============================
读取 config.yaml 中的参数，对多个标的分别回测，输出汇总表格。
验证策略在不同股票上的通用性，避免单标的过拟合。

用法: python backtest_multi.py
"""

import backtrader as bt
import yfinance as yf
import pandas as pd
import sys
import io
import yaml
from datetime import datetime

# 解决 Windows 终端中文显示问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def load_config():
    with open('config.yaml', 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


# ============================================================
# 策略逻辑 (V7.0 多标的版)
# ============================================================
class ElitePortfolioStrategy(bt.Strategy):
    params = (
        ('fast_period', 10),
        ('slow_period', 25),
        ('trend_period', 200),
        ('rsi_period', 14),
        ('rsi_upper', 65),
        ('adx_period', 14),
        ('adx_threshold', 20),
        ('atr_period', 14),
        ('atr_multiplier', 2.5),
        ('trailing_stop', 0.12),
        ('risk_per_trade', 0.015),
        ('index_multiplier', 3.0),
        ('printlog', False),   # 多标的回测关闭单笔日志
    )

    def log(self, txt, dt=None, doprint=False):
        if self.params.printlog or doprint:
            dt = dt or self.datas[0].datetime.date(0)
            print(f'{dt.isoformat()}, {txt}')

    def __init__(self):
        self.inds = {}
        for d in self.datas:
            self.inds[d] = {
                'ema_fast': bt.indicators.ExponentialMovingAverage(d, period=self.params.fast_period),
                'ema_slow': bt.indicators.ExponentialMovingAverage(d, period=self.params.slow_period),
                'ema_trend': bt.indicators.ExponentialMovingAverage(d, period=self.params.trend_period),
                'rsi': bt.indicators.RelativeStrengthIndex(d, period=self.params.rsi_period),
                'atr': bt.indicators.AverageTrueRange(d, period=self.params.atr_period),
                'adx': bt.indicators.AverageDirectionalMovementIndex(d, period=self.params.adx_period),
                'crossover': bt.indicators.CrossOver(
                    bt.indicators.ExponentialMovingAverage(d, period=self.params.fast_period),
                    bt.indicators.ExponentialMovingAverage(d, period=self.params.slow_period)
                ),
                'stop_price': None,
                'highest_price': None
            }

    def notify_order(self, order):
        if order.status in [order.Completed]:
            d = order.data
            if order.isbuy():
                self.inds[d]['stop_price'] = order.executed.price - (self.inds[d]['atr'][0] * self.params.atr_multiplier)
                self.inds[d]['highest_price'] = order.executed.price
            else:
                self.inds[d]['stop_price'] = None
                self.inds[d]['highest_price'] = None

    def next(self):
        for d in self.datas:
            pos = self.getposition(d)
            ind = self.inds[d]

            if pos:
                ind['highest_price'] = max(ind['highest_price'], d.close[0])

                # ATR 动态止损
                if d.close[0] < ind['stop_price']:
                    self.close(d)
                    continue

                # 移动止盈
                if d.close[0] < ind['highest_price'] * (1.0 - self.params.trailing_stop):
                    self.close(d)
                    continue

                # EMA 死叉离场
                if ind['crossover'] < 0:
                    self.close(d)

            else:
                cond_trend = d.close[0] > ind['ema_trend'][0]
                cond_cross = ind['crossover'] > 0
                cond_rsi = ind['rsi'][0] < self.params.rsi_upper
                cond_adx = ind['adx'][0] > self.params.adx_threshold

                if cond_trend and cond_cross and cond_rsi and cond_adx:
                    total_value = self.broker.getvalue()
                    risk_mult = self.params.index_multiplier if d._name in ['QQQ', 'VOO'] else 1.0
                    risk_amount = total_value * self.params.risk_per_trade * risk_mult
                    risk_per_share = max(ind['atr'][0] * self.params.atr_multiplier, 0.01)
                    size = int(risk_amount / risk_per_share)

                    if size * d.close[0] > self.broker.get_cash():
                        size = int(self.broker.get_cash() * 0.95 / d.close[0])

                    if size > 0:
                        self.buy(data=d, size=size)


# ============================================================
# 逐标的回测（单标的跑，收集结果）
# ============================================================
def run_single_backtest(ticker, config):
    cerebro = bt.Cerebro()

    start_date = config['backtest']['start_date']
    end_date = config['backtest']['end_date']

    df = yf.download(ticker, start=start_date, end=end_date, auto_adjust=True)
    if df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    data = bt.feeds.PandasData(dataname=df, name=ticker)
    cerebro.adddata(data)

    # 直接从 config 读取参数
    s = config['strategy']
    r = config['risk']
    cerebro.addstrategy(ElitePortfolioStrategy,
                       fast_period=s['fast_period'],
                       slow_period=s['slow_period'],
                       trend_period=s['trend_period'],
                       rsi_period=s['rsi_period'],
                       rsi_upper=s['rsi_upper'],
                       adx_period=s['adx_period'],
                       adx_threshold=s['adx_threshold'],
                       atr_period=s['atr_period'],
                       atr_multiplier=s['atr_multiplier'],
                       trailing_stop=s['trailing_stop'],
                       risk_per_trade=r['risk_per_trade'],
                       index_multiplier=r['index_multiplier'])

    cerebro.broker.setcash(config['backtest']['initial_cash'])
    cerebro.broker.setcommission(commission=config['backtest']['commission'])

    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    results = cerebro.run()
    strat = results[0]

    final_value = cerebro.broker.getvalue()
    initial_cash = config['backtest']['initial_cash']
    total_return = (final_value - initial_cash) / initial_cash * 100
    max_dd = strat.analyzers.drawdown.get_analysis()['max']['drawdown']
    sharpe = strat.analyzers.sharpe.get_analysis().get('sharperatio')
    sharpe_val = round(sharpe, 2) if sharpe else 0.0

    trade_info = strat.analyzers.trades.get_analysis()
    total_trades = trade_info.total.total if 'total' in trade_info and trade_info.total.total > 0 else 0
    won_trades = trade_info.won.total if 'won' in trade_info else 0
    win_rate = round(won_trades / total_trades * 100, 1) if total_trades > 0 else 0.0

    return {
        'ticker': ticker,
        'initial': initial_cash,
        'final': round(final_value, 2),
        'return_pct': round(total_return, 2),
        'max_dd': round(max_dd, 2),
        'sharpe': sharpe_val,
        'total_trades': total_trades,
        'win_rate': win_rate,
    }


# ============================================================
# 主程序：遍历所有标的，汇总结果
# ============================================================
def main():
    config = load_config()
    tickers = config['tickers']

    print(f"\n{'='*60}")
    print(f"AlphaFlow 多标的回测汇总")
    print(f"回测周期: {config['backtest']['start_date']} ~ {config['backtest']['end_date']}")
    print(f"初始资金: ${config['backtest']['initial_cash']}")
    print(f"{'='*60}\n")

    results = []
    for ticker in tickers:
        print(f"  ▶ 正在回测 {ticker}...", end=' ')
        res = run_single_backtest(ticker, config)
        if res:
            results.append(res)
            print(f"收益率 {res['return_pct']:+.2f}% | 夏普 {res['sharpe']} | 最大回撤 {res['max_dd']}%")
        else:
            print(f"数据获取失败，跳过")

    # 汇总表格
    print(f"\n{'='*60}")
    print(f"{'标的':<8} {'初始资金':>10} {'结束净值':>10} {'收益率':>9} {'最大回撤':>9} {'夏普比率':>8} {'交易数':>7} {'胜率':>7}")
    print(f"{'-'*60}")
    for r in results:
        print(f"{r['ticker']:<8} {r['initial']:>10.2f} {r['final']:>10.2f} {r['return_pct']:>+8.2f}% {r['max_dd']:>8.2f}% {r['sharpe']:>8} {r['total_trades']:>7} {r['win_rate']:>6.1f}%")

    # 总计行
    avg_return = sum(r['return_pct'] for r in results) / len(results)
    avg_sharpe = sum(r['sharpe'] or 0 for r in results) / len(results)
    avg_dd = sum(r['max_dd'] for r in results) / len(results)
    total_trades_all = sum(r['total_trades'] for r in results)

    print(f"{'-'*60}")
    print(f"{'平均/合计':<8} {'':>10} {'':>10} {avg_return:>+8.2f}% {avg_dd:>8.2f}% {avg_sharpe:>8} {total_trades_all:>7}")
    print(f"{'='*60}")

    # 保存结果到 CSV
    df = pd.DataFrame(results)
    csv_path = 'backtest_results.csv'
    df.to_csv(csv_path, index=False, encoding='utf-8')
    print(f"\n结果已保存到 {csv_path}")

    return results


if __name__ == '__main__':
    main()
