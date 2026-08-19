"""Public records shared by the unattended service and broker adapters."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class OrderLifecycle(str, Enum):
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class PositionLifecycle(str, Enum):
    OPEN = "OPEN"
    EXIT_PENDING = "EXIT_PENDING"
    CLOSED = "CLOSED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


ACTIVE_ORDER_STATES = {
    OrderLifecycle.CREATED.value,
    OrderLifecycle.SUBMITTED.value,
    OrderLifecycle.PARTIALLY_FILLED.value,
}


@dataclass(frozen=True)
class TradeIntent:
    intent_id: str
    order_ref: str
    purpose: str
    action: str
    symbol: str
    quantity: int
    limit_price: float
    session_date: str
    reason: str
    expiry: str = ""
    strike: float = 0.0
    right: str = "C"
    con_id: int = 0


@dataclass
class OrderRecord:
    intent_id: str
    order_ref: str
    purpose: str
    action: str
    symbol: str
    quantity: int
    limit_price: float
    status: str = OrderLifecycle.CREATED.value
    expiry: str = ""
    strike: float = 0.0
    right: str = "C"
    con_id: int = 0
    broker_order_id: int = 0
    perm_id: int = 0
    filled_quantity: int = 0
    average_fill_price: float = 0.0
    attempts: int = 0
    last_error: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True)
class FillRecord:
    execution_id: str
    order_ref: str
    perm_id: int
    symbol: str
    action: str
    quantity: int
    price: float
    commission: float = 0.0
    occurred_at: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True)
class BrokerPosition:
    account_id: str
    symbol: str
    security_type: str
    quantity: float
    average_cost: float
    con_id: int = 0
    expiry: str = ""
    strike: float = 0.0
    right: str = ""
    multiplier: int = 1


@dataclass(frozen=True)
class BrokerOrder:
    order_ref: str
    broker_order_id: int
    perm_id: int
    symbol: str
    security_type: str
    action: str
    quantity: int
    filled_quantity: int
    limit_price: float
    status: str
    con_id: int = 0
    expiry: str = ""
    strike: float = 0.0
    right: str = ""


@dataclass(frozen=True)
class AccountSnapshot:
    account_id: str
    net_liquidation: float
    available_funds: float


@dataclass(frozen=True)
class DailyBar:
    day: str
    close: float
    high: float = 0.0
    low: float = 0.0


@dataclass(frozen=True)
class OptionMarketQuote:
    symbol: str
    expiry: str
    strike: float
    right: str
    delta: float
    bid: float
    ask: float
    timestamp: str
    con_id: int
    multiplier: int = 100
    delayed: bool = False

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0


@dataclass(frozen=True)
class ReconciliationResult:
    ok: bool
    account_id: str
    stock_shares: int
    short_calls: int
    open_orders: int
    issues: tuple[str, ...] = ()
    imported_order_refs: tuple[str, ...] = ()
    checked_at: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True)
class HealthSnapshot:
    connected: bool
    halted: bool
    halt_reason: str
    account_id: str
    stock_shares: int
    short_calls: int
    active_orders: int
    shadow_sessions: int
    last_heartbeat: str
    last_cycle_status: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
