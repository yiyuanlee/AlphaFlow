import json
from pathlib import Path

from alphaflow.options.unattended.store import UnattendedStore
from alphaflow.options.unattended.types import OrderLifecycle, OrderRecord


def test_sqlite_order_roundtrip_and_halt(tmp_path: Path):
    store = UnattendedStore(tmp_path / "state.db")
    order = OrderRecord(
        intent_id="entry:1",
        order_ref="AFV11-1",
        purpose="entry",
        action="SELL",
        symbol="QQQ",
        quantity=1,
        limit_price=2.5,
    )
    store.upsert_order(order)
    assert store.get_order(intent_id="entry:1") == order
    updated = store.update_order("entry:1", status=OrderLifecycle.SUBMITTED.value, broker_order_id=10)
    assert updated.broker_order_id == 10
    assert len(store.active_orders()) == 1

    halt_file = tmp_path / "HALT"
    store.set_halt("test", halt_file)
    assert store.halt_state(halt_file) == (True, "test")
    store.clear_halt(halt_file)
    assert store.halt_state(halt_file)[0] is False


def test_alert_deduplication_and_shadow_sessions(tmp_path: Path):
    store = UnattendedStore(tmp_path / "state.db")
    assert store.should_send_alert("x", 15, "message") is True
    assert store.should_send_alert("x", 15, "message") is False
    assert store.mark_shadow_session("2026-08-19") == 1
    assert store.mark_shadow_session("2026-08-19") == 1
    assert store.mark_monitor_session("2026-08-19") == 1
    assert store.status_dict()["monitored_trading_sessions"] == 1


def test_legacy_json_is_imported_as_reconciliation_required(tmp_path: Path):
    legacy = tmp_path / "options_positions.json"
    legacy.write_text(
        json.dumps(
            {
                "positions": {
                    "old": {
                        "strategy": "covered_call",
                        "symbol": "QQQ",
                        "quantity": 1,
                        "entry_premium": 2.5,
                        "expiry": "20260918",
                        "status": "open",
                        "legs": [
                            {
                                "symbol": "QQQ",
                                "expiry": "20260918",
                                "strike": 610,
                                "right": "C",
                                "action": "SELL",
                                "ratio": 1,
                                "con_id": 123,
                            }
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    store = UnattendedStore(tmp_path / "state.db")
    assert store.import_legacy_positions(legacy) == 1
    assert store.open_strategy_position("QQQ")["status"] == "RECONCILIATION_REQUIRED"
    assert store.import_legacy_positions(legacy) == 0
