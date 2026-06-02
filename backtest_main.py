"""
AlphaFlow - 真实组合回测入口
===========================
所有标的在同一个资金池（$10,000）中共同交易，相互竞争资金。
资金分配规则：60% 资金上限用于指数类 (VOO, QQQ)，40% 资金上限用于个股类。
用法: python backtest_main.py
"""

import backtrader as bt
import yfinance as yf
import pandas as pd
import numpy as np
import sys
import io
import yaml
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from datetime import datetime
from pathlib import Path

# --- 解决 Windows 终端中文显示 ---
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# --- 解决 Matplotlib 中文乱码 ---
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False

# --- 颜色配置 ---
GREEN = '#10B981'
RED   = '#EF4444'
ACCENT = '#6C63FF'
BG     = '#0D1117'


def load_config():
    with open('config.yaml', 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


# ============================================================
# 策略逻辑 (V9.0) — 真实组合回测 + 资金池分配
# ============================================================
class AlphaFlowStrategy(bt.Strategy):
    params = dict(
        fast_period=10, slow_period=25, trend_period=200,
        rsi_period=14, rsi_upper=65,
        adx_period=14, adx_threshold=20,
        atr_period=14, atr_multiplier=2.5,
        vol_filter_period=100,
        vol_filter_ratio=0.8,
        trailing_atr_mult=3.0,
        trailing_stop=0.12,
        risk_per_trade=0.030,
        alloc_index=0.60,
        alloc_stock=0.40,
        printlog=False,
    )

    def log(self, txt, dt=None):
        if self.params.printlog:
            dt = dt or self.datas[0].datetime.date(0)
            print(f'{dt.isoformat()} {txt}')

    def __init__(self):
        self.inds = {}
        # 用于手动统计各标的交易情况
        self.trade_stats = {d._name: {'trades': 0, 'won': 0, 'pnl': 0.0} for d in self.datas}

        for d in self.datas:
            atr = bt.indicators.ATR(d, period=self.p.atr_period)
            self.inds[d] = {
                'ema_fast':  bt.indicators.EMA(d, period=self.p.fast_period),
                'ema_slow':  bt.indicators.EMA(d, period=self.p.slow_period),
                'ema_trend': bt.indicators.EMA(d, period=self.p.trend_period),
                'rsi':       bt.indicators.RSI(d, period=self.p.rsi_period),
                'atr':       atr,
                'adx':       bt.indicators.ADX(d, period=self.p.adx_period),
                'crossover': bt.indicators.CrossOver(
                    bt.indicators.EMA(d, period=self.p.fast_period),
                    bt.indicators.EMA(d, period=self.p.slow_period)
                ),
                'atr_sma':   bt.indicators.SMA(atr, period=self.p.vol_filter_period),
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

    def notify_trade(self, trade):
        if trade.isclosed:
            name = trade.data._name
            self.trade_stats[name]['trades'] += 1
            self.trade_stats[name]['pnl'] += trade.pnlcomm
            if trade.pnlcomm > 0:
                self.trade_stats[name]['won'] += 1

    def stop(self):
        # 回测结束时，计算所有未平仓头寸的浮动盈亏（主要针对长线持有的 VOO 和 QQQ）
        for d in self.datas:
            pos = self.getposition(d)
            if pos:
                pnl = pos.size * (d.close[0] - pos.price)
                name = d._name
                self.trade_stats[name]['trades'] += 1
                self.trade_stats[name]['pnl'] += pnl
                if pnl > 0:
                    self.trade_stats[name]['won'] += 1

    def next(self):
        total_value = self.broker.getvalue()
        
        # 计算当前指数和个股的已用资金敞口
        index_exposure = 0.0
        stock_exposure = 0.0
        
        for d in self.datas:
            pos = self.getposition(d)
            if pos:
                val = pos.size * d.close[0]
                if d._name in ['VOO', 'QQQ']:
                    index_exposure += val
                else:
                    stock_exposure += val

        for d in self.datas:
            pos  = self.getposition(d)
            ind  = self.inds[d]
            is_index = d._name in ['VOO', 'QQQ']

            if pos:
                ind['highest_price'] = max(ind['highest_price'], d.close[0])
                
                # 1. 趋势破坏退场 (收盘价 < 200日线)
                if d.close[0] < ind['ema_trend'][0]:
                    self.close(d)
                    continue
                # 2. ATR 止损
                if d.close[0] < ind['stop_price']:
                    self.close(d)
                    continue
                # 3. ATR 动态移动止盈
                atr_trail = ind['highest_price'] - ind['atr'][0] * self.p.trailing_atr_mult
                pct_trail = ind['highest_price'] * (1.0 - self.p.trailing_stop)
                trailing_level = min(atr_trail, pct_trail)
                if d.close[0] < trailing_level:
                    self.close(d)
                    continue
                # 4. 死叉离场
                if ind['crossover'] < 0:
                    self.close(d)

            else:
                # 动量趋势入场策略
                trend_ok  = d.close[0] > ind['ema_trend'][0]
                cross_ok  = ind['crossover'] > 0
                rsi_ok    = ind['rsi'][0] < self.p.rsi_upper
                adx_ok    = ind['adx'][0] > self.p.adx_threshold
                vol_ok    = ind['atr'][0] > ind['atr_sma'][0] * self.p.vol_filter_ratio

                if trend_ok and cross_ok and rsi_ok and adx_ok and vol_ok:
                    # 指数获得 3 倍风险乘数，个股 1 倍
                    risk_mult = 3.0 if is_index else 1.0
                    risk_amount = total_value * self.p.risk_per_trade * risk_mult
                    atr_stop    = max(ind['atr'][0] * self.p.atr_multiplier, 0.01)
                    size = int(risk_amount / atr_stop)
                    
                    order_val = size * d.close[0]
                    
                    # 资金池分配检查
                    if is_index:
                        max_allowed_val = total_value * self.p.alloc_index
                        available_val = max_allowed_val - index_exposure
                    else:
                        max_allowed_val = total_value * self.p.alloc_stock
                        available_val = max_allowed_val - stock_exposure
                        
                    # 取可用分配额度和账户实际可用现金的较小值
                    available_cash = self.broker.get_cash() * 0.95
                    actual_available = max(min(available_val, available_cash), 0)
                    
                    if order_val > actual_available:
                        size = int(actual_available / d.close[0])

                    if size <= 0:
                        continue
                        
                    self.buy(d, size=size)
                    
                    # 更新已用敞口，避免同一次 next() 循环中超买
                    if is_index:
                        index_exposure += size * d.close[0]
                    else:
                        stock_exposure += size * d.close[0]


# ============================================================
# 下载数据
# ============================================================
def fetch_data(ticker, start, end):
    try:
        df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df['openinterest'] = 0
        return df
    except Exception as e:
        print(f'  [!] {ticker} 下载失败: {e}')
        return None


# ============================================================
# 组合回测
# ============================================================
def run_portfolio_backtest(config):
    p = config['strategy']
    cash = config['backtest']['initial_cash']
    commission = config['backtest']['commission']
    start = config['backtest']['start_date']
    end   = config['backtest']['end_date']
    tickers = config['tickers']

    print('\n' + '='*65)
    print('  AlphaFlow V9.0 真实组合回测中 (60%指数 / 40%个股)...')
    print('='*65)

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission)

    valid_tickers = []
    for t in tickers:
        df = fetch_data(t, start, end)
        if df is not None and len(df) >= 60:
            data = bt.feeds.PandasData(dataname=df)
            cerebro.adddata(data, name=t)
            valid_tickers.append(t)

    cerebro.addstrategy(
        AlphaFlowStrategy,
        fast_period=p.get('fast_period', 10),
        slow_period=p.get('slow_period', 25),
        trend_period=p.get('trend_period', 200),
        rsi_period=p.get('rsi_period', 14),
        rsi_upper=p.get('rsi_upper', 65),
        adx_period=p.get('adx_period', 14),
        adx_threshold=p.get('adx_threshold', 20),
        atr_period=p.get('atr_period', 14),
        atr_multiplier=p.get('atr_multiplier', 2.5),
        vol_filter_period=p.get('vol_filter_period', 100),
        vol_filter_ratio=p.get('vol_filter_ratio', 0.8),
        trailing_atr_mult=p.get('trailing_atr_mult', 3.0),
        trailing_stop=p.get('trailing_stop', 0.12),
        risk_per_trade=config['risk'].get('risk_per_trade', 0.030),
        alloc_index=config['risk'].get('alloc_index', 0.60),
        alloc_stock=config['risk'].get('alloc_stock', 0.40),
    )

    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.04)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='timereturn')

    initial_value = cerebro.broker.getvalue()
    strats = cerebro.run()
    strat = strats[0]
    
    final_value = cerebro.broker.getvalue()
    total_return = (final_value - initial_value) / initial_value * 100

    sharpe_analysis = strat.analyzers.sharpe.get_analysis()
    dd_analysis = strat.analyzers.drawdown.get_analysis()
    time_returns = strat.analyzers.timereturn.get_analysis()

    sharpe = sharpe_analysis.get('sharperatio', 0.0) or 0.0
    max_dd = dd_analysis.get('max', {}).get('drawdown', 0.0) or 0.0

    return {
        'initial': initial_value,
        'final': final_value,
        'return': total_return,
        'sharpe': sharpe,
        'max_drawdown': max_dd,
        'trade_stats': strat.trade_stats,
        'time_returns': time_returns
    }


# ============================================================
# 打印汇总表格
# ============================================================
def print_summary(res):
    print(f"\n【整体组合表现】")
    print(f"初始资金: ${res['initial']:,.2f}")
    print(f"结束净值: ${res['final']:,.2f}")
    print(f"总收益率: {res['return']:+.2f}%")
    print(f"夏普比率: {res['sharpe']:.2f}")
    print(f"最大回撤: {res['max_drawdown']:.2f}%")

    print(f"\n【各标的贡献 (PnL)】")
    header = f'{"标的":<8} {"净利润(PnL)":>12} {"交易数":>8} {"胜率":>8}'
    print(header)
    print('-' * 42)
    
    stats = res['trade_stats']
    # 转换为列表排序
    sorted_stats = sorted(stats.items(), key=lambda x: x[1]['pnl'], reverse=True)
    
    for ticker, info in sorted_stats:
        pnl = info['pnl']
        trades = info['trades']
        won = info['won']
        win_rate = f"{(won/trades)*100:.0f}%" if trades > 0 else '—'
        flag = '🟢' if pnl > 0 else ('🔴' if pnl < 0 else '⚪')
        print(f'{ticker:<8} ${pnl:>11,.2f} {trades:>8} {win_rate:>8} {flag}')


# ============================================================
# 生成 Equity Curve 图
# ============================================================
def plot_portfolio_equity(res):
    time_returns = res['time_returns']
    if not time_returns:
        return

    # 转换 datetime 和 value
    dates = list(time_returns.keys())
    # timereturn 是每日收益率，需要转换为累计净值
    # 但是 backtrader 的 TimeReturn 如果没有 fund=True，可能只是单期 return
    # 我们自己算复利累计净值
    returns = list(time_returns.values())
    
    # 计算累计收益率
    cumulative = np.cumprod([1.0 + r for r in returns])
    # 减1变成百分比收益
    cumulative_pct = (cumulative - 1.0) * 100

    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    ax.plot(dates, cumulative_pct, color=GREEN, linewidth=1.5, label='Portfolio Return')

    ax.axhline(0, color='white', linewidth=0.5, linestyle='--')
    ax.tick_params(colors='white')
    ax.yaxis.set_major_formatter(mticker.PercentFormatter())
    ax.set_ylabel('累计收益率 (%)', color='white', fontsize=10)
    ax.set_title('AlphaFlow V9.0 真实组合回测资金曲线 (60/40配置)', color='white', fontsize=13, pad=12)

    legend = ax.legend(loc='upper left', framealpha=0.2, labelcolor='white', facecolor='#1C1C1C', edgecolor='none')
    if legend:
        legend.get_frame().set_facecolor('#1C1C1C')

    for spine in ax.spines.values():
        spine.set_edgecolor('#333')

    plt.tight_layout()
    out_path = Path('equity_curve.png')
    plt.savefig(out_path, dpi=150, bbox_inches='tight', facecolor=BG, edgecolor='none')
    plt.close()
    print(f'\n📈 Equity Curve 已保存: {out_path.resolve()}')


# ============================================================
# 主入口
# ============================================================
if __name__ == '__main__':
    config = load_config()
    results = run_portfolio_backtest(config)
    print_summary(results)
    plot_portfolio_equity(results)
    print('\n✅ 回测完成！')