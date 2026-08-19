from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone

import pandas as pd

from alphaflow.scalping.backtest import run_backtest
from alphaflow.scalping.config import ScalpBacktestConfig, ScalpConfig
from alphaflow.scalping.types import ScalpDirection, ScalpSignal


def _bars() -> pd.DataFrame:
    index = pd.date_range("2026-08-19 13:30:00+00:00", periods=60, freq="min")
    return pd.DataFrame(
        {
            "open": [100.0] * 60,
            "high": [100.02] * 60,
            "low": [99.98] * 60,
            "close": [100.0] * 60,
            "volume": [1000] * 60,
        },
        index=index,
    )


def _signal(timestamp: datetime) -> ScalpSignal:
    return ScalpSignal(
        ScalpDirection.LONG,
        date(2026, 8, 19),
        timestamp,
        timestamp.astimezone(timezone.utc),
        100.0,
        100.0,
        99.0,
        99.9,
        100.1,
        100.0,
        2.0,
        0.2,
    )


def test_signal_fills_only_on_next_bar_and_charges_both_costs(monkeypatch):
    bars = _bars()
    config = replace(
        ScalpConfig(),
        backtest=replace(ScalpBacktestConfig(), minimum_total_trades=1),
    )

    def fake_signal(features, position, _config):
        if position == 20:
            return _signal(features.index[position].to_pydatetime())
        return None

    monkeypatch.setattr("alphaflow.scalping.backtest.signal_at", fake_signal)
    bars.iloc[22, bars.columns.get_loc("high")] = 101.0
    result = run_backtest(bars, config, minimum_trades=1)
    trade = result.trades[0]
    assert trade.signal_time_utc == bars.index[20].to_pydatetime()
    assert trade.entry_time_utc == bars.index[21].to_pydatetime()
    assert trade.entry_price > bars.iloc[21]["open"]
    assert trade.commission >= 2.0
    assert trade.slippage > 0


def test_same_bar_target_and_stop_uses_stop_first(monkeypatch):
    bars = _bars()

    def fake_signal(features, position, _config):
        return _signal(features.index[position].to_pydatetime()) if position == 20 else None

    monkeypatch.setattr("alphaflow.scalping.backtest.signal_at", fake_signal)
    bars.iloc[21, bars.columns.get_loc("high")] = 101.0
    bars.iloc[21, bars.columns.get_loc("low")] = 99.0
    result = run_backtest(bars, ScalpConfig(), minimum_trades=1)
    assert result.trades[0].exit_reason == "STOP"


def test_time_exit_occurs_at_a_later_bar_open(monkeypatch):
    bars = _bars()

    def fake_signal(features, position, _config):
        return _signal(features.index[position].to_pydatetime()) if position == 20 else None

    monkeypatch.setattr("alphaflow.scalping.backtest.signal_at", fake_signal)
    result = run_backtest(bars, ScalpConfig(), minimum_trades=1)
    trade = result.trades[0]
    assert trade.exit_reason == "TIME"
    assert trade.exit_time_utc - trade.entry_time_utc >= pd.Timedelta(minutes=20)
