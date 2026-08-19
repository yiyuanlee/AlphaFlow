from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from alphaflow.scalping.clock import XnysClock
from alphaflow.scalping.config import OrbStrategyConfig, ScalpExecutionConfig, ScalpRiskConfig
from alphaflow.scalping.strategy import (
    build_bracket_intent,
    compute_features,
    position_size,
    quote_is_executable,
    risk_per_share,
    signal_at,
)
from alphaflow.scalping.types import ScalpDirection, ScalpSignal, StockQuote


def _feature_rows(direction: ScalpDirection) -> pd.DataFrame:
    index = pd.DatetimeIndex(["2026-08-19 13:59:00+00:00", "2026-08-19 14:00:00+00:00"])
    if direction is ScalpDirection.LONG:
        closes, ema_fast, ema_slow, vwap = [99.99, 100.02], 100.1, 100.0, 99.9
    else:
        closes, ema_fast, ema_slow, vwap = [99.01, 98.98], 98.9, 99.0, 99.1
    return pd.DataFrame(
        {
            "session_date": [date(2026, 8, 19)] * 2,
            "close": closes,
            "opening_range_high": [100.0] * 2,
            "opening_range_low": [99.0] * 2,
            "vwap": [vwap] * 2,
            "ema_fast": [ema_fast] * 2,
            "ema_slow": [ema_slow] * 2,
            "relative_volume": [2.0] * 2,
            "atr14": [0.20] * 2,
        },
        index=index,
    )


@pytest.mark.parametrize("direction", [ScalpDirection.LONG, ScalpDirection.SHORT])
def test_long_and_short_signals_are_symmetric(direction: ScalpDirection):
    signal = signal_at(_feature_rows(direction), 1, OrbStrategyConfig())
    assert signal is not None
    assert signal.direction is direction


def test_relative_volume_excludes_current_bar():
    index = pd.date_range("2026-08-19 13:30:00+00:00", periods=21, freq="min")
    bars = pd.DataFrame(
        {
            "open": [100.0] * 21,
            "high": [100.1] * 21,
            "low": [99.9] * 21,
            "close": [100.0] * 21,
            "volume": [100] * 20 + [1000],
        },
        index=index,
    )
    features = compute_features(bars, OrbStrategyConfig())
    assert features.iloc[-1]["relative_volume"] == pytest.approx(10.0)
    assert features.iloc[14]["relative_volume"] != features.iloc[14]["relative_volume"]  # NaN before 15 priors


def test_risk_and_position_size_enforce_all_three_caps():
    risk = ScalpRiskConfig()
    assert risk_per_share(100.0, 0.2, risk) == pytest.approx(0.10)
    assert risk_per_share(100.0, 1.0, risk) is None
    quantity = position_size(
        entry_price=100.0,
        per_share_risk=0.10,
        opening_net_liquidation=100_000.0,
        available_funds=15_000.0,
        config=risk,
    )
    assert quantity == 150  # funds cap beats 2,000 risk shares and 1,000 notional shares


@pytest.mark.parametrize(
    ("spread", "age_seconds", "delayed", "reason"),
    [
        (0.04, 0, False, "spread"),
        (0.01, 3, False, "stale"),
        (0.01, 0, True, "delayed"),
    ],
)
def test_invalid_quotes_are_rejected(spread: float, age_seconds: int, delayed: bool, reason: str):
    now = datetime.now(timezone.utc)
    quote = StockQuote(
        "SPY",
        100.0,
        100.0 + spread,
        100.0,
        now - timedelta(seconds=age_seconds),
        delayed=delayed,
    )
    ok, message = quote_is_executable(quote, now, ScalpExecutionConfig())
    assert not ok
    assert reason in message


def test_bracket_intent_is_stable_and_prices_cannot_expand_planned_risk():
    signal = ScalpSignal(
        ScalpDirection.LONG,
        date(2026, 8, 19),
        datetime(2026, 8, 19, 14, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 19, 10, 0, tzinfo=timezone(timedelta(hours=-4))),
        100.0,
        100.0,
        99.0,
        99.8,
        100.1,
        100.0,
        2.0,
        0.2,
    )
    quote = StockQuote("SPY", 100.00, 100.01, 100.0, datetime.now(timezone.utc))
    first = build_bracket_intent(signal, quote, 100, 0.10, ScalpRiskConfig(), ScalpExecutionConfig())
    second = build_bracket_intent(signal, quote, 100, 0.10, ScalpRiskConfig(), ScalpExecutionConfig())
    assert first == second
    assert first.parent_order_ref.startswith("AFSCALP-")
    assert first.entry_limit - first.stop_price <= 0.10 + 1e-9
    assert first.take_profit_price - first.entry_limit <= 0.15 + 1e-9


def test_xnys_clock_handles_dst_and_half_days():
    clock = XnysClock()
    before_dst = clock.schedule(date(2026, 3, 6))
    after_dst = clock.schedule(date(2026, 3, 9))
    half_day = clock.schedule(date(2026, 11, 27))
    assert before_dst and before_dst.open_utc.hour == 14
    assert after_dst and after_dst.open_utc.hour == 13
    assert half_day and half_day.close_et.hour == 13
    assert half_day.force_flat_at().astimezone(half_day.close_et.tzinfo).strftime("%H:%M") == "12:45"
    assert clock.schedule(date(2026, 12, 25)) is None
