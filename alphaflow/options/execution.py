"""IBKR order placement for single-leg and spread options."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alphaflow.options.chain import limit_price_from_mid, spread_limit_credit
from alphaflow.options.options_config import OptionsExecutionParams
from alphaflow.options.types import OptionLeg, OptionQuote, StrategyOrder

if TYPE_CHECKING:
    from ib_async import IB, Trade


def build_limit_order(action: str, quantity: int, limit_price: float):
    from ib_async import LimitOrder

    return LimitOrder(action.upper(), quantity, limit_price)


def option_contract_from_leg(leg: OptionLeg):
    from ib_async import Option

    return Option(
        leg.symbol,
        leg.expiry,
        leg.strike,
        leg.right,
        'SMART',
        tradingClass=leg.symbol,
        conId=leg.con_id or 0,
    )


def build_bag_contract(legs: list[OptionLeg], symbol: str):
    from ib_async import Bag, ComboLeg

    combo = Bag(symbol=symbol, secType='BAG', currency='USD', exchange='SMART')
    combo.comboLegs = []
    for leg in legs:
        contract = option_contract_from_leg(leg)
        combo.comboLegs.append(ComboLeg(
            conId=leg.con_id,
            ratio=leg.ratio,
            action=leg.action.upper(),
            exchange='SMART',
        ))
    return combo


def place_single_option(
    ib: IB,
    quote: OptionQuote,
    action: str,
    quantity: int,
    execution: OptionsExecutionParams,
) -> Trade | None:
    from ib_async import Option

    contract = Option(
        quote.symbol,
        quote.expiry,
        quote.strike,
        quote.right,
        'SMART',
        tradingClass=quote.symbol,
        conId=quote.con_id,
    )
    qualified = ib.qualifyContracts(contract)
    if not qualified:
        return None
    contract = qualified[0]
    limit_px = limit_price_from_mid(quote.mid, execution.limit_offset_pct, action)
    order = build_limit_order(action, quantity, limit_px)
    return ib.placeOrder(contract, order)


def place_spread(
    ib: IB,
    legs: list[OptionLeg],
    quantity: int,
    short_mid: float,
    long_mid: float,
    execution: OptionsExecutionParams,
) -> Trade | None:
    qualified_legs: list[OptionLeg] = []
    for leg in legs:
        contract = option_contract_from_leg(leg)
        q = ib.qualifyContracts(contract)
        if not q:
            return None
        qualified_legs.append(OptionLeg(
            leg.symbol, leg.expiry, leg.strike, leg.right, leg.action, leg.ratio, q[0].conId,
        ))
    bag = build_bag_contract(qualified_legs, legs[0].symbol)
    ib.qualifyContracts(bag)
    limit_px = spread_limit_credit(short_mid, long_mid, execution.limit_offset_pct)
    order = build_limit_order('SELL', quantity, limit_px)
    order.tif = 'DAY'
    return ib.placeOrder(bag, order)


def close_single_option(ib: IB, leg: OptionLeg, quantity: int, mid: float, execution: OptionsExecutionParams) -> Trade | None:
    close_action = 'BUY' if leg.action.upper() == 'SELL' else 'SELL'
    quote = OptionQuote(
        symbol=leg.symbol,
        expiry=leg.expiry,
        strike=leg.strike,
        right=leg.right,
        delta=0.0,
        mid=mid,
        bid=mid,
        ask=mid,
        con_id=leg.con_id,
    )
    return place_single_option(ib, quote, close_action, quantity, execution)


def order_from_strategy(strategy: StrategyOrder) -> dict[str, Any]:
    return {
        'intent': strategy.intent.value,
        'symbol': strategy.symbol,
        'quantity': strategy.quantity,
        'limit_price': strategy.limit_price,
        'max_loss': strategy.max_loss,
        'legs': [leg.__dict__ for leg in strategy.legs],
        'metadata': strategy.metadata,
    }
