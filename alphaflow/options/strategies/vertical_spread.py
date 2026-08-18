"""Bull put and bear call vertical spreads."""

from __future__ import annotations

from typing import TYPE_CHECKING

from alphaflow.options.chain import (
    build_vertical_call_spread,
    build_vertical_put_spread,
    fetch_option_quotes,
    fetch_chain_expiries,
    fetch_strikes,
    select_expiry,
    select_strike_by_delta,
    spread_limit_credit,
)
from alphaflow.options.options_config import OptionsTradingConfig
from alphaflow.options.sizing import allow_new_trade, size_vertical_spread, vertical_spread_max_loss
from alphaflow.options.types import StrategyIntent, StrategyOrder

if TYPE_CHECKING:
    from ib_async import IB


def build_bull_put_spread_order(
    ib: IB,
    symbol: str,
    config: OptionsTradingConfig,
    positions_max_loss: list[float],
    net_liquidation: float,
) -> StrategyOrder | None:
    return _build_put_spread(ib, symbol, config, positions_max_loss, net_liquidation, StrategyIntent.BULL_PUT_SPREAD)


def build_bear_call_spread_order(
    ib: IB,
    symbol: str,
    config: OptionsTradingConfig,
    positions_max_loss: list[float],
    net_liquidation: float,
) -> StrategyOrder | None:
    return _build_call_spread(ib, symbol, config, positions_max_loss, net_liquidation, StrategyIntent.BEAR_CALL_SPREAD)


def _build_put_spread(
    ib: IB,
    symbol: str,
    config: OptionsTradingConfig,
    positions_max_loss: list[float],
    net_liquidation: float,
    intent: StrategyIntent,
) -> StrategyOrder | None:
    chain = config.chain
    expiries = fetch_chain_expiries(ib, symbol)
    expiry = select_expiry(expiries, chain)
    if not expiry:
        return None
    strikes = fetch_strikes(ib, symbol, expiry, 'P')
    quotes = fetch_option_quotes(ib, symbol, expiry, 'P', strikes)
    short_q = select_strike_by_delta(quotes, chain.delta_target_spread, 'P')
    if short_q is None:
        return None
    long_strike = short_q.strike - chain.spread_width
    long_candidates = [q for q in quotes if abs(q.strike - long_strike) < 0.01]
    if not long_candidates:
        long_strike = max(s for s in strikes if s < short_q.strike)
        long_candidates = [q for q in quotes if abs(q.strike - long_strike) < 0.01]
    if not long_candidates:
        return None
    long_q = long_candidates[0]
    qty = size_vertical_spread(chain.spread_width, config.risk.max_loss_per_trade, config.risk.max_contracts_per_symbol)
    if qty <= 0:
        return None
    max_loss = vertical_spread_max_loss(chain.spread_width, qty)
    if not allow_new_trade(config.risk, positions_max_loss, max_loss, net_liquidation):
        return None
    legs = build_vertical_put_spread(symbol, expiry, short_q.strike, long_q.strike, short_q.con_id, long_q.con_id)
    limit_px = spread_limit_credit(short_q.mid, long_q.mid, config.execution.limit_offset_pct)
    return StrategyOrder(
        intent=intent,
        symbol=symbol,
        legs=legs,
        quantity=qty,
        limit_price=limit_px,
        max_loss=max_loss,
        metadata={'short_delta': short_q.delta, 'width': chain.spread_width},
    )


def _build_call_spread(
    ib: IB,
    symbol: str,
    config: OptionsTradingConfig,
    positions_max_loss: list[float],
    net_liquidation: float,
    intent: StrategyIntent,
) -> StrategyOrder | None:
    chain = config.chain
    expiries = fetch_chain_expiries(ib, symbol)
    expiry = select_expiry(expiries, chain)
    if not expiry:
        return None
    strikes = fetch_strikes(ib, symbol, expiry, 'C')
    quotes = fetch_option_quotes(ib, symbol, expiry, 'C', strikes)
    short_q = select_strike_by_delta(quotes, chain.delta_target_spread, 'C')
    if short_q is None:
        return None
    long_strike = short_q.strike + chain.spread_width
    long_candidates = [q for q in quotes if abs(q.strike - long_strike) < 0.01]
    if not long_candidates:
        long_strike = min(s for s in strikes if s > short_q.strike)
        long_candidates = [q for q in quotes if abs(q.strike - long_strike) < 0.01]
    if not long_candidates:
        return None
    long_q = long_candidates[0]
    qty = size_vertical_spread(chain.spread_width, config.risk.max_loss_per_trade, config.risk.max_contracts_per_symbol)
    if qty <= 0:
        return None
    max_loss = vertical_spread_max_loss(chain.spread_width, qty)
    if not allow_new_trade(config.risk, positions_max_loss, max_loss, net_liquidation):
        return None
    legs = build_vertical_call_spread(symbol, expiry, short_q.strike, long_q.strike, short_q.con_id, long_q.con_id)
    limit_px = spread_limit_credit(short_q.mid, long_q.mid, config.execution.limit_offset_pct)
    return StrategyOrder(
        intent=intent,
        symbol=symbol,
        legs=legs,
        quantity=qty,
        limit_price=limit_px,
        max_loss=max_loss,
        metadata={'short_delta': short_q.delta, 'width': chain.spread_width},
    )
