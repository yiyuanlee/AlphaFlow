"""Market data access layer."""

from __future__ import annotations

import pandas as pd

from alphaflow.core.data.cache import fetch_ohlcv_cached
from alphaflow.core.data.yfinance import fetch_ohlcv_yfinance

__all__ = [
    "fetch_data",
    "fetch_ohlcv_cached",
    "fetch_ohlcv_yfinance",
    "slice_ohlcv",
]


def slice_ohlcv(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    """Slice OHLCV data to an inclusive date window."""
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    return df.loc[(df.index >= start_ts) & (df.index <= end_ts)].copy()


def fetch_data(
    ticker: str,
    start: str,
    end: str,
    *,
    use_cache: bool = True,
) -> pd.DataFrame | None:
    """Fetch daily OHLCV (cached Parquet when ``use_cache`` is True)."""
    if use_cache:
        return fetch_ohlcv_cached(ticker, start, end, use_cache=True)
    return fetch_ohlcv_yfinance(ticker, start, end)
