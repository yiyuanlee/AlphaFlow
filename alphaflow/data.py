"""Market data helpers."""

import pandas as pd
import yfinance as yf


def slice_ohlcv(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    """Slice OHLCV data to an inclusive date window."""
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    return df.loc[(df.index >= start_ts) & (df.index <= end_ts)].copy()


def fetch_data(ticker: str, start: str, end: str) -> pd.DataFrame | None:
    try:
        df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.lower() for c in df.columns]
        df['openinterest'] = 0
        return df
    except Exception:
        return None
