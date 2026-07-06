"""Yahoo Finance OHLCV provider."""

from __future__ import annotations

import logging

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


def fetch_ohlcv_yfinance(ticker: str, start: str, end: str) -> pd.DataFrame | None:
    """Download adjusted daily OHLCV from Yahoo Finance."""
    try:
        df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.lower() for c in df.columns]
        df["openinterest"] = 0
        return df
    except Exception as exc:
        logger.warning("yfinance download failed for %s: %s", ticker, exc)
        return None
