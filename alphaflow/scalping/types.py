"""Public records shared by the SPY scalping runtime and broker adapters."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


class ScalpDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class StockOrderLifecycle(str, Enum):
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class StockOrderRole(str, Enum):
    ENTRY = "ENTRY"
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"
    FLATTEN = "FLATTEN"
    EMERGENCY = "EMERGENCY"


class ScalpPositionLifecycle(str, Enum):
    OPEN = "OPEN"
    FLATTENING = "FLATTENING"
    CLOSED = "CLOSED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


ACTIVE_STOCK_ORDER_STATES = {
    StockOrderLifecycle.CREATED.value,
    StockOrderLifecycle.SUBMITTED.value,
    StockOrderLifecycle.PARTIALLY_FILLED.value,
}


@dataclass(frozen=True)
class MinuteBar:
    timestamp_utc: datetime
    timestamp_et: datetime
    session_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True)
class StockQuote:
    symbol: str
    bid: float
    ask: float
    last: float
    timestamp_utc: datetime
    shortable_shares: int | None = None
    delayed: bool = False

    @property
    def spread(self) -> float:
        return self.ask - self.bid


@dataclass(frozen=True)
class ScalpSignal:
    direction: ScalpDirection
    session_date: date
    bar_time_utc: datetime
    bar_time_et: datetime
    close: float
    opening_range_high: float
    opening_range_low: float
    vwap: float
    ema_fast: float
    ema_slow: float
    relative_volume: float
    atr14: float


@dataclass(frozen=True)
class BracketIntent:
    intent_id: str
    parent_order_ref: str
    take_profit_order_ref: str
    stop_order_ref: str
    direction: ScalpDirection
    symbol: str
    quantity: int
    entry_limit: float
    take_profit_price: float
    stop_price: float
    risk_per_share: float
    session_date: date
    signal_time_utc: datetime


@dataclass
class StockOrderRecord:
    intent_id: str
    order_ref: str
    parent_order_ref: str
    role: str
    action: str
    symbol: str
    quantity: int
    order_type: str
    limit_price: float = 0.0
    stop_price: float = 0.0
    status: str = StockOrderLifecycle.CREATED.value
    broker_order_id: int = 0
    perm_id: int = 0
    filled_quantity: int = 0
    average_fill_price: float = 0.0
    last_error: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True)
class StockFillRecord:
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
class BrokerStockPosition:
    account_id: str
    symbol: str
    quantity: int
    average_cost: float
    con_id: int = 0


@dataclass(frozen=True)
class BrokerStockOrder:
    order_ref: str
    parent_order_id: int
    broker_order_id: int
    perm_id: int
    symbol: str
    action: str
    quantity: int
    filled_quantity: int
    order_type: str
    limit_price: float
    stop_price: float
    status: str


@dataclass(frozen=True)
class ScalpAccountSnapshot:
    account_id: str
    net_liquidation: float
    available_funds: float
    buying_power: float
    day_trades_remaining: str = ""
    account_type: str = ""
    trading_restrictions: tuple[str, ...] = ()


@dataclass
class ScalpPosition:
    intent_id: str
    direction: ScalpDirection
    symbol: str
    quantity: int
    entry_price: float
    stop_price: float
    take_profit_price: float
    opened_at_utc: datetime
    session_date: date
    state: str = ScalpPositionLifecycle.OPEN.value
    entry_perm_id: int = 0
    stop_perm_id: int = 0
    take_profit_perm_id: int = 0
    closed_at_utc: datetime | None = None
    exit_price: float = 0.0
    realized_pnl: float = 0.0


@dataclass(frozen=True)
class ScalpReconciliationResult:
    ok: bool
    account_id: str
    broker_quantity: int
    local_quantity: int
    active_orders: int
    protected: bool
    issues: tuple[str, ...] = ()
    checked_at: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True)
class ScalpHealthSnapshot:
    connected: bool
    halted: bool
    halt_reason: str
    shadow_mode: bool
    account_id: str
    broker_quantity: int
    local_quantity: int
    active_orders: int
    protected: bool
    session_date: str
    entries_today: int
    consecutive_losses: int
    daily_locked: bool
    shadow_sessions: int
    paper_sessions: int
    closed_cycles: int
    last_complete_bar: str
    last_heartbeat: str
    last_cycle_status: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScalpBacktestTrade:
    session_date: date
    direction: ScalpDirection
    signal_time_utc: datetime
    entry_time_utc: datetime
    exit_time_utc: datetime
    quantity: int
    entry_price: float
    exit_price: float
    risk_per_share: float
    gross_pnl: float
    commission: float
    slippage: float
    net_pnl: float
    exit_reason: str


@dataclass(frozen=True)
class ScalpBacktestResult:
    start_date: date | None
    end_date: date | None
    initial_equity: float
    final_equity: float
    trades: tuple[ScalpBacktestTrade, ...]
    net_profit: float
    profit_factor: float
    max_drawdown_pct: float
    win_rate: float
    sessions: int
    passed: bool
    failures: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
