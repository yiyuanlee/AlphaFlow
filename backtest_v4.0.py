import backtrader as bt
import yfinance as yf
import pandas as pd
import sys
import io
from datetime import datetime

# 解决 Windows 终端中文显示问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 1. 策略逻辑 (V7.0: 增强平衡版 - 优化交易频率与指数权重)
class ElitePortfolioStrategy(bt.Strategy):
    params = (
        ('fast_period', 10),      # EMA 快线 (微调至10，提高反应速度)
        ('slow_period', 25),      # EMA 慢线
        ('trend_period', 200),    
        ('rsi_period', 14),
        ('rsi_upper', 65),        
        ('adx_period', 14),       
        ('adx_threshold', 20),    # 调低至 20，增加交易机会并捕捉更多趋势
        ('atr_period', 14),       
        ('atr_multiplier', 2.5),  
        ('trailing_stop', 0.12),  # 稍微放宽移动止盈，减少由于微小波动导致的离场
        ('risk_per_trade', 0.015),# 提升至 1.5%，因为之前回撤极低，有空间提升收益
        ('index_multiplier', 3.0),# 进一步增加大盘指数(QQQ/VOO)的权重
        ('printlog', True),
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
                self.log(f'[{d._name}] 买入成功: 价格 {order.executed.price:.2f}')
            else:
                self.log(f'[{d._name}] 卖出成功: 价格 {order.executed.price:.2f}')
                self.inds[d]['stop_price'] = None
                self.inds[d]['highest_price'] = None

    def next(self):
        for d in self.datas:
            pos = self.getposition(d)
            ind = self.inds[d]

            if pos:
                ind['highest_price'] = max(ind['highest_price'], d.close[0])
                
                # 1. 动态 ATR 止损
                if d.close[0] < ind['stop_price']:
                    self.log(f'[{d._name}] 触发 ATR 止损')
                    self.close(d)
                    continue

                # 2. 移动止盈
                if d.close[0] < ind['highest_price'] * (1.0 - self.params.trailing_stop):
                    self.log(f'[{d._name}] 触发移动止盈')
                    self.close(d)
                    continue
                
                # 3. EMA 死叉离场
                if ind['crossover'] < 0:
                    self.log(f'[{d._name}] EMA 死叉离场')
                    self.close(d)

            else:
                # 入场条件增强：结合趋势强度 ADX
                cond_trend = d.close[0] > ind['ema_trend'][0]
                cond_cross = ind['crossover'] > 0
                cond_rsi = ind['rsi'][0] < self.params.rsi_upper
                cond_adx = ind['adx'][0] > self.params.adx_threshold

                if cond_trend and cond_cross and cond_rsi and cond_adx:
                    total_value = self.broker.getvalue()
                    
                    # V7.0 指数权重：QQQ 和 VOO 获得 3 倍风险预算
                    risk_mult = self.params.index_multiplier if d._name in ['QQQ', 'VOO'] else 1.0
                    risk_amount = total_value * self.params.risk_per_trade * risk_mult
                    
                    risk_per_share = max(ind['atr'][0] * self.params.atr_multiplier, 0.01)
                    size = int(risk_amount / risk_per_share)
                    
                    if size * d.close[0] > self.broker.get_cash():
                        size = int(self.broker.get_cash() * 0.95 / d.close[0])

                    if size > 0:
                        self.log(f'[{d._name}] 信号确认 (ADX:{ind["adx"][0]:.1f}): 计划买入 {size} 股')
                        self.buy(data=d, size=size)

def run_backtest(tickers=['QQQ', 'VOO', 'AMD', 'NVDA', 'AAPL', 'MSFT', 'TSLA'], start_date='2023-01-01', end_date='2026-03-20'):
    cerebro = bt.Cerebro()
    
    for ticker in tickers:
        df = yf.download(ticker, start=start_date, end=end_date, auto_adjust=True)
        if not df.empty:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            data = bt.feeds.PandasData(dataname=df, name=ticker)
            cerebro.adddata(data)

    cerebro.addstrategy(ElitePortfolioStrategy)
    cerebro.broker.setcash(3000.0)
    cerebro.broker.setcommission(commission=0.001) 

    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    print(f'--- 开始回测 V7.0 (优化交易频率+指数加权): {tickers} ---')
    results = cerebro.run()
    strat = results[0]

    print('\n' + '='*30)
    print(f'V7.0 增强平衡版回测总结报告')
    print(f'期末净值: {cerebro.broker.getvalue():.2f}')
    print(f'总收益率: {strat.analyzers.returns.get_analysis()["rtot"]*100:.2f}%')
    print(f'最大回撤: {strat.analyzers.drawdown.get_analysis()["max"]["drawdown"]:.2f}%')
    
    sharpe = strat.analyzers.sharpe.get_analysis().get('sharperatio')
    print(f'夏普比率: {sharpe:.2f}' if sharpe else '夏普比率: N/A')
    
    trade_info = strat.analyzers.trades.get_analysis()
    if 'total' in trade_info:
        total = trade_info.total.total
        won = trade_info.won.total
        print(f'总交易笔数: {total}, 胜率: {(won/total*100):.2f}%' if total > 0 else '无记录')
    print('='*30)

if __name__ == '__main__':
    run_backtest()