"""Shared types for options trading."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StrategyIntent(str, Enum):
    COVERED_CALL = 'covered_call'
    CSP = 'cash_secured_put'
    BULL_PUT_SPREAD = 'bull_put_spread'
    BEAR_CALL_SPREAD = 'bear_call_spread'
    HOLD = 'hold'
    CLOSE = 'close'
    NONE = 'none'


@dataclass(frozen=True)
class OptionQuote:
    symbol: str
    expiry: str
    strike: float
    right: str
    delta: float
    mid: float
    bid: float
    ask: float
    con_id: int = 0


@dataclass(frozen=True)
class OptionLeg:
    symbol: str
    expiry: str
    strike: float
    right: str
    action: str
    ratio: int = 1
    con_id: int = 0


@dataclass
class StrategyOrder:
    intent: StrategyIntent
    symbol: str
    legs: list[OptionLeg]
    quantity: int
    limit_price: float
    max_loss: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class UnderlyingSnapshot:
    symbol: str
    close: float
    ema_fast: float
    ema_slow: float
    ema_trend: float
    rsi: float
    adx: float
    golden_cross: bool
    stock_shares: int = 0
    short_calls: int = 0
    short_puts: int = 0
