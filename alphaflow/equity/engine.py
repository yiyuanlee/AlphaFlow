"""Backtest engine helpers."""

from typing import Any

import backtrader as bt
import pandas as pd

from alphaflow.core.config import RiskParams, StrategyParams, strategy_params_to_bt
from alphaflow.core.data import fetch_data, slice_ohlcv
from alphaflow.equity.backtest import AlphaFlowStrategy


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


def run_with_bt_params(
    df: pd.DataFrame,
    ticker: str,
    config: dict,
    bt_params: dict[str, Any],
    *,
    portfolio_mode: bool = False,
    tickers: list[str] | None = None,
    data_by_ticker: dict[str, pd.DataFrame] | None = None,
) -> dict | None:
    """Run backtest with explicit Backtrader param dict (for grid / walk-forward)."""
    if df is not None and len(df) < 60:
        return None

    cash = config['backtest']['initial_cash']
    commission = config['backtest']['commission']

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission)

    if portfolio_mode:
        if not data_by_ticker:
            return None
        for symbol, frame in data_by_ticker.items():
            if frame is not None and len(frame) >= 60:
                cerebro.adddata(bt.feeds.PandasData(dataname=frame), name=symbol)
    else:
        if df is None:
            return None
        cerebro.adddata(bt.feeds.PandasData(dataname=df), name=ticker)

    cerebro.addstrategy(
        AlphaFlowStrategy,
        portfolio_mode=portfolio_mode,
        **bt_params,
    )
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.04)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')

    strat, initial_value, final_value = _run_cerebro(cerebro)
    total_return = (final_value - initial_value) / initial_value * 100
    sharpe = strat.analyzers.sharpe.get_analysis().get('sharperatio', 0.0) or 0.0
    max_dd = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0.0) or 0.0
    trades = sum(s['trades'] for s in strat.trade_stats.values())

    calmar = total_return / max_dd if max_dd > 0 else 0.0

    return {
        'return': total_return,
        'sharpe': sharpe,
        'max_drawdown': max_dd,
        'calmar': calmar,
        'trades': trades,
        'final': final_value,
        'initial': initial_value,
    }


def run_period_single(
    ticker: str,
    full_df: pd.DataFrame,
    config: dict,
    bt_params: dict[str, Any],
    start: str,
    end: str,
) -> dict | None:
    sliced = slice_ohlcv(full_df, start, end)
    result = run_with_bt_params(sliced, ticker, config, bt_params, portfolio_mode=False)
    if result:
        result['start'] = start
        result['end'] = end
        result['ticker'] = ticker
    return result


def run_period_portfolio(
    config: dict,
    bt_params: dict[str, Any],
    start: str,
    end: str,
    tickers: list[str],
    data_cache: dict[str, pd.DataFrame],
) -> dict | None:
    data_by_ticker = {}
    for ticker in tickers:
        full_df = data_cache.get(ticker)
        if full_df is None:
            continue
        sliced = slice_ohlcv(full_df, start, end)
        if len(sliced) >= 60:
            data_by_ticker[ticker] = sliced

    if not data_by_ticker:
        return None

    result = run_with_bt_params(
        None,
        '',
        config,
        bt_params,
        portfolio_mode=True,
        data_by_ticker=data_by_ticker,
    )
    if result:
        result['start'] = start
        result['end'] = end
        result['tickers'] = list(data_by_ticker.keys())
    return result
