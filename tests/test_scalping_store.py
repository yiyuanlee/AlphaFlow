from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from alphaflow.scalping.store import ScalpingStore
from alphaflow.scalping.types import BracketIntent, ScalpDirection, StockFillRecord


def _intent() -> BracketIntent:
    return BracketIntent(
        "AFSCALP-ABC",
        "AFSCALP-ABC-P",
        "AFSCALP-ABC-TP",
        "AFSCALP-ABC-SL",
        ScalpDirection.LONG,
        "SPY",
        100,
        100.0,
        100.15,
        99.90,
        0.10,
        date(2026, 8, 19),
        datetime(2026, 8, 19, 14, 0, tzinfo=timezone.utc),
    )


def test_bracket_reservation_is_atomic_and_survives_restart(tmp_path: Path):
    database = tmp_path / "scalper.db"
    store = ScalpingStore(database, tmp_path / "audit.jsonl")
    assert store.reserve_bracket(_intent())
    assert not store.reserve_bracket(_intent())
    reopened = ScalpingStore(database)
    assert len(reopened.orders_for_intent("AFSCALP-ABC")) == 3
    assert {order.order_ref for order in reopened.active_orders()} == {
        "AFSCALP-ABC-P",
        "AFSCALP-ABC-TP",
        "AFSCALP-ABC-SL",
    }


def test_halt_and_session_state_are_independent(tmp_path: Path):
    store = ScalpingStore(tmp_path / "scalper.db")
    halt_file = tmp_path / "SCALP_HALT"
    store.set_halt("operator", halt_file)
    store.update_session(date(2026, 8, 19), entries=5, daily_locked=1)
    assert store.halt_reason(halt_file) == "operator"
    assert store.session_state(date(2026, 8, 19))["entries"] == 5
    store.clear_halt(halt_file)
    assert store.halt_reason(halt_file) == ""


def test_late_commission_report_updates_existing_execution(tmp_path: Path):
    store = ScalpingStore(tmp_path / "scalper.db")
    original = StockFillRecord("exec-1", "AFSCALP-X-P", 10, "SPY", "BOT", 10, 600.0)
    updated = StockFillRecord("exec-1", "AFSCALP-X-P", 10, "SPY", "BOT", 10, 600.0, 1.25)
    assert store.record_fill(original)
    assert not store.record_fill(updated)
    assert store.fills_for_refs({"AFSCALP-X-P"})[0].commission == 1.25
