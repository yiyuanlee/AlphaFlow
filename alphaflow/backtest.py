"""Backtest engine helpers."""

from typing import Any

import backtrader as bt

from alphaflow.config import RiskParams, StrategyParams, strategy_params_to_bt
from alphaflow.data import fetch_data
from alphaflow.strategy import AlphaFlowStrategy


def _run_cerebro(cerebro: bt.Cerebro) -> tuple[Any, float, float]:
    initial_value = cerebro.broker.getvalue()
    strats = cerebro.run()
    strat = strats[0]
    final_value = cerebro.broker.getvalue()
    return strat, initial_value, final_value


def run_portfolio_backtest(
    config: dict,
    strategy: StrategyParams,
    risk: RiskParams,
) -> dict:
    cash = config['backtest']['initial_cash']
    commission = config['backtest']['commission']
    start = config['backtest']['start_date']
    end = config['backtest']['end_date']
    tickers = config['tickers']

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission)

    for ticker in tickers:
        df = fetch_data(ticker, start, end)
        if df is not None and len(df) >= 60:
            cerebro.adddata(bt.feeds.PandasData(dataname=df), name=ticker)

    cerebro.addstrategy(
        AlphaFlowStrategy,
        portfolio_mode=True,
        **strategy_params_to_bt(strategy, risk),
    )
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.04)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='timereturn')

    strat, initial_value, final_value = _run_cerebro(cerebro)
    total_return = (final_value - initial_value) / initial_value * 100

    sharpe_analysis = strat.analyzers.sharpe.get_analysis()
    dd_analysis = strat.analyzers.drawdown.get_analysis()
    time_returns = strat.analyzers.timereturn.get_analysis()

    return {
        'initial': initial_value,
        'final': final_value,
        'return': total_return,
        'sharpe': sharpe_analysis.get('sharperatio', 0.0) or 0.0,
        'max_drawdown': dd_analysis.get('max', {}).get('drawdown', 0.0) or 0.0,
        'trade_stats': strat.trade_stats,
        'time_returns': time_returns,
    }


def run_single_ticker_backtest(
    ticker: str,
    config: dict,
    strategy: StrategyParams,
    risk: RiskParams,
    df=None,
) -> dict | None:
    cash = config['backtest']['initial_cash']
    commission = config['backtest']['commission']
    start = config['backtest']['start_date']
    end = config['backtest']['end_date']

    if df is None:
        df = fetch_data(ticker, start, end)
    if df is None or len(df) < 60:
        return None

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission)
    cerebro.adddata(bt.feeds.PandasData(dataname=df), name=ticker)
    cerebro.addstrategy(
        AlphaFlowStrategy,
        portfolio_mode=False,
        **strategy_params_to_bt(strategy, risk),
    )
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.04)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')

    strat, initial_value, final_value = _run_cerebro(cerebro)
    total_return = (final_value - initial_value) / initial_value * 100
    sharpe = strat.analyzers.sharpe.get_analysis().get('sharperatio', 0.0) or 0.0
    max_dd = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0.0) or 0.0
    stats = strat.trade_stats.get(ticker, {'trades': 0, 'won': 0, 'pnl': 0.0})

    return {
        'ticker': ticker,
        'return': total_return,
        'sharpe': sharpe,
        'max_drawdown': max_dd,
        'trades': stats['trades'],
        'won': stats['won'],
        'pnl': stats['pnl'],
        'final': final_value,
    }


def run_all_single_ticker_backtests(
    config: dict,
    strategy: StrategyParams,
    risk: RiskParams,
) -> list[dict]:
    start = config['backtest']['start_date']
    end = config['backtest']['end_date']
    results = []
    for ticker in config['tickers']:
        df = fetch_data(ticker, start, end)
        row = run_single_ticker_backtest(ticker, config, strategy, risk, df=df)
        if row:
            results.append(row)
    results.sort(key=lambda x: x['return'], reverse=True)
    return results
