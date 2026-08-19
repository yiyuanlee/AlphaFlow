from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

from alphaflow.scalping.alerts import NullScalpAlertSink
from alphaflow.scalping.clock import ET
from alphaflow.scalping.config import (
    ScalpBacktestConfig,
    ScalpConfig,
    ScalpPersistenceConfig,
)
from alphaflow.scalping.service import ScalpingService
from alphaflow.scalping.store import ScalpingStore
from alphaflow.scalping.types import (
    BracketIntent,
    BrokerStockOrder,
    BrokerStockPosition,
    ScalpAccountSnapshot,
    ScalpDirection,
    ScalpPosition,
    ScalpSignal,
    StockFillRecord,
    StockOrderLifecycle,
    StockQuote,
)


class FakeStockBroker:
    def __init__(self, account_id: str = "DU123") -> None:
        self.connected = False
        self.account_id = account_id
        self._positions: list[BrokerStockPosition] = []
        self._orders: list[BrokerStockOrder] = []
        self._fills: list[StockFillRecord] = []
        self.mutations: list[str] = []
        self._quote = StockQuote("SPY", 599.99, 600.01, 600.0, datetime.now(timezone.utc), shortable_shares=10_000)

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def is_connected(self) -> bool:
        return self.connected

    def wait(self, _seconds: float) -> None:
        return None

    def account_snapshot(self) -> ScalpAccountSnapshot:
        return ScalpAccountSnapshot(self.account_id, 100_000.0, 80_000.0, 100_000.0, "3", "MARGIN")

    def positions(self) -> list[BrokerStockPosition]:
        return list(self._positions)

    def orders(self, *, include_completed: bool = False) -> list[BrokerStockOrder]:
        if include_completed:
            return list(self._orders)
        return [
            order
            for order in self._orders
            if order.status
            in {
                StockOrderLifecycle.SUBMITTED.value,
                StockOrderLifecycle.PARTIALLY_FILLED.value,
                StockOrderLifecycle.CREATED.value,
            }
        ]

    def executions(self) -> list[StockFillRecord]:
        return list(self._fills)

    def historical_minutes(self, _symbol: str, _start: date, _end: date):
        return []

    def start_minute_subscription(self, _symbol: str) -> None:
        return None

    def complete_minute_bars(self, _now_utc=None):
        return []

    def quote(self, _symbol: str) -> StockQuote:
        return self._quote

    def submit_bracket(self, intent: BracketIntent) -> list[BrokerStockOrder]:
        self.mutations.append(f"bracket:{intent.intent_id}")
        return []

    def cancel(self, order_ref: str) -> None:
        self.mutations.append(f"cancel:{order_ref}")
        self._orders = [order for order in self._orders if order.order_ref != order_ref]

    def resize(self, order_ref: str, quantity: int) -> BrokerStockOrder:
        self.mutations.append(f"resize:{order_ref}:{quantity}")
        return next(order for order in self._orders if order.order_ref == order_ref)

    def cancel_symbol_orders(self, symbol: str, *, exclude_refs: set[str] | None = None) -> None:
        self.mutations.append(f"cancel_symbol:{symbol}")
        excluded = exclude_refs or set()
        self._orders = [order for order in self._orders if order.symbol != symbol or order.order_ref in excluded]

    def submit_exit_limit(self, symbol: str, action: str, quantity: int, price: float, order_ref: str):
        self.mutations.append(f"limit:{action}:{quantity}:{price}:{order_ref}")
        return _broker_order(
            order_ref,
            action,
            quantity,
            StockOrderLifecycle.SUBMITTED.value,
            perm_id=100 + len(self.mutations),
        )

    def submit_emergency_market(self, symbol: str, action: str, quantity: int, order_ref: str):
        self.mutations.append(f"market:{action}:{quantity}:{order_ref}")
        return _broker_order(
            order_ref,
            action,
            quantity,
            StockOrderLifecycle.SUBMITTED.value,
            perm_id=100 + len(self.mutations),
            order_type="MKT",
        )


def _broker_order(
    order_ref: str,
    action: str,
    quantity: int,
    status: str,
    *,
    filled: int = 0,
    perm_id: int = 10,
    order_type: str = "LMT",
    stop_price: float = 0.0,
) -> BrokerStockOrder:
    return BrokerStockOrder(
        order_ref,
        0,
        perm_id,
        perm_id,
        "SPY",
        action,
        quantity,
        filled,
        order_type,
        600.0,
        stop_price,
        status,
    )


def _intent(session_date: date) -> BracketIntent:
    timestamp = datetime.now(timezone.utc)
    return BracketIntent(
        "AFSCALP-RECOVERY",
        "AFSCALP-RECOVERY-P",
        "AFSCALP-RECOVERY-TP",
        "AFSCALP-RECOVERY-SL",
        ScalpDirection.LONG,
        "SPY",
        100,
        600.0,
        600.90,
        599.40,
        0.60,
        session_date,
        timestamp,
    )


def _service(tmp_path: Path, monkeypatch, account_id: str = "DU123"):
    monkeypatch.setenv("IBKR_SCALP_PAPER_ACCOUNT", "DU123")
    persistence = ScalpPersistenceConfig(
        database=tmp_path / "scalper.db",
        journal=tmp_path / "audit.jsonl",
        halt_file=tmp_path / "SCALP_HALT",
        lock_file=tmp_path / "LOCK",
        heartbeat_file=tmp_path / "heartbeat.json",
    )
    config = replace(
        ScalpConfig(),
        persistence=persistence,
        backtest=replace(ScalpBacktestConfig(), cache_path=tmp_path / "bars.csv.gz"),
    )
    store = ScalpingStore(persistence.database, persistence.journal)
    broker = FakeStockBroker(account_id)
    service = ScalpingService(config, broker, store, NullScalpAlertSink(store))
    return config, store, broker, service


def test_wrong_or_live_account_disconnects_without_any_broker_mutation(tmp_path: Path, monkeypatch):
    config, store, broker, service = _service(tmp_path, monkeypatch, account_id="U123")
    broker._orders.append(_broker_order("AFSCALP-DO-NOT-TOUCH-P", "BUY", 10, "SUBMITTED"))
    result = service.reconcile()
    assert not result.ok
    assert broker.mutations == []
    assert not broker.connected
    assert "wrong account" in store.halt_reason(config.persistence.halt_file)


def test_unknown_manual_order_and_position_halt(tmp_path: Path, monkeypatch):
    config, store, broker, service = _service(tmp_path, monkeypatch)
    broker._orders.append(_broker_order("manual", "BUY", 10, "SUBMITTED"))
    broker._positions.append(BrokerStockPosition("DU123", "AAPL", 5, 200.0))
    result = service.reconcile()
    assert not result.ok
    assert "unknown/manual" in ";".join(result.issues)
    assert "unknown broker position" in ";".join(result.issues)
    assert store.halt_reason(config.persistence.halt_file)


def test_crash_window_recovers_only_exact_reserved_bracket(tmp_path: Path, monkeypatch):
    _config, store, broker, service = _service(tmp_path, monkeypatch)
    today = datetime.now(timezone.utc).astimezone(ET).date()
    intent = _intent(today)
    assert store.reserve_bracket(intent)
    broker._orders.extend(
        [
            _broker_order(intent.parent_order_ref, "BUY", 100, "FILLED", filled=100, perm_id=11),
            _broker_order(intent.take_profit_order_ref, "SELL", 100, "SUBMITTED", perm_id=12),
            _broker_order(
                intent.stop_order_ref,
                "SELL",
                100,
                "SUBMITTED",
                perm_id=13,
                order_type="STP",
                stop_price=599.40,
            ),
        ]
    )
    broker._positions.append(BrokerStockPosition("DU123", "SPY", 100, 600.0))
    broker._fills.append(StockFillRecord("exec-1", intent.parent_order_ref, 11, "SPY", "BOT", 100, 600.0))
    result = service.reconcile()
    assert result.ok
    assert result.protected
    position = store.open_position()
    assert position is not None and position.quantity == 100 and position.stop_perm_id == 13
    assert broker.mutations == []


def test_unprotected_broker_position_triggers_emergency_market_exit(tmp_path: Path, monkeypatch):
    config, store, broker, service = _service(tmp_path, monkeypatch)
    broker._positions.append(BrokerStockPosition("DU123", "SPY", 25, 600.0))
    result = service.run_cycle()
    assert result.halted
    assert any(mutation.startswith("market:SELL:25") for mutation in broker.mutations)
    assert store.halt_reason(config.persistence.halt_file)


def test_duplicate_bracket_never_reaches_broker(tmp_path: Path, monkeypatch):
    _config, store, broker, service = _service(tmp_path, monkeypatch)
    service.config = replace(service.config, shadow_mode=False, trading_enabled=True)
    store.set_metadata("backtest_passed", "true")
    for day in range(10, 15):
        store.update_session(date(2026, 8, day), shadow_complete=1)
    intent = _intent(datetime.now(timezone.utc).date())
    assert store.reserve_bracket(intent)
    account = broker.account_snapshot()
    service._submit_paper_bracket(intent, account)
    assert broker.mutations == []


def test_daily_loss_locks_session_and_uses_two_limits_before_market(tmp_path: Path, monkeypatch):
    _config, store, broker, service = _service(tmp_path, monkeypatch)
    today = datetime.now(timezone.utc).astimezone(ET).date()
    now = datetime.now(timezone.utc)
    position = ScalpPosition(
        "AFSCALP-LOSS",
        ScalpDirection.LONG,
        "SPY",
        100,
        600.0,
        599.4,
        600.9,
        now,
        today,
    )
    store.save_position(position)
    store.session_state(today, 100_000.0)
    broker._positions.append(BrokerStockPosition("DU123", "SPY", 100, 600.0))
    broker._quote = replace(broker._quote, bid=589.0, ask=589.02, timestamp_utc=now)
    service._manage_open_position(position, 100, now)
    assert store.session_state(today)["daily_locked"] == 1
    assert len([mutation for mutation in broker.mutations if mutation.startswith("limit:SELL")]) == 2
    assert any(mutation.startswith("market:SELL") for mutation in broker.mutations)


def test_entry_limits_cooldown_rearm_losses_and_daily_lock(tmp_path: Path, monkeypatch):
    _config, store, _broker, service = _service(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    today = now.astimezone(ET).date()
    signal = ScalpSignal(
        ScalpDirection.LONG,
        today,
        now,
        now.astimezone(ET),
        600.0,
        600.0,
        599.0,
        599.8,
        600.1,
        600.0,
        2.0,
        0.5,
    )
    store.update_session(today, last_exit_at=now.isoformat())
    assert not service._entry_state_allows(signal, store.session_state(today), now)
    store.update_session(today, last_exit_at="", rearmed_long=0)
    assert not service._entry_state_allows(signal, store.session_state(today), now)
    store.update_session(today, rearmed_long=1, consecutive_losses=3)
    assert not service._entry_state_allows(signal, store.session_state(today), now)
    store.update_session(today, consecutive_losses=0, daily_locked=1)
    assert not service._entry_state_allows(signal, store.session_state(today), now)
    store.update_session(today, daily_locked=0, entries=5)
    assert not service._entry_state_allows(signal, store.session_state(today), now)
