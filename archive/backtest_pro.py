import backtrader as bt
import yfinance as yf
import pandas as pd
import sys
import io
from datetime import datetime

# 解决 Windows 控制台输出中文乱码问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 1. 定义进阶版策略逻辑 (V3.0: 趋势过滤 + ATR 自适应止损)
class MyStrategy(bt.Strategy):
    params = (
        ('fast_period', 10),      
        ('slow_period', 30),      
        ('trend_period', 200),    
        ('rsi_period', 14),
        ('rsi_upper', 70),
        ('atr_period', 14),       # ATR 周期
        ('atr_multiplier', 2.5),  # ATR 止损倍数：通常 2.0-3.0 比较稳健
        ('trailing_stop', 0.15),  
        ('printlog', True),
    )

    def log(self, txt, dt=None, doprint=False):
        if self.params.printlog or doprint:
            dt = dt or self.datas[0].datetime.date(0)
            print(f'{dt.isoformat()}, {txt}')

    def __init__(self):
        self.dataclose = self.datas[0].close
        
        # 基础指标
        self.sma_fast = bt.indicators.SimpleMovingAverage(self.datas[0], period=self.params.fast_period)
        self.sma_slow = bt.indicators.SimpleMovingAverage(self.datas[0], period=self.params.slow_period)
        self.sma_trend = bt.indicators.SimpleMovingAverage(self.datas[0], period=self.params.trend_period)
        self.rsi = bt.indicators.RelativeStrengthIndex(period=self.params.rsi_period)
        
        # 波动率指标 (ATR)
        self.atr = bt.indicators.AverageTrueRange(self.datas[0], period=self.params.atr_period)
        
        # 交叉信号
        self.crossover = bt.indicators.CrossOver(self.sma_fast, self.sma_slow)
        
        self.order = None
        self.stop_price = None     # 动态止损价
        self.highest_price = None 

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
            
        if order.status in [order.Completed]:
            if order.isbuy():
                # 买入时，基于当前 ATR 计算初始止损价
                self.stop_price = order.executed.price - (self.atr[0] * self.params.atr_multiplier)
                self.log(f'买入执行: 价格 {order.executed.price:.2f}, 初始 ATR 止损位: {self.stop_price:.2f}')
                self.highest_price = order.executed.price
            else:
                self.log(f'卖出执行: 价格 {order.executed.price:.2f}')
                self.stop_price = None
                self.highest_price = None
        
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log('订单异常')
            
        self.order = None

    def next(self):
        if self.order:
            return

        # 持仓状态下的风险管理
        if self.position:
            self.highest_price = max(self.highest_price, self.dataclose[0])
            
            # 策略 A: 自适应 ATR 止损 (代替固定的 8%)
            if self.dataclose[0] < self.stop_price:
                self.log(f'【触发 ATR 止损】: 当前价 {self.dataclose[0]:.2f}, 止损价 {self.stop_price:.2f}')
                self.order = self.close()
                return

            # 策略 B: 移动止损 (锁住大额利润)
            if self.dataclose[0] < self.highest_price * (1.0 - self.params.trailing_stop):
                self.log(f'【触发移动止损】: 当前价 {self.dataclose[0]:.2f}, 最高价 {self.highest_price:.2f}')
                self.order = self.close()
                return

        # 买入信号：金叉 + 趋势向上 + RSI安全
        if not self.position:
            if self.crossover > 0 and self.rsi[0] < self.params.rsi_upper and self.dataclose[0] > self.sma_trend[0]:
                cash = self.broker.get_cash()
                size = int(cash * 0.95 / self.dataclose[0]) 
                if size > 0:
                    self.log(f'创建买入单: 价格 {self.dataclose[0]:.2f}, ATR: {self.atr[0]:.2f}')
                    self.order = self.buy(size=size)
        
        # 卖出信号
        else:
            if self.crossover < 0:
                self.log(f'趋势结束卖出 (均线死叉): 价格 {self.dataclose[0]:.2f}')
                self.order = self.close()

def run_backtest(ticker_symbol='AMD', start_date='2022-01-01', end_date='2026-03-20'):
    cerebro = bt.Cerebro()
    
    # 增加数据窗口，让指标计算更准确
    df = yf.download(ticker_symbol, start=start_date, end=end_date, auto_adjust=True)
    if df.empty: return
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
        
    data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data)

    cerebro.addstrategy(MyStrategy)
    cerebro.broker.setcash(3000.0)
    cerebro.broker.setcommission(commission=0.001) 

    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')

    print(f'--- 开始回测 V3.0 (ATR自适应止损): {ticker_symbol} ---')
    results = cerebro.run()
    strat = results[0]

    print('\n' + '='*30)
    print(f'结束账户净值: {cerebro.broker.getvalue():.2f}')
    print(f'总收益率: {strat.analyzers.returns.get_analysis()["rtot"]*100:.2f}%')
    print(f'最大回撤: {strat.analyzers.drawdown.get_analysis()["max"]["drawdown"]:.2f}%')
    
    sharpe = strat.analyzers.sharpe.get_analysis().get('sharperatio')
    print(f'夏普比率: {sharpe:.2f}' if sharpe else '夏普比率: N/A')
    print('='*30)

if __name__ == '__main__':
    run_backtest('AMD')