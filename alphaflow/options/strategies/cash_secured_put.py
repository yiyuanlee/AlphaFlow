"""Cash-secured put strategy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from alphaflow.options.chain import limit_price_from_mid, pick_otm_option
from alphaflow.options.options_config import OptionsTradingConfig
from alphaflow.options.sizing import allow_new_trade, csp_max_loss, size_cash_secured_put
from alphaflow.options.types import OptionLeg, StrategyIntent, StrategyOrder

if TYPE_CHECKING:
    from ib_insync import IB


def build_csp_order(
    ib: IB,
    symbol: str,
    available_cash: float,
    config: OptionsTradingConfig,
    positions_max_loss: list[float],
    net_liquidation: float,
) -> StrategyOrder | None:
    quote = pick_otm_option(
        ib,
        symbol,
        'P',
        config.chain,
        config.chain.delta_target_csp,
    )
    if quote is None:
        return None
    qty = size_cash_secured_put(
        available_cash,
        quote.strike,
        config.risk.max_contracts_per_symbol,
    )
    if qty <= 0:
        return None
    max_loss = csp_max_loss(quote.strike, qty)
    if not allow_new_trade(config.risk, positions_max_loss, max_loss, net_liquidation):
        return None
    limit_px = limit_price_from_mid(quote.mid, config.execution.limit_offset_pct, 'SELL')
    leg = OptionLeg(symbol, quote.expiry, quote.strike, 'P', 'SELL', 1, quote.con_id)
    return StrategyOrder(
        intent=StrategyIntent.CSP,
        symbol=symbol,
        legs=[leg],
        quantity=qty,
        limit_price=limit_px,
        max_loss=max_loss,
        metadata={'premium': quote.mid, 'delta': quote.delta},
    )


