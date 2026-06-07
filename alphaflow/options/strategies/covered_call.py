"""Covered call strategy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from alphaflow.options.chain import limit_price_from_mid, pick_otm_option
from alphaflow.options.options_config import OptionsTradingConfig
from alphaflow.options.sizing import allow_new_trade, size_covered_call
from alphaflow.options.types import OptionLeg, StrategyIntent, StrategyOrder, UnderlyingSnapshot

if TYPE_CHECKING:
    from ib_insync import IB


def build_covered_call_order(
    ib: IB,
    underlying: UnderlyingSnapshot,
    config: OptionsTradingConfig,
    positions_max_loss: list[float],
    net_liquidation: float,
) -> StrategyOrder | None:
    qty = size_covered_call(
        underlying.stock_shares,
        underlying.short_calls,
        config.risk.max_contracts_per_symbol,
    )
    if qty <= 0:
        return None
    quote = pick_otm_option(
        ib,
        underlying.symbol,
        'C',
        config.chain,
        config.chain.delta_target_cc,
    )
    if quote is None:
        return None
    max_loss = float('inf')
    trade_max_loss = config.risk.max_loss_per_trade
    if not allow_new_trade(config.risk, positions_max_loss, trade_max_loss, net_liquidation):
        return None
    limit_px = limit_price_from_mid(quote.mid, config.execution.limit_offset_pct, 'SELL')
    leg = OptionLeg(underlying.symbol, quote.expiry, quote.strike, 'C', 'SELL', 1, quote.con_id)
    return StrategyOrder(
        intent=StrategyIntent.COVERED_CALL,
        symbol=underlying.symbol,
        legs=[leg],
        quantity=qty,
        limit_price=limit_px,
        max_loss=max_loss,
        metadata={'premium': quote.mid, 'delta': quote.delta, 'shares': underlying.stock_shares},
    )
