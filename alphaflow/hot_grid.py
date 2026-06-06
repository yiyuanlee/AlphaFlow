"""Parameter sensitivity grid for hot-stock daily replay."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

import yaml

from alphaflow.grid import iter_param_combos
from alphaflow.hot_config import HotEntryParams, HotTradingConfig, hot_config_from_yaml
from alphaflow.hot_replay import (
    INDICATOR_PARAM_KEYS,
    ReplayContext,
    build_replay_indicators,
    load_replay_context,
    run_daily_replay,
    summarize_replay,
)

DEFAULT_HOT_GRID: dict[str, list] = {
    'min_adx': [15, 18, 20, 22, 25],
    'min_rel_volume': [1.0, 1.1, 1.2, 1.3, 1.5],
    'rsi_max': [65, 70, 75],
    'require_golden_cross': [True, False],
}

QUICK_HOT_GRID: dict[str, list] = {
    'min_adx': [15, 20, 25],
    'min_rel_volume': [1.0, 1.2, 1.5],
    'rsi_max': [65, 70, 75],
    'require_golden_cross': [True, False],
}

EMA_HOT_GRID: dict[str, list] = {
    'fast_ema': [8, 9, 12],
    'slow_ema': [18, 21, 25],
    'min_adx': [15, 20],
    'min_rel_volume': [1.0, 1.2],
}


def hot_objective_score(summary: dict[str, Any], objective: str) -> float:
    trades = int(summary.get('trades', 0))
    ret = float(summary.get('total_return_pct', 0.0))
    max_dd = abs(float(summary.get('max_drawdown_pct', 0.0)))

    if objective == 'return':
        return ret
    if objective == 'trades':
        return float(trades)
    if objective == 'profit_factor':
        return float(summary.get('profit_factor', 0.0)) if trades else -999.0
    if objective == 'balanced':
        if trades == 0:
            return -999.0
        pf = float(summary.get('profit_factor', 0.0))
        return ret - 0.5 * max_dd + min(trades, 20) * 0.25 + pf * 2.0
    raise ValueError(f'Unknown objective: {objective}')


def _coerce_entry_overrides(overrides: dict[str, Any]) -> dict[str, Any]:
    out = dict(overrides)
    for key in ('fast_ema', 'slow_ema', 'rsi_period', 'adx_period', 'rel_volume_period'):
        if key in out:
            out[key] = int(out[key])
    for key in ('min_adx', 'min_rel_volume', 'rsi_max'):
        if key in out:
            out[key] = float(out[key])
    if 'require_golden_cross' in out:
        out['require_golden_cross'] = bool(out['require_golden_cross'])
    return out


def _apply_hot_overrides(base: HotTradingConfig, overrides: dict[str, Any]) -> HotTradingConfig:
    overrides = _coerce_entry_overrides(overrides)
    entry = replace(base.entry, **overrides)
    return replace(base, entry=entry)


def _needs_indicator_rebuild(overrides: dict[str, Any]) -> bool:
    return bool(INDICATOR_PARAM_KEYS.intersection(overrides))


def run_hot_grid_search(
    config: dict[str, Any],
    param_grid: dict[str, list] | None = None,
    *,
    quick: bool = False,
    objective: str = 'balanced',
    top_k: int = 15,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    base_hot = hot_config_from_yaml(config)
    param_grid = param_grid or (QUICK_HOT_GRID if quick else DEFAULT_HOT_GRID)
    combos = iter_param_combos(param_grid)

    context = load_replay_context(config, base_hot)
    indicator_cache: dict[tuple, dict] = {}

    def _indicator_key(entry: HotEntryParams) -> tuple:
        return (
            entry.fast_ema,
            entry.slow_ema,
            entry.rsi_period,
            entry.adx_period,
            entry.rel_volume_period,
        )

    indicator_cache[_indicator_key(base_hot.entry)] = context.indicators

    rows: list[dict[str, Any]] = []
    total = len(combos)

    for i, overrides in enumerate(combos, 1):
        hot = _apply_hot_overrides(base_hot, overrides)

        if hot.entry.fast_ema >= hot.entry.slow_ema:
            if on_progress:
                on_progress(i, total)
            continue

        key = _indicator_key(hot.entry)
        if key not in indicator_cache:
            indicator_cache[key] = build_replay_indicators(context.ohlcv, hot.entry)

        run_context = ReplayContext(
            ohlcv=context.ohlcv,
            indicators=indicator_cache[key],
            trading_days=context.trading_days,
            warmup_start=context.warmup_start,
        )

        result = run_daily_replay(config, hot, run_context)
        summary = summarize_replay(result)
        summary['params'] = overrides
        summary['score'] = hot_objective_score(summary, objective)
        rows.append(summary)

        if on_progress:
            on_progress(i, total)

    rows.sort(key=lambda x: x['score'], reverse=True)
    return {
        'objective': objective,
        'grid_size': total,
        'evaluated': len(rows),
        'top_k': rows[:top_k],
        'all_results': rows,
    }


def format_hot_grid_table(results: dict[str, Any], limit: int = 15) -> str:
    lines = [
        '=' * 72,
        f"  Hot-Stock Grid Search (objective={results.get('objective')})",
        f"  Evaluated: {results.get('evaluated')} / {results.get('grid_size')}",
        '=' * 72,
        f"  {'Rank':<5} {'Score':>8} {'Return%':>9} {'Trades':>7} {'Win%':>7} {'PF':>6} {'MaxDD%':>8}  Params",
    ]
    for rank, row in enumerate(results.get('top_k', [])[:limit], 1):
        params = row.get('params', {})
        param_str = ', '.join(f'{k}={v}' for k, v in params.items())
        lines.append(
            f"  {rank:<5} {row.get('score', 0):>8.2f} "
            f"{row.get('total_return_pct', 0):>+8.2f}% "
            f"{row.get('trades', 0):>7} "
            f"{row.get('win_rate_pct', 0):>6.1f}% "
            f"{row.get('profit_factor', 0):>6.2f} "
            f"{row.get('max_drawdown_pct', 0):>7.2f}%  {param_str}"
        )
    return '\n'.join(lines)


def save_hot_grid_results(results: dict[str, Any], path: str) -> None:
    serializable = {
        'objective': results['objective'],
        'grid_size': results['grid_size'],
        'evaluated': results['evaluated'],
        'top_k': results['top_k'],
    }
    with open(path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(serializable, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
