"""
AlphaFlow - 真实组合回测入口
===========================
所有标的在同一个资金池中共同交易，相互竞争资金。
资金分配规则：60% 资金上限用于指数类 (VOO, QQQ)，40% 资金上限用于个股类。
用法: python backtest_main.py
"""

import sys
import io

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
from pathlib import Path

from alphaflow.backtest import run_all_single_ticker_backtests, run_portfolio_backtest
from alphaflow.config import load_config, params_from_config

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False

GREEN = '#10B981'
BG = '#0D1117'


def print_portfolio_summary(res, config):
    start = config['backtest']['start_date']
    end = config['backtest']['end_date']
    print(f"\n【整体组合表现】({start} ~ {end})")
    print(f"初始资金: ${res['initial']:,.2f}")
    print(f"结束净值: ${res['final']:,.2f}")
    print(f"总收益率: {res['return']:+.2f}%")
    print(f"夏普比率: {res['sharpe']:.2f}")
    print(f"最大回撤: {res['max_drawdown']:.2f}%")

    print(f"\n【各标的贡献 (PnL)】")
    header = f'{"标的":<8} {"净利润(PnL)":>12} {"交易数":>8} {"胜率":>8}'
    print(header)
    print('-' * 42)

    sorted_stats = sorted(res['trade_stats'].items(), key=lambda x: x[1]['pnl'], reverse=True)
    for ticker, info in sorted_stats:
        pnl = info['pnl']
        trades = info['trades']
        won = info['won']
        win_rate = f"{(won / trades) * 100:.0f}%" if trades > 0 else '—'
        flag = '🟢' if pnl > 0 else ('🔴' if pnl < 0 else '⚪')
        print(f'{ticker:<8} ${pnl:>11,.2f} {trades:>8} {win_rate:>8} {flag}')


def print_single_ticker_table(rows):
    print(f"\n【单标的独立回测（各 $10,000 独立资金池）】")
    header = f'{"标的":<8} {"收益率":>8} {"夏普":>6} {"最大回撤":>8} {"交易数":>6} {"胜率":>6}'
    print(header)
    print('-' * 50)

    total_return = 0.0
    count = 0
    for row in rows:
        win_rate = f"{(row['won'] / row['trades']) * 100:.0f}%" if row['trades'] > 0 else '—'
        flag = '🟢' if row['return'] > 0 else ('🔴' if row['return'] < 0 else '⚪')
        print(
            f"{row['ticker']:<8} {row['return']:>+7.2f}% "
            f"{row['sharpe']:>6.2f} {row['max_drawdown']:>7.2f}% "
            f"{row['trades']:>6} {win_rate:>6} {flag}"
        )
        total_return += row['return']
        count += 1

    if count:
        print('-' * 50)
        print(f"{'平均':<8} {total_return / count:>+7.2f}%")


def plot_portfolio_equity(res):
    time_returns = res['time_returns']
    if not time_returns:
        return

    dates = list(time_returns.keys())
    returns = list(time_returns.values())
    cumulative_pct = (np.cumprod([1.0 + r for r in returns]) - 1.0) * 100

    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.plot(dates, cumulative_pct, color=GREEN, linewidth=1.5, label='Portfolio Return')
    ax.axhline(0, color='white', linewidth=0.5, linestyle='--')
    ax.tick_params(colors='white')
    ax.yaxis.set_major_formatter(mticker.PercentFormatter())
    ax.set_ylabel('累计收益率 (%)', color='white', fontsize=10)
    ax.set_title('AlphaFlow 真实组合回测资金曲线 (60/40配置)', color='white', fontsize=13, pad=12)
    legend = ax.legend(loc='upper left', framealpha=0.2, labelcolor='white')
    if legend:
        legend.get_frame().set_facecolor('#1C1C1C')
    for spine in ax.spines.values():
        spine.set_edgecolor('#333')

    plt.tight_layout()
    out_path = Path('equity_curve.png')
    plt.savefig(out_path, dpi=150, bbox_inches='tight', facecolor=BG, edgecolor='none')
    plt.close()
    print(f'\n📈 Equity Curve 已保存: {out_path.resolve()}')


if __name__ == '__main__':
    config = load_config()
    strategy, risk = params_from_config(config)

    print('\n' + '=' * 65)
    print('  AlphaFlow 真实组合回测 (60%指数 / 40%个股)...')
    print('=' * 65)

    portfolio = run_portfolio_backtest(config, strategy, risk)
    print_portfolio_summary(portfolio, config)

    singles = run_all_single_ticker_backtests(config, strategy, risk)
    print_single_ticker_table(singles)

    plot_portfolio_equity(portfolio)
    print('\n✅ 回测完成！')
