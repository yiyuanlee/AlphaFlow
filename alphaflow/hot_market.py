"""Benchmark regime filter for hot-stock sleeve (e.g. QQQ above 200 EMA)."""

from __future__ import annotations

from datetime import date
from functools import lru_cache

import pandas as pd

from alphaflow.data import fetch_data
from alphaflow.hot_config import HotMarketFilterParams
from alphaflow.indicators import ema_backtrader


@lru_cache(maxsize=4)
def _benchmark_history(benchmark: str, start: str, end: str) -> pd.DataFrame | None:
    return fetch_data(benchmark, start, end)


def is_market_bullish(
    params: HotMarketFilterParams,
    as_of: date | None = None,
    lookback_start: str = '2018-01-01',
) -> tuple[bool, dict]:
    """Return whether benchmark close is above trend EMA on as_of date."""
    as_of = as_of or date.today()
    end = (pd.Timestamp(as_of) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
    df = _benchmark_history(params.benchmark, lookback_start, end)
    if df is None or len(df) < params.trend_period + 2:
        return False, {'benchmark': params.benchmark, 'reason': 'insufficient_data'}

    ind = df.copy()
    ind['ema_trend'] = ema_backtrader(ind['close'], params.trend_period)
    day = pd.Timestamp(as_of)
    if day not in ind.index:
        idx = ind.index[ind.index <= day]
        if idx.empty:
            return False, {'benchmark': params.benchmark, 'reason': 'no_bar'}
        day = idx[-1]
    else:
        day = day

    row = ind.loc[day]
    close = float(row['close'])
    trend = float(row['ema_trend'])
    bullish = close > trend
    return bullish, {
        'benchmark': params.benchmark,
        'date': str(day.date()),
        'close': close,
        'ema_trend': trend,
        'bullish': bullish,
    }
