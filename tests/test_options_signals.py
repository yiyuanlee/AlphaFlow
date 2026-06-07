"""Tests for options strategy routing."""

from alphaflow.options.options_config import (
    OptionsChainParams,
    OptionsExecutionParams,
    OptionsRegimeParams,
    OptionsRiskParams,
    OptionsStrategyToggles,
    OptionsTradingConfig,
)
from alphaflow.options.regime import MarketRegime, RegimeSnapshot
from alphaflow.options.signals import route_strategy, should_close_for_profit, should_roll
from alphaflow.options.types import StrategyIntent, UnderlyingSnapshot


def _config(**kwargs) -> OptionsTradingConfig:
    return OptionsTradingConfig(
        regime=OptionsRegimeParams(),
        chain=OptionsChainParams(),
        risk=OptionsRiskParams(),
        execution=OptionsExecutionParams(),
        strategies=OptionsStrategyToggles(**kwargs),
    )


def _regime(regime: MarketRegime, bullish: bool = True) -> RegimeSnapshot:
    return RegimeSnapshot(
        benchmark='QQQ',
        close=500.0,
        ema_trend=480.0,
        adx=26.0,
        rsi=55.0,
        bullish=bullish,
        regime=regime,
    )


def _underlying(shares: int = 0, golden: bool = True) -> UnderlyingSnapshot:
    return UnderlyingSnapshot(
        symbol='QQQ',
        close=500.0,
        ema_fast=510.0,
        ema_slow=500.0,
        ema_trend=480.0,
        rsi=55.0,
        adx=26.0,
        golden_cross=golden,
        stock_shares=shares,
    )


def test_strong_uptrend_bull_put():
    intent = route_strategy(_regime(MarketRegime.STRONG_UPTREND), _underlying(), _config())
    assert intent == StrategyIntent.BULL_PUT_SPREAD


def test_mild_bull_covered_call_with_shares():
    intent = route_strategy(
        _regime(MarketRegime.MILD_BULL),
        _underlying(shares=100),
        _config(),
    )
    assert intent == StrategyIntent.COVERED_CALL


def test_mild_bull_csp_without_shares():
    intent = route_strategy(
        _regime(MarketRegime.MILD_BULL),
        _underlying(shares=0),
        _config(),
    )
    assert intent == StrategyIntent.CSP


def test_weak_hold():
    intent = route_strategy(_regime(MarketRegime.WEAK, bullish=False), _underlying(), _config())
    assert intent == StrategyIntent.HOLD


def test_profit_and_roll_helpers():
    assert should_close_for_profit(2.0, 0.9, 0.5) is True
    assert should_roll(5, 7) is True
