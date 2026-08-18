"""Broker protocol and IB Gateway implementation backed by ib_async."""

from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Protocol
from zoneinfo import ZoneInfo

from alphaflow.options.chain import days_to_expiry

from .config import BrokerConfig
from .types import (
    AccountSnapshot,
    BrokerOrder,
    BrokerPosition,
    DailyBar,
    FillRecord,
    OptionMarketQuote,
    OrderLifecycle,
    TradeIntent,
)


class Broker(Protocol):
    def connect(self) -> None: ...

    def disconnect(self) -> None: ...

    def is_connected(self) -> bool: ...

    def wait(self, seconds: float) -> None: ...

    def account_snapshot(self) -> AccountSnapshot: ...

    def positions(self) -> list[BrokerPosition]: ...

    def open_orders(self) -> list[BrokerOrder]: ...

    def executions(self) -> list[FillRecord]: ...

    def daily_bars(self, symbol: str, minimum_bars: int) -> list[DailyBar]: ...

    def covered_call_quotes(self, symbol: str, dte_min: int, dte_max: int) -> tuple[float, list[OptionMarketQuote]]: ...

    def option_quote(self, symbol: str, expiry: str, strike: float, right: str, con_id: int) -> OptionMarketQuote: ...

    def submit_limit(self, intent: TradeIntent, tif: str) -> BrokerOrder: ...

    def modify_limit(self, order_ref: str, limit_price: float) -> BrokerOrder: ...

    def cancel(self, order_ref: str) -> None: ...


def _normalise_status(status: str, filled: float, remaining: float) -> str:
    lowered = status.lower()
    if lowered == "filled" or (filled > 0 and remaining <= 0):
        return OrderLifecycle.FILLED.value
    if filled > 0 and remaining > 0:
        return OrderLifecycle.PARTIALLY_FILLED.value
    if lowered in {"cancelled", "apicancelled"}:
        return OrderLifecycle.CANCELLED.value
    if lowered in {"inactive", "rejected"}:
        return OrderLifecycle.REJECTED.value
    return OrderLifecycle.SUBMITTED.value


class IBKRBroker:
    """Small, synchronous adapter around a single IB Gateway API session."""

    def __init__(self, config: BrokerConfig):
        from ib_async import IB

        self.config = config
        self.ib = IB()

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
        self.ib.sleep(0.25)

    def disconnect(self) -> None:
        if self.ib.isConnected():
            self.ib.disconnect()

    def is_connected(self) -> bool:
        return bool(self.ib.isConnected())

    def wait(self, seconds: float) -> None:
        self.ib.sleep(seconds)

    def account_snapshot(self) -> AccountSnapshot:
        accounts = list(self.ib.managedAccounts())
        if not accounts:
            raise RuntimeError("IB Gateway returned no managed accounts")
        if len(accounts) != 1:
            raise RuntimeError(f"unattended pilot requires exactly one managed account; received {len(accounts)}")
        account_id = accounts[0]
        values: dict[str, float] = {}
        for item in self.ib.accountSummary(account_id):
            if item.currency not in {"USD", "BASE"} or item.value in {"", None}:
                continue
            try:
                values[item.tag] = float(item.value)
            except (TypeError, ValueError):
                continue
        return AccountSnapshot(
            account_id=account_id,
            net_liquidation=float(values.get("NetLiquidation", 0.0)),
            available_funds=float(values.get("AvailableFunds", values.get("TotalCashValue", 0.0))),
        )

    def positions(self) -> list[BrokerPosition]:
        rows: list[BrokerPosition] = []
        for position in self.ib.positions():
            contract = position.contract
            multiplier_text = str(getattr(contract, "multiplier", "") or "1")
            try:
                multiplier = int(float(multiplier_text))
            except ValueError:
                multiplier = 1
            rows.append(
                BrokerPosition(
                    account_id=str(position.account),
                    symbol=str(contract.symbol),
                    security_type=str(contract.secType),
                    quantity=float(position.position),
                    average_cost=float(position.avgCost),
                    con_id=int(contract.conId or 0),
                    expiry=str(getattr(contract, "lastTradeDateOrContractMonth", "") or "")[:8],
                    strike=float(getattr(contract, "strike", 0.0) or 0.0),
                    right=str(getattr(contract, "right", "") or ""),
                    multiplier=multiplier,
                )
            )
        return rows

    @staticmethod
    def _trade_to_order(trade) -> BrokerOrder:
        contract = trade.contract
        order = trade.order
        status = trade.orderStatus
        return BrokerOrder(
            order_ref=str(order.orderRef or ""),
            broker_order_id=int(order.orderId or 0),
            perm_id=int(order.permId or status.permId or 0),
            symbol=str(contract.symbol),
            security_type=str(contract.secType),
            action=str(order.action),
            quantity=int(float(order.totalQuantity)),
            filled_quantity=int(float(status.filled or 0)),
            limit_price=float(order.lmtPrice or 0.0),
            status=_normalise_status(str(status.status), float(status.filled or 0), float(status.remaining or 0)),
            con_id=int(contract.conId or 0),
            expiry=str(getattr(contract, "lastTradeDateOrContractMonth", "") or "")[:8],
            strike=float(getattr(contract, "strike", 0.0) or 0.0),
            right=str(getattr(contract, "right", "") or ""),
        )

    def open_orders(self) -> list[BrokerOrder]:
        requested = list(self.ib.reqAllOpenOrders() or [])
        self.ib.sleep(0.2)
        trades = [*requested, *self.ib.openTrades()]
        unique = {
            (int(trade.order.permId or 0), int(trade.order.orderId or 0), str(trade.order.orderRef or "")): trade
            for trade in trades
        }
        return [self._trade_to_order(trade) for trade in unique.values()]

    def executions(self) -> list[FillRecord]:
        rows: list[FillRecord] = []
        for fill in self.ib.fills():
            execution = fill.execution
            commission = getattr(fill, "commissionReport", None)
            rows.append(
                FillRecord(
                    execution_id=str(execution.execId),
                    order_ref=str(getattr(execution, "orderRef", "") or ""),
                    perm_id=int(execution.permId or 0),
                    symbol=str(fill.contract.symbol),
                    action=str(execution.side),
                    quantity=int(float(execution.shares)),
                    price=float(execution.price),
                    commission=float(getattr(commission, "commission", 0.0) or 0.0),
                    occurred_at=(
                        execution.time.astimezone(timezone.utc).isoformat()
                        if getattr(execution.time, "tzinfo", None)
                        else str(execution.time)
                    ),
                )
            )
        return rows

    def daily_bars(self, symbol: str, minimum_bars: int) -> list[DailyBar]:
        from ib_async import Stock

        contract = Stock(symbol, "SMART", "USD")
        qualified = self.ib.qualifyContracts(contract)
        if not qualified:
            raise RuntimeError(f"unable to qualify stock contract for {symbol}")
        duration_years = max((minimum_bars // 240) + 1, 2)
        bars = self.ib.reqHistoricalData(
            qualified[0],
            endDateTime="",
            durationStr=f"{duration_years} Y",
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
        )
        today = datetime.now(ZoneInfo("America/New_York")).date()
        result: list[DailyBar] = []
        for bar in bars:
            value = bar.date
            day = value.date() if isinstance(value, datetime) else value
            if isinstance(day, str):
                day = date.fromisoformat(day[:10])
            if day >= today:
                continue
            result.append(
                DailyBar(
                    day=day.isoformat(),
                    close=float(bar.close),
                    high=float(bar.high),
                    low=float(bar.low),
                )
            )
        return result

    def _stock_and_spot(self, symbol: str):
        from ib_async import Stock

        stock = Stock(symbol, "SMART", "USD")
        qualified = self.ib.qualifyContracts(stock)
        if not qualified:
            raise RuntimeError(f"unable to qualify stock contract for {symbol}")
        stock = qualified[0]
        ticker = self.ib.reqTickers(stock)[0]
        spot = float(ticker.marketPrice() or ticker.last or ticker.close or 0.0)
        if not math.isfinite(spot) or spot <= 0:
            raise RuntimeError(f"no live stock quote for {symbol}")
        return stock, spot

    @staticmethod
    def _ticker_to_quote(ticker, *, delayed: bool = False) -> OptionMarketQuote:
        contract = ticker.contract
        model = ticker.modelGreeks
        delta = float(model.delta) if model and model.delta is not None else 0.0
        stamp = ticker.time
        if not isinstance(stamp, datetime):
            stamp = datetime.now(timezone.utc)
        elif stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return OptionMarketQuote(
            symbol=str(contract.symbol),
            expiry=str(contract.lastTradeDateOrContractMonth)[:8],
            strike=float(contract.strike),
            right=str(contract.right),
            delta=delta,
            bid=float(ticker.bid or 0.0),
            ask=float(ticker.ask or 0.0),
            timestamp=stamp.astimezone(timezone.utc).isoformat(),
            con_id=int(contract.conId or 0),
            multiplier=int(float(contract.multiplier or 100)),
            delayed=delayed or int(getattr(ticker, "marketDataType", 1) or 1) in {3, 4},
        )

    def covered_call_quotes(self, symbol: str, dte_min: int, dte_max: int) -> tuple[float, list[OptionMarketQuote]]:
        from ib_async import Option

        stock, spot = self._stock_and_spot(symbol)
        chains = self.ib.reqSecDefOptParams(stock.symbol, "", stock.secType, stock.conId)
        eastern_today = datetime.now(ZoneInfo("America/New_York")).date()
        valid_expiries = sorted(
            {
                expiry
                for chain in chains
                for expiry in chain.expirations
                if dte_min <= days_to_expiry(expiry, eastern_today) <= dte_max
            },
            key=lambda expiry: days_to_expiry(expiry, eastern_today),
        )
        if not valid_expiries:
            return spot, []
        expiry = valid_expiries[0]
        strikes = sorted(
            {
                float(strike)
                for chain in chains
                if expiry in chain.expirations
                for strike in chain.strikes
                if spot < float(strike) <= spot * 1.20
            }
        )[:24]
        contracts = [Option(symbol, expiry, strike, "C", "SMART", tradingClass=symbol) for strike in strikes]
        qualified = self.ib.qualifyContracts(*contracts) if contracts else []
        if not qualified:
            return spot, []
        self.ib.reqMarketDataType(1)
        tickers = self.ib.reqTickers(*qualified)
        return spot, [self._ticker_to_quote(ticker) for ticker in tickers]

    def option_quote(self, symbol: str, expiry: str, strike: float, right: str, con_id: int) -> OptionMarketQuote:
        from ib_async import Option

        contract = Option(symbol, expiry, strike, right, "SMART", tradingClass=symbol, conId=con_id)
        qualified = self.ib.qualifyContracts(contract)
        if not qualified:
            raise RuntimeError(f"unable to qualify option {symbol} {expiry} {strike}{right}")
        self.ib.reqMarketDataType(1)
        ticker = self.ib.reqTickers(qualified[0])[0]
        return self._ticker_to_quote(ticker)

    def submit_limit(self, intent: TradeIntent, tif: str) -> BrokerOrder:
        from ib_async import LimitOrder, Option

        contract = Option(
            intent.symbol,
            intent.expiry,
            intent.strike,
            intent.right,
            "SMART",
            tradingClass=intent.symbol,
            conId=intent.con_id,
        )
        qualified = self.ib.qualifyContracts(contract)
        if not qualified:
            raise RuntimeError("option contract qualification failed")
        order = LimitOrder(intent.action.upper(), intent.quantity, intent.limit_price, tif=tif)
        order.orderRef = intent.order_ref
        order.transmit = True
        trade = self.ib.placeOrder(qualified[0], order)
        self.ib.sleep(0.5)
        return self._trade_to_order(trade)

    def _trade_by_ref(self, order_ref: str):
        self.ib.reqOpenOrders()
        self.ib.sleep(0.2)
        for trade in self.ib.openTrades():
            if str(trade.order.orderRef or "") == order_ref:
                return trade
        raise KeyError(f"active broker order not found: {order_ref}")

    def modify_limit(self, order_ref: str, limit_price: float) -> BrokerOrder:
        trade = self._trade_by_ref(order_ref)
        trade.order.lmtPrice = float(limit_price)
        updated = self.ib.placeOrder(trade.contract, trade.order)
        self.ib.sleep(0.4)
        return self._trade_to_order(updated)

    def cancel(self, order_ref: str) -> None:
        trade = self._trade_by_ref(order_ref)
        self.ib.cancelOrder(trade.order)
        self.ib.sleep(0.3)
