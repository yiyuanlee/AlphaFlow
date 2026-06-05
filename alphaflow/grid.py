"""Parameter grid search utilities."""

from __future__ import annotations

import itertools
from typing import Any, Callable

import pandas as pd

from alphaflow.backtest import run_period_single, run_period_portfolio

DEFAULT_PARAM_GRID: dict[str, list] = {
    'fast_period': [8, 10, 12, 15],
    'slow_period': [20, 25, 30, 35],
    'rsi_upper': [60, 65, 70],
    'adx_threshold': [15, 20, 25],
    'atr_multiplier': [2.0, 2.5, 3.0],
    'trailing_stop': [0.10, 0.12, 0.15],
}

QUICK_PARAM_GRID: dict[str, list] = {
    'fast_period': [10, 12],
    'slow_period': [25, 30],
    'rsi_upper': [60, 65],
    'adx_threshold': [20, 25],
    'atr_multiplier': [2.5, 3.0],
    'trailing_stop': [0.10, 0.12],
}


def objective_score(result: dict, objective: str) -> float:
    """Higher is better."""
    if objective == 'return':
        return result['return']
    if objective == 'calmar':
        return result['calmar']
    if objective == 'sharpe':
        sharpe = result['sharpe']
        if sharpe != 0:
            return sharpe
        return result['return'] - 0.5 * result['max_drawdown']
    raise ValueError(f'Unknown objective: {objective}')


def iter_param_combos(param_grid: dict[str, list]) -> list[dict[str, Any]]:
    keys = list(param_grid.keys())
    return [dict(zip(keys, combo)) for combo in itertools.product(*param_grid.values())]


def grid_search_single(
    ticker: str,
    full_df: pd.DataFrame,
    config: dict,
    base_bt_params: dict[str, Any],
    start: str,
    end: str,
    param_grid: dict[str, list],
    objective: str = 'sharpe',
    on_progress: Callable[[int, int], None] | None = None,
) -> list[dict]:
    combos = iter_param_combos(param_grid)
    results = []
    total = len(combos)

    for i, overrides in enumerate(combos, 1):
        bt_params = {**base_bt_params, **overrides}
        if bt_params['fast_period'] >= bt_params['slow_period']:
            if on_progress:
                on_progress(i, total)
            continue

        row = run_period_single(ticker, full_df, config, bt_params, start, end)
        if row:
            row['params'] = overrides
            row['score'] = objective_score(row, objective)
            results.append(row)
        if on_progress:
            on_progress(i, total)

    results.sort(key=lambda x: x['score'], reverse=True)
    return results


def grid_search_portfolio(
    tickers: list[str],
    data_cache: dict[str, pd.DataFrame],
    config: dict,
    base_bt_params: dict[str, Any],
    start: str,
    end: str,
    param_grid: dict[str, list],
    objective: str = 'sharpe',
    on_progress: Callable[[int, int], None] | None = None,
) -> list[dict]:
    combos = iter_param_combos(param_grid)
    results = []
    total = len(combos)

    for i, overrides in enumerate(combos, 1):
        bt_params = {**base_bt_params, **overrides}
        if bt_params['fast_period'] >= bt_params['slow_period']:
            if on_progress:
                on_progress(i, total)
            continue

        row = run_period_portfolio(config, bt_params, start, end, tickers, data_cache)
        if row:
            row['params'] = overrides
            row['score'] = objective_score(row, objective)
            results.append(row)
        if on_progress:
            on_progress(i, total)

    results.sort(key=lambda x: x['score'], reverse=True)
    return results
