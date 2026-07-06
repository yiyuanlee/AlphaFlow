"""Local CSV cache for OHLCV data."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import pandas as pd

from alphaflow.core.config import output_path
from alphaflow.core.data.yfinance import fetch_ohlcv_yfinance

logger = logging.getLogger(__name__)

CACHE_DIR = output_path("cache/ohlcv")


def _cache_key(ticker: str, start: str, end: str) -> str:
    raw = f"{ticker.upper()}|{start}|{end}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def cache_file(ticker: str, start: str, end: str) -> Path:
    return CACHE_DIR / f"{ticker.upper()}_{_cache_key(ticker, start, end)}.csv"


def read_cache(ticker: str, start: str, end: str) -> pd.DataFrame | None:
    path = cache_file(ticker, start, end)
    if not path.is_file():
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df.empty:
            return None
        return df
    except Exception as exc:
        logger.warning("Failed to read OHLCV cache %s: %s", path, exc)
        return None


def write_cache(ticker: str, start: str, end: str, df: pd.DataFrame) -> None:
    path = cache_file(ticker, start, end)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path)


def fetch_ohlcv_cached(
    ticker: str,
    start: str,
    end: str,
    *,
    use_cache: bool = True,
) -> pd.DataFrame | None:
    """Fetch OHLCV, reading/writing a local CSV cache when enabled."""
    if use_cache:
        cached = read_cache(ticker, start, end)
        if cached is not None and not cached.empty:
            return cached

    df = fetch_ohlcv_yfinance(ticker, start, end)
    if df is not None and use_cache:
        try:
            write_cache(ticker, start, end, df)
        except Exception as exc:
            logger.warning("Failed to write OHLCV cache for %s: %s", ticker, exc)
    return df
