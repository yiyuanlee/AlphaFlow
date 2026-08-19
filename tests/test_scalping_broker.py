from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

from alphaflow.scalping.broker import IBKRStockBroker
from alphaflow.scalping.config import ScalpBrokerConfig
from alphaflow.scalping.types import BracketIntent, ScalpDirection


class FakeIB:
    def __init__(self) -> None:
        self.placed = []

    def bracketOrder(self, _action, quantity, entry, target, stop, **_kwargs):
        def order(order_type, action, price=0.0, aux=0.0):
            return SimpleNamespace(
                orderRef="",
                transmit=None,
                parentId=0,
                orderId=len(self.placed) + 1,
                permId=0,
                totalQuantity=quantity,
                orderType=order_type,
                action=action,
                lmtPrice=price,
                auxPrice=aux,
            )

        return [order("LMT", "BUY", entry), order("LMT", "SELL", target), order("STP", "SELL", aux=stop)]

    def placeOrder(self, contract, order):
        self.placed.append(order)
        status = SimpleNamespace(status="Submitted", filled=0, remaining=order.totalQuantity, permId=0)
        return SimpleNamespace(contract=contract, order=order, orderStatus=status)

    def sleep(self, _seconds):
        return None


def test_ibkr_bracket_uses_atomic_transmit_sequence():
    broker = IBKRStockBroker.__new__(IBKRStockBroker)
    broker.config = ScalpBrokerConfig()
    broker.ib = FakeIB()
    broker._stock = SimpleNamespace(symbol="SPY", secType="STK")
    broker._ticker = None
    broker._live_bars = None
    intent = BracketIntent(
        "AFSCALP-X",
        "AFSCALP-X-P",
        "AFSCALP-X-TP",
        "AFSCALP-X-SL",
        ScalpDirection.LONG,
        "SPY",
        10,
        600.0,
        600.9,
        599.4,
        0.6,
        date(2026, 8, 19),
        datetime(2026, 8, 19, 14, 0, tzinfo=timezone.utc),
    )
    orders = broker.submit_bracket(intent)
    assert [order.transmit for order in broker.ib.placed] == [False, False, True]
    assert [order.orderRef for order in broker.ib.placed] == [
        intent.parent_order_ref,
        intent.take_profit_order_ref,
        intent.stop_order_ref,
    ]
    assert len(orders) == 3
