"""Tests for core.data (OHLCV slice + cache)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from alphaflow.core.data import fetch_data, slice_ohlcv
from alphaflow.core.data.cache import cache_file, fetch_ohlcv_cached, read_cache, write_cache


def _sample_df() -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=5, freq="D")
    return pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0, 103.0, 104.0],
            "high": [101.0, 102.0, 103.0, 104.0, 105.0],
            "low": [99.0, 100.0, 101.0, 102.0, 103.0],
            "close": [100.5, 101.5, 102.5, 103.5, 104.5],
            "volume": [1_000_000] * 5,
            "openinterest": [0] * 5,
        },
        index=idx,
    )


def test_slice_ohlcv_inclusive():
    df = _sample_df()
    sliced = slice_ohlcv(df, "2024-01-02", "2024-01-04")
    assert len(sliced) == 3
    assert sliced.index[0] == pd.Timestamp("2024-01-02")


def test_cache_roundtrip(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("alphaflow.core.data.cache.CACHE_DIR", tmp_path)
    df = _sample_df()
    write_cache("QQQ", "2024-01-01", "2024-01-05", df)
    path = cache_file("QQQ", "2024-01-01", "2024-01-05")
    assert path.is_file()
    loaded = read_cache("QQQ", "2024-01-01", "2024-01-05")
    assert loaded is not None
    assert len(loaded) == 5


def test_fetch_ohlcv_cached_uses_cache(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("alphaflow.core.data.cache.CACHE_DIR", tmp_path)
    df = _sample_df()
    write_cache("VOO", "2024-01-01", "2024-01-05", df)

    def _fail_download(*_args, **_kwargs):
        raise RuntimeError("should not call yfinance when cache hit")

    monkeypatch.setattr("alphaflow.core.data.cache.fetch_ohlcv_yfinance", _fail_download)
    result = fetch_ohlcv_cached("VOO", "2024-01-01", "2024-01-05")
    assert result is not None
    assert len(result) == 5


def test_fetch_data_compat_reexport():
    assert callable(fetch_data)
