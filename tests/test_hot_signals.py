"""Unit tests for hot-stock entry filters."""

import pandas as pd

from alphaflow.hot_config import HotEntryParams
from alphaflow.hot_indicators import compute_intraday_indicators
from alphaflow.hot_signals import check_hot_entry


def _entry_params() -> HotEntryParams:
    return HotEntryParams(
        fast_ema=9,
        slow_ema=21,
        rsi_max=70,
        require_golden_cross=True,
        min_adx=20,
        min_rel_volume=1.2,
        require_bull_market=True,
    )


def test_golden_cross_event_required():
    p = _entry_params()
    ok, reason = check_hot_entry(
        close=100, ema_fast=101, ema_slow=100, rsi=50, vwap=99,
        golden_cross=False, adx=25, rel_volume=1.5, market_bullish=True, params=p,
    )
    assert not ok
    assert reason == 'no_golden_cross'


def test_market_filter_blocks_entry():
    p = _entry_params()
    ok, reason = check_hot_entry(
        close=100, ema_fast=101, ema_slow=100, rsi=50, vwap=99,
        golden_cross=True, adx=25, rel_volume=1.5, market_bullish=False, params=p,
    )
    assert not ok
    assert reason == 'market_not_bullish'


def test_full_entry_passes():
    p = _entry_params()
    ok, reason = check_hot_entry(
        close=100, ema_fast=101, ema_slow=100, rsi=50, vwap=99,
        golden_cross=True, adx=25, rel_volume=1.5, market_bullish=True, params=p,
    )
    assert ok
    assert reason == 'ok'


def test_intraday_indicators_emit_golden_cross():
    p = _entry_params()
    n = 40
    close = pd.Series([100 + i * 0.5 for i in range(n)], dtype=float)
    df = pd.DataFrame({
        'open': close,
        'high': close + 0.2,
        'low': close - 0.2,
        'close': close,
        'volume': [1_000_000 + i * 10_000 for i in range(n)],
    })
    out = compute_intraday_indicators(df, p)
    assert out['golden_cross'].dtype == bool
    assert out['golden_cross'].sum() >= 0
