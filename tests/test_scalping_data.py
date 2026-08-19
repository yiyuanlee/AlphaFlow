from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from alphaflow.scalping.data import MinuteBarCache, minute_bar_from_utc


def test_compressed_minute_cache_deduplicates_and_keeps_et_utc(tmp_path: Path):
    cache = MinuteBarCache(tmp_path / "SPY.csv.gz")
    timestamp = datetime(2026, 8, 19, 13, 30, tzinfo=timezone.utc)
    original = minute_bar_from_utc(timestamp, 600.0, 600.2, 599.9, 600.1, 1000)
    corrected = minute_bar_from_utc(timestamp, 600.0, 600.3, 599.9, 600.2, 1100)
    assert cache.merge([original]) == 1
    assert cache.merge([corrected]) == 0
    loaded = cache.read()
    assert len(loaded) == 1
    assert loaded[0].close == 600.2
    assert loaded[0].timestamp_et.hour == 9
    assert loaded[0].timestamp_utc == timestamp
    assert cache.path.read_bytes()[:2] == b"\x1f\x8b"


def test_cache_rejects_invalid_ohlc(tmp_path: Path):
    cache = MinuteBarCache(tmp_path / "SPY.csv.gz")
    bad = minute_bar_from_utc(
        datetime(2026, 8, 19, 13, 30, tzinfo=timezone.utc),
        600.0,
        599.0,
        598.0,
        600.0,
        100,
    )
    with pytest.raises(ValueError, match="invalid OHLC"):
        cache.merge([bad])
