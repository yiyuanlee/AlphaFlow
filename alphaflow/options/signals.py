"""Strategy intent routing based on regime and underlying state."""

from __future__ import annotations

from alphaflow.options.options_config import OptionsTradingConfig
from alphaflow.options.regime import MarketRegime, RegimeSnapshot
from alphaflow.options.types import StrategyIntent, UnderlyingSnapshot


def route_strategy(
    regime: RegimeSnapshot,
    underlying: UnderlyingSnapshot,
    config: OptionsTradingConfig,
    has_open_option: bool = False,
) -> StrategyIntent:
    toggles = config.strategies
    reg = regime.regime

    if has_open_option:
        return StrategyIntent.HOLD

    if reg == MarketRegime.WEAK:
        return StrategyIntent.HOLD

    if reg == MarketRegime.SHARP_DROP:
        if toggles.bear_call_spread and underlying.golden_cross is False:
            return StrategyIntent.BEAR_CALL_SPREAD
        return StrategyIntent.HOLD

    if reg == MarketRegime.STRONG_UPTREND:
        if toggles.bull_put_spread and underlying.golden_cross:
            return StrategyIntent.BULL_PUT_SPREAD
        if toggles.covered_call and underlying.stock_shares >= 100:
            return StrategyIntent.COVERED_CALL
        if toggles.cash_secured_put and _csp_allowed(regime, config):
            return StrategyIntent.CSP
        return StrategyIntent.HOLD

    # Mild bull / range
    if toggles.covered_call and underlying.stock_shares >= 100 and underlying.short_calls == 0:
        return StrategyIntent.COVERED_CALL
    if toggles.cash_secured_put and underlying.stock_shares < 100 and _csp_allowed(regime, config):
        return StrategyIntent.CSP
    if toggles.bull_put_spread and underlying.golden_cross:
        return StrategyIntent.BULL_PUT_SPREAD
    return StrategyIntent.HOLD


def should_close_for_profit(entry_premium: float, current_value: float, profit_take_pct: float) -> bool:
    if entry_premium <= 0:
        return False
    target = entry_premium * (1 - profit_take_pct)
    return current_value <= target


def should_roll(dte: int, roll_dte: int) -> bool:
    return dte <= roll_dte


def _csp_allowed(regime: RegimeSnapshot, config: OptionsTradingConfig) -> bool:
    if not config.strategies.cash_secured_put:
        return False
    if config.regime.require_bull_market and not regime.bullish:
        return False
    if regime.rsi > 70:
        return False
    return True
