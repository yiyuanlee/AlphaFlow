from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from alphaflow.options.unattended.alerts import NullAlertSink
from alphaflow.options.unattended.config import PersistenceConfig, UnattendedPaperConfig
from alphaflow.options.unattended.service import UnattendedService
from alphaflow.options.unattended.store import UnattendedStore
from alphaflow.options.unattended.types import (
    AccountSnapshot,
    BrokerOrder,
    BrokerPosition,
    DailyBar,
    FillRecord,
    OptionMarketQuote,
    OrderLifecycle,
    OrderRecord,
)

NOW = datetime(2026, 8, 19, 14, 15, tzinfo=timezone.utc)  # 10:15 ET


class FakeBroker:
    def __init__(self, account_id: str = "DU123", shares: int = 100):
        self.connected = False
        self.account_id = account_id
        self._positions = [BrokerPosition(account_id, "QQQ", "STK", shares, 500.0, con_id=1)]
        self._orders: list[BrokerOrder] = []
        self._fills: list[FillRecord] = []
        self.submissions: list[str] = []
        self.quote = OptionMarketQuote(
            "QQQ", "20260918", 610.0, "C", 0.25, 2.90, 3.10, NOW.isoformat(), 123, 100, False
        )

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def is_connected(self) -> bool:
        return self.connected

    def wait(self, _seconds: float) -> None:
        return None

    def account_snapshot(self) -> AccountSnapshot:
        return AccountSnapshot(self.account_id, 100_000.0, 50_000.0)

    def positions(self) -> list[BrokerPosition]:
        return list(self._positions)

    def open_orders(self) -> list[BrokerOrder]:
        return list(self._orders)

    def executions(self) -> list[FillRecord]:
        return list(self._fills)

    def daily_bars(self, _symbol: str, _minimum_bars: int) -> list[DailyBar]:
        start = datetime(2025, 10, 1, tzinfo=timezone.utc)
        return [DailyBar((start + timedelta(days=i)).date().isoformat(), 400.0 + i) for i in range(230)]

    def covered_call_quotes(self, _symbol: str, _dte_min: int, _dte_max: int):
        return 600.0, [self.quote]

    def option_quote(self, *_args):
        return self.quote

    def submit_limit(self, intent, _tif: str) -> BrokerOrder:
        self.submissions.append(intent.order_ref)
        order = BrokerOrder(
            intent.order_ref,
            len(self._orders) + 1,
            1000 + len(self._orders),
            intent.symbol,
            "OPT",
            intent.action,
            intent.quantity,
            0,
            intent.limit_price,
            OrderLifecycle.SUBMITTED.value,
            intent.con_id,
            intent.expiry,
            intent.strike,
            intent.right,
        )
        self._orders.append(order)
        return order

    def modify_limit(self, order_ref: str, limit_price: float) -> BrokerOrder:
        order = next(order for order in self._orders if order.order_ref == order_ref)
        updated = replace(order, limit_price=limit_price)
        self._orders[self._orders.index(order)] = updated
        return updated

    def cancel(self, order_ref: str) -> None:
        self._orders = [order for order in self._orders if order.order_ref != order_ref]


def _service(tmp_path: Path, monkeypatch, *, shadow: bool, enabled: bool, shares: int = 100, account="DU123"):
    monkeypatch.setenv("IBKR_PAPER_ACCOUNT", "DU123")
    persistence = PersistenceConfig(
        database=tmp_path / "state.db",
        journal=tmp_path / "journal.jsonl",
        halt_file=tmp_path / "HALT",
        lock_file=tmp_path / "LOCK",
    )
    config = replace(UnattendedPaperConfig(), shadow_mode=shadow, trading_enabled=enabled, persistence=persistence)
    store = UnattendedStore(persistence.database)
    broker = FakeBroker(account, shares)
    service = UnattendedService(config, broker, store, NullAlertSink(persistence.journal))
    return config, store, broker, service


def test_shadow_cycle_is_recorded_once_per_session(tmp_path: Path, monkeypatch):
    _config, store, broker, service = _service(tmp_path, monkeypatch, shadow=True, enabled=False)
    assert service.run_cycle(NOW).ok
    assert service.run_cycle(NOW).ok
    assert len(store.shadow_sessions()) == 1
    assert broker.submissions == []


def test_real_paper_entry_requires_shadow_gate_and_is_idempotent(tmp_path: Path, monkeypatch):
    _config, store, broker, service = _service(tmp_path, monkeypatch, shadow=False, enabled=True)
    for i in range(5):
        store.mark_shadow_session(f"2026-08-{10 + i:02d}")
    assert service.run_cycle(NOW).ok
    assert len(broker.submissions) == 1
    assert service.run_cycle(NOW).ok
    assert len(broker.submissions) == 1


def test_missing_collateral_and_live_account_halt(tmp_path: Path, monkeypatch):
    config, store, _broker, service = _service(tmp_path, monkeypatch, shadow=True, enabled=False, shares=0)
    result = service.reconcile()
    assert not result.ok
    assert store.halt_state(config.persistence.halt_file)[0]

    config2, store2, _broker2, service2 = _service(
        tmp_path / "live", monkeypatch, shadow=True, enabled=False, shares=100, account="U123"
    )
    result2 = service2.reconcile()
    assert not result2.ok
    assert store2.halt_state(config2.persistence.halt_file)[0]


def test_profit_target_submits_buy_to_close(tmp_path: Path, monkeypatch):
    _config, store, broker, service = _service(tmp_path, monkeypatch, shadow=False, enabled=True)
    filled = OrderRecord(
        intent_id="entry",
        order_ref="AFV11-entry",
        purpose="entry",
        action="SELL",
        symbol="QQQ",
        quantity=1,
        limit_price=2.0,
        status=OrderLifecycle.FILLED.value,
        expiry="20260918",
        strike=610.0,
        right="C",
        con_id=123,
        filled_quantity=1,
        average_fill_price=2.0,
    )
    store.upsert_order(filled)
    store.create_strategy_position(filled)
    broker._positions.append(BrokerPosition("DU123", "QQQ", "OPT", -1, 200.0, 123, "20260918", 610, "C", 100))
    broker.quote = replace(broker.quote, bid=0.90, ask=1.00)
    assert service.run_cycle(NOW).ok
    assert len(broker.submissions) == 1
    exit_order = store.active_orders("exit")[0]
    assert exit_order.action == "BUY"


def test_recovered_broker_order_prevents_duplicate_submission(tmp_path: Path, monkeypatch):
    _config, store, broker, service = _service(tmp_path, monkeypatch, shadow=False, enabled=True)
    for i in range(5):
        store.mark_shadow_session(f"2026-08-{10 + i:02d}")
    broker._orders.append(
        BrokerOrder(
            "AFV11-recovered",
            77,
            88,
            "QQQ",
            "OPT",
            "SELL",
            1,
            0,
            3.0,
            OrderLifecycle.SUBMITTED.value,
            123,
            "20260918",
            610.0,
            "C",
        )
    )
    assert service.run_cycle(NOW).ok
    assert broker.submissions == []
    assert store.get_order(order_ref="AFV11-recovered") is not None


def test_halt_cancels_pending_entry_but_keeps_daemon_reconciling(tmp_path: Path, monkeypatch):
    config, store, broker, service = _service(tmp_path, monkeypatch, shadow=False, enabled=True)
    for i in range(5):
        store.mark_shadow_session(f"2026-08-{10 + i:02d}")
    assert service.run_cycle(NOW).ok
    assert len(broker._orders) == 1
    store.set_halt("operator", config.persistence.halt_file)
    assert service.run_cycle(NOW).ok
    assert broker._orders == []
    assert store.active_orders("entry") == []


def test_missing_broker_call_for_local_position_halts_immediately(tmp_path: Path, monkeypatch):
    config, store, _broker, service = _service(tmp_path, monkeypatch, shadow=False, enabled=True)
    filled = OrderRecord(
        intent_id="entry",
        order_ref="AFV11-entry",
        purpose="entry",
        action="SELL",
        symbol="QQQ",
        quantity=1,
        limit_price=2.0,
        status=OrderLifecycle.FILLED.value,
        expiry="20260918",
        strike=610.0,
        right="C",
        con_id=123,
        filled_quantity=1,
        average_fill_price=2.0,
    )
    store.upsert_order(filled)
    store.create_strategy_position(filled)
    result = service.reconcile()
    assert not result.ok
    assert store.halt_state(config.persistence.halt_file)[0]


def test_unknown_manual_qqq_option_order_halts(tmp_path: Path, monkeypatch):
    config, store, broker, service = _service(tmp_path, monkeypatch, shadow=True, enabled=False)
    broker._orders.append(
        BrokerOrder(
            "manual-order",
            90,
            91,
            "QQQ",
            "OPT",
            "SELL",
            1,
            0,
            3.0,
            OrderLifecycle.SUBMITTED.value,
            123,
            "20260918",
            610.0,
            "C",
        )
    )
    result = service.reconcile()
    assert not result.ok
    assert store.halt_state(config.persistence.halt_file)[0]


def test_unknown_option_position_halts_even_when_it_is_not_a_short_call(tmp_path: Path, monkeypatch):
    config, store, broker, service = _service(tmp_path, monkeypatch, shadow=True, enabled=False)
    broker._positions.append(
        BrokerPosition("DU123", "SPY", "OPT", 1, 100.0, 999, "20260918", 650.0, "P", 100)
    )
    result = service.reconcile()
    assert not result.ok
    assert "unknown option position" in ";".join(result.issues)
    assert store.halt_state(config.persistence.halt_file)[0]


def test_wrong_account_cycle_disconnects_without_touching_orders(tmp_path: Path, monkeypatch):
    _config, _store, broker, service = _service(
        tmp_path, monkeypatch, shadow=False, enabled=True, account="U123"
    )
    broker._orders.append(
        BrokerOrder(
            "AFV11-do-not-touch",
            1,
            2,
            "QQQ",
            "OPT",
            "SELL",
            1,
            0,
            3.0,
            OrderLifecycle.SUBMITTED.value,
            123,
            "20260918",
            610.0,
            "C",
        )
    )
    result = service.run_cycle(NOW)
    assert result is not None and not result.ok
    assert [order.order_ref for order in broker._orders] == ["AFV11-do-not-touch"]
    assert not broker.is_connected()


def test_bearish_shadow_day_counts_as_a_valid_read_only_session(tmp_path: Path, monkeypatch):
    _config, store, broker, service = _service(tmp_path, monkeypatch, shadow=True, enabled=False)

    def bearish_bars(_symbol: str, _minimum_bars: int) -> list[DailyBar]:
        start = datetime(2025, 10, 1, tzinfo=timezone.utc)
        return [DailyBar((start + timedelta(days=i)).date().isoformat(), 700.0 - i) for i in range(230)]

    broker.daily_bars = bearish_bars
    result = service.run_cycle(NOW)
    assert result is not None and result.ok
    assert store.shadow_sessions() == ["2026-08-19"]
    assert broker.submissions == []


def test_historical_exit_fill_cannot_close_a_later_position(tmp_path: Path, monkeypatch):
    _config, store, broker, service = _service(tmp_path, monkeypatch, shadow=False, enabled=True)
    current_entry = OrderRecord(
        intent_id="current-entry",
        order_ref="AFV11-current-entry",
        purpose="entry",
        action="SELL",
        symbol="QQQ",
        quantity=1,
        limit_price=2.0,
        status=OrderLifecycle.FILLED.value,
        expiry="20261016",
        strike=620.0,
        right="C",
        con_id=456,
        filled_quantity=1,
        average_fill_price=2.0,
    )
    old_exit = OrderRecord(
        intent_id="old-exit",
        order_ref="AFV11-old-exit",
        purpose="exit",
        action="BUY",
        symbol="QQQ",
        quantity=1,
        limit_price=1.0,
        status=OrderLifecycle.FILLED.value,
        expiry="20260918",
        strike=610.0,
        right="C",
        con_id=123,
        filled_quantity=1,
        average_fill_price=1.0,
    )
    old_fill = FillRecord("old-fill", old_exit.order_ref, 99, "QQQ", "BOT", 1, 1.0)
    store.upsert_order(current_entry)
    store.create_strategy_position(current_entry)
    store.upsert_order(old_exit)
    store.record_fill(old_fill)
    broker._fills.append(old_fill)
    broker._positions.append(
        BrokerPosition("DU123", "QQQ", "OPT", -1, 200.0, 456, "20261016", 620.0, "C", 100)
    )

    result = service.reconcile()

    assert result.ok
    assert store.open_strategy_position("QQQ")["entry_order_ref"] == current_entry.order_ref


def test_created_order_missing_at_broker_halts_after_one_grace_cycle(tmp_path: Path, monkeypatch):
    config, store, broker, service = _service(tmp_path, monkeypatch, shadow=False, enabled=True)
    store.upsert_order(
        OrderRecord(
            intent_id="crash-window",
            order_ref="AFV11-crash-window",
            purpose="entry",
            action="SELL",
            symbol="QQQ",
            quantity=1,
            limit_price=3.0,
        )
    )

    first = service.reconcile()
    second = service.reconcile()

    assert not first.ok and not second.ok
    assert store.halt_state(config.persistence.halt_file)[0]
    assert broker.submissions == []
