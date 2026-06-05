"""Pure signal logic shared by backtest and live trading."""

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from alphaflow.config import RiskParams, StrategyParams
from alphaflow.constants import is_index


@dataclass(frozen=True)
class PositionState:
    stop_price: Optional[float] = None
    highest_price: Optional[float] = None


def trailing_stop_level(
    highest_price: float,
    atr: float,
    params: StrategyParams,
) -> float:
    """ATR trailing stop with fixed-percentage cap (same as backtest)."""
    atr_trail = highest_price - atr * params.trailing_atr_mult
    pct_trail = highest_price * (1.0 - params.trailing_stop)
    return min(atr_trail, pct_trail)


def initial_stop_price(entry_price: float, atr: float, params: StrategyParams) -> float:
    return entry_price - atr * params.atr_multiplier


def check_entry(
    close: float,
    ema_trend: float,
    rsi: float,
    adx: float,
    atr: float,
    atr_sma: float,
    golden_cross: bool,
    params: StrategyParams,
) -> bool:
    if not golden_cross:
        return False
    if close <= ema_trend:
        return False
    if rsi >= params.rsi_upper:
        return False
    if adx <= params.adx_threshold:
        return False
    if pd.isna(atr_sma) or atr_sma <= 0:
        return False
    if atr <= atr_sma * params.vol_filter_ratio:
        return False
    return True


def check_exit(
    close: float,
    ema_trend: float,
    death_cross: bool,
    position: PositionState,
    atr: float,
    params: StrategyParams,
) -> Optional[str]:
    """Return exit reason string, or None if position should be held."""
    if close < ema_trend:
        return 'trend_break'
    if position.stop_price is not None and close < position.stop_price:
        return 'atr_stop'
    if position.highest_price is not None:
        if close < trailing_stop_level(position.highest_price, atr, params):
            return 'trailing_stop'
    if death_cross:
        return 'death_cross'
    return None


def calc_position_size(
    symbol: str,
    close: float,
    atr: float,
    total_value: float,
    available_cash: float,
    index_exposure: float,
    stock_exposure: float,
    strategy: StrategyParams,
    risk: RiskParams,
    portfolio_mode: bool = True,
) -> int:
    """Calculate share count for a new entry."""
    risk_mult = risk.index_multiplier if is_index(symbol) else 1.0
    risk_amount = total_value * risk.risk_per_trade * risk_mult
    atr_stop = max(atr * strategy.atr_multiplier, 0.01)
    size = int(risk_amount / atr_stop)
    if size <= 0:
        return 0

    order_val = size * close
    available_cash_limit = available_cash * 0.95

    if portfolio_mode:
        if is_index(symbol):
            max_allowed_val = total_value * risk.alloc_index
            available_val = max_allowed_val - index_exposure
        else:
            max_allowed_val = total_value * risk.alloc_stock
            available_val = max_allowed_val - stock_exposure
        actual_available = max(min(available_val, available_cash_limit), 0)
    else:
        actual_available = available_cash_limit

    if order_val > actual_available:
        size = int(actual_available / close)

    return max(size, 0)
