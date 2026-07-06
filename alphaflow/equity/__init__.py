"""Equity trend-following strategy package."""

from alphaflow.equity.backtest import AlphaFlowStrategy
from alphaflow.equity.signals import (
    PositionState,
    calc_position_size,
    check_entry,
    check_exit,
    initial_stop_price,
    trailing_stop_level,
)

__all__ = [
    "AlphaFlowStrategy",
    "PositionState",
    "calc_position_size",
    "check_entry",
    "check_exit",
    "initial_stop_price",
    "trailing_stop_level",
]
