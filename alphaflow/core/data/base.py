"""Market data provider protocol."""

from __future__ import annotations

from typing import Protocol

import pandas as pd


class OHLCVProvider(Protocol):
    """Fetch daily OHLCV bars for a symbol."""

    def fetch_ohlcv(self, ticker: str, start: str, end: str) -> pd.DataFrame | None:
        """Return a DataFrame indexed by date with lowercase OHLCV columns."""
        ...
