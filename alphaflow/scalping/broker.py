"""Stock broker protocol and isolated IBKR paper adapter for the SPY scalper."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol

from alphaflow.scalping.clock import XnysClock
from alphaflow.scalping.config import ScalpBrokerConfig
from alphaflow.scalping.data import minute_bar_from_utc
from alphaflow.scalping.types import (
    BracketIntent,
    BrokerStockOrder,
    BrokerStockPosition,
    MinuteBar,
    ScalpAccountSnapshot,
    ScalpDirection,
    StockFillRecord,
    StockOrderLifecycle,
    StockQuote,
)


class StockBroker(Protocol):
    def connect(self) -> None: ...

    def disconnect(self) -> None: ...

    def is_connected(self) -> bool: ...

    def wait(self, seconds: float) -> None: ...

    def account_snapshot(self) -> ScalpAccountSnapshot: ...

    def positions(self) -> list[BrokerStockPosition]: ...

    def orders(self, *, include_completed: bool = False) -> list[BrokerStockOrder]: ...

    def executions(self) -> list[StockFillRecord]: ...

    def historical_minutes(self, symbol: str, start: date, end: date) -> list[MinuteBar]: ...

    def start_minute_subscription(self, symbol: str) -> None: ...

    def complete_minute_bars(self, now_utc: datetime | None = None) -> list[MinuteBar]: ...

    def quote(self, symbol: str) -> StockQuote: ...

    def submit_bracket(self, intent: BracketIntent) -> list[BrokerStockOrder]: ...

    def cancel(self, order_ref: str) -> None: ...

    def resize(self, order_ref: str, quantity: int) -> BrokerStockOrder: ...

    def cancel_symbol_orders(self, symbol: str, *, exclude_refs: set[str] | None = None) -> None: ...

    def submit_exit_limit(
        self, symbol: str, action: str, quantity: int, price: float, order_ref: str
    ) -> BrokerStockOrder: ...

    def submit_emergency_market(self, symbol: str, action: str, quantity: int, order_ref: str) -> BrokerStockOrder: ...


def normalize_stock_order_status(status: str, filled: float, remaining: float) -> str:
    lowered = status.lower()
    if lowered == "filled" or (filled > 0 and remaining <= 0):
        return StockOrderLifecycle.FILLED.value
    if filled > 0 and remaining > 0:
        return StockOrderLifecycle.PARTIALLY_FILLED.value
    if lowered in {"cancelled", "apicancelled"}:
        return StockOrderLifecycle.CANCELLED.value
    if lowered in {"inactive", "rejected"}:
        return StockOrderLifecycle.REJECTED.value
    return StockOrderLifecycle.SUBMITTED.value


class IBKRStockBroker:
    """Synchronous adapter around exactly one dedicated IB Gateway API session."""

    def __init__(self, config: ScalpBrokerConfig) -> None:
        from ib_async import IB

        self.config = config
        self.ib = IB()
        self._stock: Any | None = None
        self._ticker: Any | None = None
        self._live_bars: Any | None = None

    def connect(self) -> None:
        if self.ib.isConnected():
            return
        self.ib.connect(
            self.config.host,
            self.config.port,
            clientId=self.config.client_id,
            timeout=self.config.connect_timeout,
            readonly=False,
        )
        self.ib.reqOpenOrders()
        self.ib.reqExecutions()
        self.ib.sleep(0.25)

    def disconnect(self) -> None:
        if self.ib.isConnected():
            if self._ticker is not None:
                self.ib.cancelMktData(self._ticker.contract)
            if self._live_bars is not None:
                self.ib.cancelHistoricalData(self._live_bars)
            self.ib.disconnect()

    def is_connected(self) -> bool:
        return bool(self.ib.isConnected())

    def wait(self, seconds: float) -> None:
        self.ib.sleep(seconds)

    def _qualified_stock(self, symbol: str):
        from ib_async import Stock

        if self._stock is not None and str(self._stock.symbol) == symbol:
            return self._stock
        stock = Stock(symbol, "SMART", "USD")
        qualified = self.ib.qualifyContracts(stock)
        if not qualified:
            raise RuntimeError(f"unable to qualify {symbol} stock contract")
        self._stock = qualified[0]
        return self._stock

    def account_snapshot(self) -> ScalpAccountSnapshot:
        accounts = list(self.ib.managedAccounts())
        if len(accounts) != 1:
            raise RuntimeError(f"scalping runtime requires exactly one managed account; received {len(accounts)}")
        account_id = str(accounts[0])
        raw: dict[str, str] = {}
        for item in self.ib.accountSummary(account_id):
            if str(item.currency) not in {"USD", "BASE", ""}:
                continue
            raw[str(item.tag)] = str(item.value)

        def number(tag: str, fallback: str = "") -> float:
            value = raw.get(tag, raw.get(fallback, "0"))
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0.0

        restrictions: list[str] = []
        if raw.get("AccountReady", "true").lower() not in {"true", "1", "yes"}:
            restrictions.append("AccountReady=false")
        if raw.get("TradingType-S", "").upper() in {"CASH", "NONE"}:
            restrictions.append(f"TradingType-S={raw['TradingType-S']}")
        remaining = raw.get("DayTradesRemaining", "")
        try:
            if remaining and float(remaining) == 0:
                restrictions.append("DayTradesRemaining=0")
        except ValueError:
            restrictions.append(f"invalid DayTradesRemaining={remaining}")
        return ScalpAccountSnapshot(
            account_id=account_id,
            net_liquidation=number("NetLiquidation"),
            available_funds=number("AvailableFunds", "TotalCashValue"),
            buying_power=number("BuyingPower", "AvailableFunds"),
            day_trades_remaining=remaining,
            account_type=raw.get("AccountType", ""),
            trading_restrictions=tuple(restrictions),
        )

    def positions(self) -> list[BrokerStockPosition]:
        rows: list[BrokerStockPosition] = []
        for position in self.ib.positions():
            contract = position.contract
            if str(contract.secType) != "STK":
                continue
            rows.append(
                BrokerStockPosition(
                    account_id=str(position.account),
                    symbol=str(contract.symbol),
                    quantity=int(float(position.position)),
                    average_cost=float(position.avgCost),
                    con_id=int(contract.conId or 0),
                )
            )
        return rows

    @staticmethod
    def _trade_to_order(trade: Any) -> BrokerStockOrder:
        order = trade.order
        status = trade.orderStatus
        return BrokerStockOrder(
            order_ref=str(order.orderRef or ""),
            parent_order_id=int(order.parentId or 0),
            broker_order_id=int(order.orderId or 0),
            perm_id=int(order.permId or status.permId or 0),
            symbol=str(trade.contract.symbol),
            action=str(order.action),
            quantity=int(float(order.totalQuantity)),
            filled_quantity=int(float(status.filled or 0)),
            order_type=str(order.orderType),
            limit_price=float(order.lmtPrice or 0.0),
            stop_price=float(order.auxPrice or 0.0),
            status=normalize_stock_order_status(
                str(status.status), float(status.filled or 0), float(status.remaining or 0)
            ),
        )

    def orders(self, *, include_completed: bool = False) -> list[BrokerStockOrder]:
        requested = list(self.ib.reqAllOpenOrders() or [])
        self.ib.sleep(0.15)
        trades = [*requested, *self.ib.openTrades()]
        if include_completed:
            trades.extend(self.ib.reqCompletedOrders(apiOnly=False) or [])
        unique = {
            (int(trade.order.permId or 0), int(trade.order.orderId or 0), str(trade.order.orderRef or "")): trade
            for trade in trades
            if str(trade.contract.secType) == "STK"
        }
        return [self._trade_to_order(trade) for trade in unique.values()]

    def executions(self) -> list[StockFillRecord]:
        self.ib.reqExecutions()
        self.ib.sleep(0.1)
        rows: list[StockFillRecord] = []
        for fill in self.ib.fills():
            if str(fill.contract.secType) != "STK":
                continue
            execution = fill.execution
            commission_report = getattr(fill, "commissionReport", None)
            occurred = execution.time
            if isinstance(occurred, datetime) and occurred.tzinfo is not None:
                occurred_at = occurred.astimezone(timezone.utc).isoformat()
            else:
                occurred_at = str(occurred)
            rows.append(
                StockFillRecord(
                    execution_id=str(execution.execId),
                    order_ref=str(getattr(execution, "orderRef", "") or ""),
                    perm_id=int(execution.permId or 0),
                    symbol=str(fill.contract.symbol),
                    action=str(execution.side),
                    quantity=int(float(execution.shares)),
                    price=float(execution.price),
                    commission=float(getattr(commission_report, "commission", 0.0) or 0.0),
                    occurred_at=occurred_at,
                )
            )
        return rows

    def historical_minutes(self, symbol: str, start: date, end: date) -> list[MinuteBar]:
        if end < start:
            raise ValueError("historical end date precedes start date")
        stock = self._qualified_stock(symbol)
        clock = XnysClock()
        result: dict[datetime, MinuteBar] = {}
        cursor = end
        while cursor >= start:
            schedule = clock.schedule(cursor)
            if schedule is None:
                cursor -= timedelta(days=1)
                continue
            end_timestamp = schedule.close_utc + timedelta(minutes=1)
            bars = self.ib.reqHistoricalData(
                stock,
                endDateTime=end_timestamp,
                durationStr="1 D",
                barSizeSetting="1 min",
                whatToShow="TRADES",
                useRTH=True,
                formatDate=2,
                keepUpToDate=False,
                timeout=60,
            )
            for bar in bars:
                converted = self._bar(bar)
                if converted.session_date == cursor:
                    result[converted.timestamp_utc] = converted
            cursor -= timedelta(days=1)
            # One RTH session per request satisfies the 1-minute step-size rule;
            # one request/second also stays below burst pacing limits.
            self.ib.sleep(1.0)
        return sorted(result.values(), key=lambda bar: bar.timestamp_utc)

    @staticmethod
    def _bar(bar: Any) -> MinuteBar:
        timestamp = bar.date
        if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
            raise RuntimeError("IBKR formatDate=2 returned a minute bar without an aware timestamp")
        return minute_bar_from_utc(
            timestamp,
            float(bar.open),
            float(bar.high),
            float(bar.low),
            float(bar.close),
            int(float(bar.volume)),
        )

    def start_minute_subscription(self, symbol: str) -> None:
        if self._live_bars is not None:
            return
        stock = self._qualified_stock(symbol)
        self._live_bars = self.ib.reqHistoricalData(
            stock,
            endDateTime="",
            durationStr="2 D",
            barSizeSetting="1 min",
            whatToShow="TRADES",
            useRTH=True,
            formatDate=2,
            keepUpToDate=True,
            timeout=60,
        )

    def complete_minute_bars(self, now_utc: datetime | None = None) -> list[MinuteBar]:
        if self._live_bars is None:
            raise RuntimeError("minute subscription has not been started")
        now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
        rows: dict[datetime, MinuteBar] = {}
        for raw in self._live_bars:
            bar = self._bar(raw)
            if bar.timestamp_utc + timedelta(minutes=1) <= now:
                rows[bar.timestamp_utc] = bar
        return sorted(rows.values(), key=lambda bar: bar.timestamp_utc)

    def quote(self, symbol: str) -> StockQuote:
        if self._ticker is None:
            stock = self._qualified_stock(symbol)
            self.ib.reqMarketDataType(1)
            self._ticker = self.ib.reqMktData(stock, genericTickList="236", snapshot=False)
            self.ib.sleep(0.5)
        ticker = self._ticker
        stamp = ticker.time
        if not isinstance(stamp, datetime):
            stamp = datetime.now(timezone.utc)
        elif stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        shortable = ticker.shortableShares
        return StockQuote(
            symbol=symbol,
            bid=_finite_price(ticker.bid),
            ask=_finite_price(ticker.ask),
            last=_finite_price(ticker.last or ticker.close),
            timestamp_utc=stamp.astimezone(timezone.utc),
            shortable_shares=int(float(shortable)) if shortable is not None and math.isfinite(shortable) else None,
            delayed=int(getattr(ticker, "marketDataType", 1) or 1) in {3, 4},
        )

    def submit_bracket(self, intent: BracketIntent) -> list[BrokerStockOrder]:
        stock = self._qualified_stock(intent.symbol)
        action = "BUY" if intent.direction is ScalpDirection.LONG else "SELL"
        bracket = self.ib.bracketOrder(
            action,
            intent.quantity,
            intent.entry_limit,
            intent.take_profit_price,
            intent.stop_price,
            tif="DAY",
            outsideRth=False,
        )
        parent, take_profit, stop_loss = bracket
        parent.orderRef = intent.parent_order_ref
        take_profit.orderRef = intent.take_profit_order_ref
        stop_loss.orderRef = intent.stop_order_ref
        parent.transmit = False
        take_profit.transmit = False
        stop_loss.transmit = True
        trades = [self.ib.placeOrder(stock, order) for order in (parent, take_profit, stop_loss)]
        self.ib.sleep(0.3)
        return [self._trade_to_order(trade) for trade in trades]

    def _trade_by_ref(self, order_ref: str):
        self.ib.reqOpenOrders()
        self.ib.sleep(0.1)
        for trade in self.ib.openTrades():
            if str(trade.order.orderRef or "") == order_ref:
                return trade
        raise KeyError(f"active broker order not found: {order_ref}")

    def cancel(self, order_ref: str) -> None:
        trade = self._trade_by_ref(order_ref)
        self.ib.cancelOrder(trade.order)
        self.ib.sleep(0.1)

    def resize(self, order_ref: str, quantity: int) -> BrokerStockOrder:
        if quantity <= 0:
            raise ValueError("replacement quantity must be positive")
        trade = self._trade_by_ref(order_ref)
        trade.order.totalQuantity = quantity
        updated = self.ib.placeOrder(trade.contract, trade.order)
        self.ib.sleep(0.1)
        return self._trade_to_order(updated)

    def cancel_symbol_orders(self, symbol: str, *, exclude_refs: set[str] | None = None) -> None:
        excluded = exclude_refs or set()
        for trade in list(self.ib.openTrades()):
            if str(trade.contract.symbol) == symbol and str(trade.order.orderRef or "") not in excluded:
                self.ib.cancelOrder(trade.order)
        self.ib.sleep(0.15)

    def submit_exit_limit(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: float,
        order_ref: str,
    ) -> BrokerStockOrder:
        from ib_async import LimitOrder

        stock = self._qualified_stock(symbol)
        order = LimitOrder(action, quantity, price, tif="DAY", outsideRth=False)
        order.orderRef = order_ref
        order.transmit = True
        trade = self.ib.placeOrder(stock, order)
        self.ib.sleep(0.15)
        return self._trade_to_order(trade)

    def submit_emergency_market(
        self,
        symbol: str,
        action: str,
        quantity: int,
        order_ref: str,
    ) -> BrokerStockOrder:
        from ib_async import MarketOrder

        stock = self._qualified_stock(symbol)
        order = MarketOrder(action, quantity, tif="DAY", outsideRth=False)
        order.orderRef = order_ref
        order.transmit = True
        trade = self.ib.placeOrder(stock, order)
        self.ib.sleep(0.15)
        return self._trade_to_order(trade)


def _finite_price(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0
