"""Walk-forward validation framework (holdout and rolling)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from alphaflow.equity.engine import run_period_portfolio, run_period_single
from alphaflow.core.config import params_from_config, strategy_params_to_bt
from alphaflow.core.data import fetch_data
from alphaflow.research.grid import (
    DEFAULT_PARAM_GRID,
    QUICK_PARAM_GRID,
    grid_search_portfolio,
    grid_search_single,
    objective_score,
)


@dataclass
class HoldoutWindows:
    train_start: str
    train_end: str
    val_start: str
    val_end: str
    test_start: str
    test_end: str


@dataclass
class WalkForwardConfig:
    mode: str = 'holdout'
    scope: str = 'single'
    tickers: list[str] = field(default_factory=lambda: ['VOO', 'QQQ'])
    objective: str = 'sharpe'
    top_k_train: int = 10
    quick_grid: bool = False
    holdout: HoldoutWindows | None = None
    rolling_train_years: int = 5
    rolling_test_years: int = 1
    rolling_step_years: int = 1
    data_start: str = '2010-01-01'
    data_end: str = '2026-06-03'


def walkforward_config_from_yaml(config: dict) -> WalkForwardConfig:
    wf = config.get('walk_forward', {})
    holdout_cfg = wf.get('holdout', {})
    holdout = HoldoutWindows(
        train_start=holdout_cfg.get('train_start', '2010-01-01'),
        train_end=holdout_cfg.get('train_end', '2020-12-31'),
        val_start=holdout_cfg.get('val_start', '2021-01-01'),
        val_end=holdout_cfg.get('val_end', '2023-12-31'),
        test_start=holdout_cfg.get('test_start', '2024-01-01'),
        test_end=holdout_cfg.get('test_end', config['backtest'].get('end_date', '2026-06-03')),
    )
    return WalkForwardConfig(
        mode=wf.get('mode', 'holdout'),
        scope=wf.get('scope', 'single'),
        tickers=wf.get('tickers', ['VOO', 'QQQ']),
        objective=wf.get('objective', 'sharpe'),
        top_k_train=wf.get('top_k_train', 10),
        quick_grid=wf.get('quick_grid', False),
        holdout=holdout,
        rolling_train_years=wf.get('rolling', {}).get('train_years', 5),
        rolling_test_years=wf.get('rolling', {}).get('test_years', 1),
        rolling_step_years=wf.get('rolling', {}).get('step_years', 1),
        data_start=wf.get('rolling', {}).get('data_start', '2010-01-01'),
        data_end=wf.get('rolling', {}).get('data_end', config['backtest'].get('end_date', '2026-06-03')),
    )


def _param_grid(wf: WalkForwardConfig, config: dict) -> dict:
    if 'param_grid' in config.get('walk_forward', {}):
        return config['walk_forward']['param_grid']
    return QUICK_PARAM_GRID if wf.quick_grid else DEFAULT_PARAM_GRID


def _progress_factory(label: str):
    def _on_progress(done: int, total: int):
        if done % max(total // 10, 1) == 0 or done == total:
            print(f'  {label}: {done}/{total} ({done * 100 // total}%)')
    return _on_progress


def _evaluate_candidates_single(
    ticker: str,
    full_df: pd.DataFrame,
    config: dict,
    base_bt_params: dict,
    candidates: list[dict],
    start: str,
    end: str,
    objective: str,
) -> dict | None:
    best = None
    best_score = float('-inf')
    for cand in candidates:
        bt_params = {**base_bt_params, **cand['params']}
        row = run_period_single(ticker, full_df, config, bt_params, start, end)
        if not row:
            continue
        score = objective_score(row, objective)
        if score > best_score:
            best_score = score
            best = {**row, 'params': cand['params'], 'score': score}
    return best


def _evaluate_candidates_portfolio(
    tickers: list[str],
    data_cache: dict[str, pd.DataFrame],
    config: dict,
    base_bt_params: dict,
    candidates: list[dict],
    start: str,
    end: str,
    objective: str,
) -> dict | None:
    best = None
    best_score = float('-inf')
    for cand in candidates:
        bt_params = {**base_bt_params, **cand['params']}
        row = run_period_portfolio(config, bt_params, start, end, tickers, data_cache)
        if not row:
            continue
        score = objective_score(row, objective)
        if score > best_score:
            best_score = score
            best = {**row, 'params': cand['params'], 'score': score}
    return best


def run_holdout_single(
    ticker: str,
    full_df: pd.DataFrame,
    config: dict,
    base_bt_params: dict,
    wf: WalkForwardConfig,
    param_grid: dict,
) -> dict:
    windows = wf.holdout
    print(f'\n{"=" * 60}')
    print(f'  Walk-Forward Holdout: {ticker}')
    print(f'  Train {windows.train_start} ~ {windows.train_end}')
    print(f'  Val   {windows.val_start} ~ {windows.val_end}')
    print(f'  Test  {windows.test_start} ~ {windows.test_end}')
    print('=' * 60)

    print('\n[1/3] 训练集网格搜索...')
    train_results = grid_search_single(
        ticker, full_df, config, base_bt_params,
        windows.train_start, windows.train_end,
        param_grid, wf.objective,
        on_progress=_progress_factory('train grid'),
    )
    if not train_results:
        return {'ticker': ticker, 'error': 'no train results'}

    top_candidates = train_results[: wf.top_k_train]
    print(f'\n[2/3] 验证集评估 Top-{len(top_candidates)} 候选...')
    val_best = _evaluate_candidates_single(
        ticker, full_df, config, base_bt_params,
        top_candidates, windows.val_start, windows.val_end, wf.objective,
    )
    if not val_best:
        return {'ticker': ticker, 'error': 'no validation result'}

    print('\n[3/3] 测试集最终评估（样本外）...')
    test_bt = {**base_bt_params, **val_best['params']}
    test_result = run_period_single(
        ticker, full_df, config, test_bt,
        windows.test_start, windows.test_end,
    )
    train_best = top_candidates[0]

    return {
        'ticker': ticker,
        'selected_params': val_best['params'],
        'train_best': {
            'params': train_best['params'],
            'return': train_best['return'],
            'sharpe': train_best['sharpe'],
            'max_drawdown': train_best['max_drawdown'],
            'score': train_best['score'],
        },
        'validation': {
            'return': val_best['return'],
            'sharpe': val_best['sharpe'],
            'max_drawdown': val_best['max_drawdown'],
            'score': val_best['score'],
        },
        'test': {
            'return': test_result['return'] if test_result else None,
            'sharpe': test_result['sharpe'] if test_result else None,
            'max_drawdown': test_result['max_drawdown'] if test_result else None,
            'trades': test_result['trades'] if test_result else 0,
        },
        'windows': asdict(windows),
    }


def run_holdout_portfolio(
    tickers: list[str],
    data_cache: dict[str, pd.DataFrame],
    config: dict,
    base_bt_params: dict,
    wf: WalkForwardConfig,
    param_grid: dict,
) -> dict:
    windows = wf.holdout
    print(f'\n{"=" * 60}')
    print(f'  Walk-Forward Holdout: Portfolio ({", ".join(tickers)})')
    print(f'  Train {windows.train_start} ~ {windows.train_end}')
    print(f'  Val   {windows.val_start} ~ {windows.val_end}')
    print(f'  Test  {windows.test_start} ~ {windows.test_end}')
    print('=' * 60)

    print('\n[1/3] 训练集网格搜索...')
    train_results = grid_search_portfolio(
        tickers, data_cache, config, base_bt_params,
        windows.train_start, windows.train_end,
        param_grid, wf.objective,
        on_progress=_progress_factory('train grid'),
    )
    if not train_results:
        return {'scope': 'portfolio', 'error': 'no train results'}

    top_candidates = train_results[: wf.top_k_train]
    print(f'\n[2/3] 验证集评估 Top-{len(top_candidates)} 候选...')
    val_best = _evaluate_candidates_portfolio(
        tickers, data_cache, config, base_bt_params,
        top_candidates, windows.val_start, windows.val_end, wf.objective,
    )
    if not val_best:
        return {'scope': 'portfolio', 'error': 'no validation result'}

    print('\n[3/3] 测试集最终评估（样本外）...')
    test_bt = {**base_bt_params, **val_best['params']}
    test_result = run_period_portfolio(
        config, test_bt, windows.test_start, windows.test_end, tickers, data_cache,
    )

    return {
        'scope': 'portfolio',
        'tickers': tickers,
        'selected_params': val_best['params'],
        'validation': {
            'return': val_best['return'],
            'sharpe': val_best['sharpe'],
            'max_drawdown': val_best['max_drawdown'],
        },
        'test': {
            'return': test_result['return'] if test_result else None,
            'sharpe': test_result['sharpe'] if test_result else None,
            'max_drawdown': test_result['max_drawdown'] if test_result else None,
            'trades': test_result['trades'] if test_result else 0,
        },
        'windows': asdict(windows),
    }


def _rolling_windows(wf: WalkForwardConfig) -> list[tuple[str, str, str, str]]:
    """Return list of (train_start, train_end, test_start, test_end)."""
    windows = []
    data_start = pd.Timestamp(wf.data_start)
    data_end = pd.Timestamp(wf.data_end)

    test_start = data_start + pd.DateOffset(years=wf.rolling_train_years)
    while test_start + pd.DateOffset(years=wf.rolling_test_years) <= data_end:
        train_start = test_start - pd.DateOffset(years=wf.rolling_train_years)
        test_end = test_start + pd.DateOffset(years=wf.rolling_test_years) - pd.DateOffset(days=1)
        if test_end > data_end:
            test_end = data_end
        windows.append((
            train_start.strftime('%Y-%m-%d'),
            (test_start - pd.DateOffset(days=1)).strftime('%Y-%m-%d'),
            test_start.strftime('%Y-%m-%d'),
            test_end.strftime('%Y-%m-%d'),
        ))
        test_start += pd.DateOffset(years=wf.rolling_step_years)
    return windows


def run_rolling_single(
    ticker: str,
    full_df: pd.DataFrame,
    config: dict,
    base_bt_params: dict,
    wf: WalkForwardConfig,
    param_grid: dict,
) -> dict:
    windows = _rolling_windows(wf)
    print(f'\n{"=" * 60}')
    print(f'  Rolling Walk-Forward: {ticker} ({len(windows)} windows)')
    print('=' * 60)

    oos_returns = []
    fold_results = []

    for idx, (train_start, train_end, test_start, test_end) in enumerate(windows, 1):
        print(f'\n--- Fold {idx}/{len(windows)}: train {train_start}~{train_end} | test {test_start}~{test_end} ---')
        train_results = grid_search_single(
            ticker, full_df, config, base_bt_params,
            train_start, train_end, param_grid, wf.objective,
            on_progress=_progress_factory(f'fold {idx}'),
        )
        if not train_results:
            continue

        best_params = train_results[0]['params']
        test_bt = {**base_bt_params, **best_params}
        test_row = run_period_single(ticker, full_df, config, test_bt, test_start, test_end)
        if not test_row:
            continue

        oos_returns.append(test_row['return'])
        fold_results.append({
            'fold': idx,
            'train': f'{train_start} ~ {train_end}',
            'test': f'{test_start} ~ {test_end}',
            'params': best_params,
            'test_return': test_row['return'],
            'test_sharpe': test_row['sharpe'],
            'test_max_drawdown': test_row['max_drawdown'],
        })

    avg_oos = sum(oos_returns) / len(oos_returns) if oos_returns else 0.0
    return {
        'ticker': ticker,
        'mode': 'rolling',
        'folds': fold_results,
        'avg_oos_return': avg_oos,
        'positive_folds': sum(1 for r in oos_returns if r > 0),
        'total_folds': len(oos_returns),
    }


def run_walk_forward(config: dict) -> dict:
    strategy, risk = params_from_config(config)
    base_bt_params = strategy_params_to_bt(strategy, risk)
    wf = walkforward_config_from_yaml(config)
    param_grid = _param_grid(wf, config)

    data_start = wf.holdout.train_start if wf.mode == 'holdout' else wf.data_start
    data_end = wf.holdout.test_end if wf.mode == 'holdout' else wf.data_end

    print('=' * 65)
    print('  AlphaFlow Walk-Forward Validation')
    print(f'  Mode: {wf.mode} | Scope: {wf.scope} | Objective: {wf.objective}')
    print('=' * 65)

    results: dict[str, Any] = {
        'mode': wf.mode,
        'scope': wf.scope,
        'objective': wf.objective,
        'run_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'items': [],
    }

    if wf.scope == 'portfolio':
        data_cache = {}
        for ticker in wf.tickers:
            df = fetch_data(ticker, data_start, data_end)
            if df is not None:
                data_cache[ticker] = df

        if wf.mode == 'holdout':
            item = run_holdout_portfolio(wf.tickers, data_cache, config, base_bt_params, wf, param_grid)
        else:
            item = {'error': 'rolling portfolio mode not yet implemented'}
        results['items'].append(item)
    else:
        for ticker in wf.tickers:
            full_df = fetch_data(ticker, data_start, data_end)
            if full_df is None or len(full_df) < 60:
                print(f'[!] Skip {ticker}: insufficient data')
                continue
            if wf.mode == 'holdout':
                item = run_holdout_single(ticker, full_df, config, base_bt_params, wf, param_grid)
            else:
                item = run_rolling_single(ticker, full_df, config, base_bt_params, wf, param_grid)
            results['items'].append(item)

    return results


def print_walk_forward_summary(results: dict):
    print(f'\n{"=" * 65}')
    print('  Walk-Forward Summary')
    print('=' * 65)

    for item in results.get('items', []):
        if 'error' in item:
            name = item.get('ticker') or item.get('scope', '?')
            print(f'\n{name}: ERROR — {item["error"]}')
            continue

        if item.get('mode') == 'rolling':
            print(f'\n{item["ticker"]} (rolling):')
            print(f'  样本外平均收益: {item["avg_oos_return"]:+.2f}%')
            print(f'  正收益折数: {item["positive_folds"]}/{item["total_folds"]}')
            for fold in item['folds']:
                print(
                    f'  Fold {fold["fold"]} test {fold["test"]}: '
                    f'{fold["test_return"]:+.2f}% | Sharpe {fold["test_sharpe"]:.2f}'
                )
            continue

        name = item.get('ticker') or f'Portfolio({",".join(item.get("tickers", []))})'
        test = item.get('test', {})
        val = item.get('validation', {})
        print(f'\n{name}:')
        print(f'  选定参数: {item.get("selected_params")}')
        print(f'  验证集: 收益 {val.get("return", 0):+.2f}% | Sharpe {val.get("sharpe", 0):.2f} | DD {val.get("max_drawdown", 0):.2f}%')
        print(
            f'  测试集: 收益 {test.get("return", 0):+.2f}% | Sharpe {test.get("sharpe", 0):.2f} | '
            f'DD {test.get("max_drawdown", 0):.2f}% | 交易 {test.get("trades", 0)}'
        )

        test_sharpe = test.get('sharpe') or 0
        gate = 'PASS' if test_sharpe > 0 else 'FAIL'
        print(f'  Phase-0 门槛 (测试集 Sharpe > 0): {gate}')


def save_walk_forward_results(results: dict, path: str = 'walkforward_results.yaml'):
    serializable = yaml.safe_dump(results, allow_unicode=True, default_flow_style=False, sort_keys=False)
    Path(path).write_text(serializable, encoding='utf-8')
    print(f'\n💾 结果已保存: {Path(path).resolve()}')
