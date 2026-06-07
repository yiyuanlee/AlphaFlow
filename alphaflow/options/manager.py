"""High-level options position management."""

from __future__ import annotations

from typing import TYPE_CHECKING

from alphaflow.options.chain import days_to_expiry
from alphaflow.options.execution import close_single_option, place_single_option, place_spread
from alphaflow.options.journal import log_options_event
from alphaflow.options.options_config import OptionsTradingConfig
from alphaflow.options.signals import should_close_for_profit, should_roll
from alphaflow.options.state import OptionsPosition, StoredLeg, load_positions, new_position_id, save_positions
from alphaflow.options.strategies import (
    build_bear_call_spread_order,
    build_bull_put_spread_order,
    build_covered_call_order,
    build_csp_order,
)
from alphaflow.options.types import StrategyIntent, UnderlyingSnapshot

if TYPE_CHECKING:
    from ib_insync import IB


class OptionsManager:
    def __init__(self, ib: IB, config: OptionsTradingConfig):
        self.ib = ib
        self.config = config
        self.positions = load_positions()

    def open_positions_max_loss(self) -> list[float]:
        losses = []
        for pos in self.positions.values():
            if pos.status != 'open':
                continue
            if pos.max_loss == float('inf'):
                losses.append(self.config.risk.max_loss_per_trade)
            else:
                losses.append(pos.max_loss)
        return losses

    def persist(self) -> None:
        save_positions(self.positions)

    def execute_intent(
        self,
        intent: StrategyIntent,
        underlying: UnderlyingSnapshot,
        available_cash: float,
        net_liquidation: float,
    ) -> bool:
        order = None
        losses = self.open_positions_max_loss()
        if intent == StrategyIntent.CSP:
            order = build_csp_order(self.ib, underlying.symbol, available_cash, self.config, losses, net_liquidation)
        elif intent == StrategyIntent.COVERED_CALL:
            order = build_covered_call_order(self.ib, underlying, self.config, losses, net_liquidation)
        elif intent == StrategyIntent.BULL_PUT_SPREAD:
            order = build_bull_put_spread_order(self.ib, underlying.symbol, self.config, losses, net_liquidation)
        elif intent == StrategyIntent.BEAR_CALL_SPREAD:
            order = build_bear_call_spread_order(self.ib, underlying.symbol, self.config, losses, net_liquidation)
        else:
            return False
        if order is None:
            return False
        return self._submit_order(order)

    def _submit_order(self, order) -> bool:
        if len(order.legs) == 1:
            from alphaflow.options.types import OptionQuote

            leg = order.legs[0]
            quote = OptionQuote(
                symbol=leg.symbol,
                expiry=leg.expiry,
                strike=leg.strike,
                right=leg.right,
                delta=float(order.metadata.get('delta', 0)),
                mid=float(order.metadata.get('premium', order.limit_price)),
                bid=0,
                ask=0,
                con_id=leg.con_id,
            )
            trade = place_single_option(self.ib, quote, leg.action, order.quantity, self.config.execution)
        else:
            short_mid = float(order.metadata.get('short_mid', order.limit_price))
            long_mid = float(order.metadata.get('long_mid', 0))
            trade = place_spread(self.ib, order.legs, order.quantity, short_mid, long_mid, self.config.execution)
        if trade is None:
            return False
        pid = new_position_id(order.symbol, order.intent.value)
        legs = [StoredLeg(**leg.__dict__) for leg in order.legs]
        self.positions[pid] = OptionsPosition(
            position_id=pid,
            strategy=order.intent.value,
            symbol=order.symbol,
            quantity=order.quantity,
            entry_premium=float(order.metadata.get('premium', order.limit_price)),
            limit_price=order.limit_price,
            max_loss=order.max_loss,
            expiry=order.legs[0].expiry,
            legs=legs,
            status='open',
            metadata=order.metadata,
        )
        self.persist()
        log_options_event(
            'open',
            position_id=pid,
            intent=order.intent.value,
            symbol=order.symbol,
            quantity=order.quantity,
            limit_price=order.limit_price,
            max_loss=order.max_loss,
        )
        return True

    def manage_open_positions(self) -> None:
        to_close: list[str] = []
        for pid, pos in self.positions.items():
            if pos.status != 'open':
                continue
            dte = days_to_expiry(pos.expiry)
            if should_roll(dte, self.config.risk.roll_dte):
                log_options_event('roll_signal', position_id=pid, dte=dte)
            current = pos.entry_premium * 0.5
            if should_close_for_profit(pos.entry_premium, current, self.config.risk.profit_take_pct):
                self._close_position(pos)
                to_close.append(pid)
        for pid in to_close:
            self.positions[pid].status = 'closed'
        if to_close:
            self.persist()

    def _close_position(self, pos: OptionsPosition) -> None:
        if len(pos.legs) == 1:
            leg = pos.legs[0]
            close_single_option(self.ib, leg, pos.quantity, pos.entry_premium * 0.5, self.config.execution)
        log_options_event(
            'close',
            position_id=pos.position_id,
            symbol=pos.symbol,
            strategy=pos.strategy,
            pnl=pos.entry_premium * pos.quantity * 100 * self.config.risk.profit_take_pct,
        )
