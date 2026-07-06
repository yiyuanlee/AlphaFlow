"""Signal parity between shared equity functions and Backtrader logic."""

from __future__ import annotations

from alphaflow.core.config import StrategyParams, load_config, params_from_config
from alphaflow.equity.signal_parity import _synthetic_uptrend, simulate_signal_decisions
from alphaflow.equity.signals import check_entry, check_exit


def test_check_entry_respects_golden_cross():
    params = StrategyParams()
    base = dict(
        close=110.0,
        ema_trend=100.0,
        rsi=50.0,
        adx=25.0,
        atr=2.0,
        atr_sma=1.5,
        params=params,
    )
    assert check_entry(**base, golden_cross=True) is True
    assert check_entry(**base, golden_cross=False) is False


def test_check_exit_death_cross():
    params = StrategyParams()
    from alphaflow.equity.signals import PositionState

    reason = check_exit(
        close=105.0,
        ema_trend=100.0,
        death_cross=True,
        position=PositionState(stop_price=95.0, highest_price=112.0),
        atr=2.0,
        params=params,
    )
    assert reason == "death_cross"


def test_simulate_signal_decisions_runs_on_synthetic_data():
    config = load_config()
    strategy, _ = params_from_config(config)
    df = _synthetic_uptrend()
    decisions = simulate_signal_decisions(df, strategy)
    assert len(decisions) > 0
    assert any(d["entry"] or d["exit"] for d in decisions)


def test_merged_config_has_equity_and_options_sections():
    config = load_config()
    assert "strategy" in config
    assert "options_trading" in config
    assert config["backtest"]["initial_cash"] == 50000.0


def test_load_config_profile_options():
    config = load_config(profile="options")
    assert "options_trading" in config
    assert "strategy" not in config
