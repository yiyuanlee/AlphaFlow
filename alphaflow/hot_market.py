"""Benchmark regime filter for hot-stock sleeve (e.g. QQQ above 200 EMA)."""

from __future__ import annotations

from datetime import date
from functools import lru_cache

import pandas as pd

from alphaflow.data import fetch_data
from alphaflow.hot_config import HotMarketFilterParams
from alphaflow.indicators import ema_backtrader


@lru_cache(maxsize=8)
def _benchmark_with_trend(benchmark: str, start: str, end: str, trend_period: int) -> pd.DataFrame | None:
    """Fetch benchmark once and attach trend EMA (cached by start/end, not per-day)."""
    df = fetch_data(benchmark, start, end)
    if df is None or df.empty:
        return None
    out = df.copy()
    out['ema_trend'] = ema_backtrader(out['close'], trend_period)
    out['bullish'] = out['close'] > out['ema_trend']
    return out


def build_market_regime_lookup(
    params: HotMarketFilterParams,
    lookback_start: str,
    replay_end: str,
) -> dict[str, bool]:
    """Precompute bullish/bearish for every bar (used by replay/grid to avoid per-day downloads)."""
    end = (pd.Timestamp(replay_end) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
    ind = _benchmark_with_trend(params.benchmark, lookback_start, end, params.trend_period)
    if ind is None:
        return {}
    return {str(idx.date()): bool(row['bullish']) for idx, row in ind.iterrows()}


def is_market_bullish(
    params: HotMarketFilterParams,
    as_of: date | None = None,
    lookback_start: str = '2018-01-01',
    regime_lookup: dict[str, bool] | None = None,
) -> tuple[bool, dict]:
    """Return whether benchmark close is above trend EMA on as_of date."""
    as_of = as_of or date.today()
    day_key = str(as_of)

    if regime_lookup is not None:
        if day_key not in regime_lookup:
            return False, {'benchmark': params.benchmark, 'reason': 'no_bar', 'date': day_key}
        bullish = regime_lookup[day_key]
        return bullish, {
            'benchmark': params.benchmark,
            'date': day_key,
            'bullish': bullish,
            'source': 'lookup',
        }

    end = (pd.Timestamp(as_of) + pd.Timedelta(days=30)).strftime('%Y-%m-%d')
    ind = _benchmark_with_trend(params.benchmark, lookback_start, end, params.trend_period)
    if ind is None or len(ind) < params.trend_period + 2:
        return False, {'benchmark': params.benchmark, 'reason': 'insufficient_data'}

    day = pd.Timestamp(as_of)
    if day not in ind.index:
        idx = ind.index[ind.index <= day]
        if idx.empty:
            return False, {'benchmark': params.benchmark, 'reason': 'no_bar'}
        day = idx[-1]

    row = ind.loc[day]
    close = float(row['close'])
    trend = float(row['ema_trend'])
    bullish = bool(row['bullish'])
    return bullish, {
        'benchmark': params.benchmark,
        'date': str(day.date()),
        'close': close,
        'ema_trend': trend,
        'bullish': bullish,
    }
