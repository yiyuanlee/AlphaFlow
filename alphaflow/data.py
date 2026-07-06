"""Market data helpers (compat re-export).

Prefer ``alphaflow.core.data`` for new code.
"""

from alphaflow.core.data import fetch_data, slice_ohlcv

__all__ = ["fetch_data", "slice_ohlcv"]
