"""Transactional SQLite state for the unattended paper service."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .types import ACTIVE_ORDER_STATES, BrokerPosition, FillRecord, HealthSnapshot, OrderRecord, utc_now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    intent_id TEXT PRIMARY KEY,
    order_ref TEXT NOT NULL UNIQUE,
    purpose TEXT NOT NULL,
    action TEXT NOT NULL,
    symbol TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    limit_price REAL NOT NULL,
    status TEXT NOT NULL,
    expiry TEXT NOT NULL,
    strike REAL NOT NULL,
    right TEXT NOT NULL,
    con_id INTEGER NOT NULL,
    broker_order_id INTEGER NOT NULL,
    perm_id INTEGER NOT NULL,
    filled_quantity INTEGER NOT NULL,
    average_fill_price REAL NOT NULL,
    attempts INTEGER NOT NULL,
    last_error TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fills (
    execution_id TEXT PRIMARY KEY,
    order_ref TEXT NOT NULL,
    perm_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price REAL NOT NULL,
    commission REAL NOT NULL,
    occurred_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS strategy_positions (
    position_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    expiry TEXT NOT NULL,
    strike REAL NOT NULL,
    right TEXT NOT NULL,
    con_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    entry_credit REAL NOT NULL,
    entry_order_ref TEXT NOT NULL,
    exit_order_ref TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    closed_at TEXT NOT NULL DEFAULT '',
    last_reconciled_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS broker_positions (
    account_id TEXT NOT NULL,
    con_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    security_type TEXT NOT NULL,
    quantity REAL NOT NULL,
    average_cost REAL NOT NULL,
    expiry TEXT NOT NULL,
    strike REAL NOT NULL,
    right TEXT NOT NULL,
    multiplier INTEGER NOT NULL,
    observed_at TEXT NOT NULL,
    PRIMARY KEY (account_id, con_id, symbol, security_type, expiry, strike, right)
);
CREATE TABLE IF NOT EXISTS cycles (
    cycle_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
    alert_key TEXT PRIMARY KEY,
    sent_at TEXT NOT NULL,
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_positions_status ON strategy_positions(status);
"""


class UnattendedStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA busy_timeout=15000")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def get_meta(self, key: str, default: Any = None) -> Any:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default

    def set_meta(self, key: str, value: Any) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO metadata(key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, json.dumps(value, ensure_ascii=False), utc_now_iso()),
            )

    def set_halt(self, reason: str, halt_file: Path | None = None) -> None:
        payload = {"halted": True, "reason": reason, "at": utc_now_iso()}
        self.set_meta("halt", payload)
        if halt_file is not None:
            halt_file.parent.mkdir(parents=True, exist_ok=True)
            halt_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def clear_halt(self, halt_file: Path | None = None) -> None:
        self.set_meta("halt", {"halted": False, "reason": "", "at": utc_now_iso()})
        if halt_file is not None and halt_file.exists():
            halt_file.unlink()

    def halt_state(self, halt_file: Path | None = None) -> tuple[bool, str]:
        state = self.get_meta("halt", {})
        file_halt = bool(halt_file and halt_file.exists())
        halted = bool(state.get("halted", False)) or file_halt
        reason = str(state.get("reason", "manual HALT file present" if file_halt else ""))
        return halted, reason

    def upsert_order(self, order: OrderRecord) -> None:
        values = asdict(order)
        columns = list(values)
        placeholders = ",".join("?" for _ in columns)
        updates = ",".join(f"{column}=excluded.{column}" for column in columns if column != "intent_id")
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO orders({','.join(columns)}) VALUES ({placeholders}) "
                f"ON CONFLICT(intent_id) DO UPDATE SET {updates}",
                tuple(values[column] for column in columns),
            )

    def get_order(self, *, intent_id: str | None = None, order_ref: str | None = None) -> OrderRecord | None:
        if not intent_id and not order_ref:
            raise ValueError("intent_id or order_ref is required")
        key = "intent_id" if intent_id else "order_ref"
        value = intent_id or order_ref
        with self._connect() as conn:
            row = conn.execute(f"SELECT * FROM orders WHERE {key} = ?", (value,)).fetchone()
        return OrderRecord(**dict(row)) if row else None

    def active_orders(self, purpose: str | None = None) -> list[OrderRecord]:
        placeholders = ",".join("?" for _ in ACTIVE_ORDER_STATES)
        sql = f"SELECT * FROM orders WHERE status IN ({placeholders})"
        params: list[Any] = list(ACTIVE_ORDER_STATES)
        if purpose:
            sql += " AND purpose = ?"
            params.append(purpose)
        sql += " ORDER BY created_at"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [OrderRecord(**dict(row)) for row in rows]

    def update_order(
        self,
        intent_id: str,
        *,
        status: str | None = None,
        broker_order_id: int | None = None,
        perm_id: int | None = None,
        filled_quantity: int | None = None,
        average_fill_price: float | None = None,
        limit_price: float | None = None,
        attempts: int | None = None,
        last_error: str | None = None,
    ) -> OrderRecord:
        current = self.get_order(intent_id=intent_id)
        if current is None:
            raise KeyError(intent_id)
        data = asdict(current)
        for key, value in {
            "status": status,
            "broker_order_id": broker_order_id,
            "perm_id": perm_id,
            "filled_quantity": filled_quantity,
            "average_fill_price": average_fill_price,
            "limit_price": limit_price,
            "attempts": attempts,
            "last_error": last_error,
        }.items():
            if value is not None:
                data[key] = value
        data["updated_at"] = utc_now_iso()
        updated = OrderRecord(**data)
        self.upsert_order(updated)
        return updated

    def record_fill(self, fill: FillRecord) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO fills(
                    execution_id, order_ref, perm_id, symbol, action,
                    quantity, price, commission, occurred_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(asdict(fill).values()),
            )
        return bool(cursor.rowcount)

    def open_strategy_position(self, symbol: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM strategy_positions WHERE symbol = ? AND status IN ('OPEN', 'EXIT_PENDING', "
                "'RECONCILIATION_REQUIRED') ORDER BY opened_at DESC LIMIT 1",
                (symbol,),
            ).fetchone()
        return dict(row) if row else None

    def create_strategy_position(self, order: OrderRecord) -> None:
        if order.status != "FILLED":
            raise ValueError("a strategy position can only be created from a filled order")
        position_id = f"{order.symbol}:{order.con_id}:{order.order_ref}"
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO strategy_positions(
                    position_id, symbol, expiry, strike, right, con_id, quantity,
                    entry_credit, entry_order_ref, status, opened_at, last_reconciled_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)
                """,
                (
                    position_id,
                    order.symbol,
                    order.expiry,
                    order.strike,
                    order.right,
                    order.con_id,
                    order.filled_quantity or order.quantity,
                    order.average_fill_price,
                    order.order_ref,
                    now,
                    now,
                ),
            )

    def update_strategy_position(
        self,
        symbol: str,
        status: str,
        exit_order_ref: str = "",
        position_id: str = "",
    ) -> None:
        now = utc_now_iso()
        closed_at = now if status == "CLOSED" else ""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE strategy_positions
                SET status = ?, exit_order_ref = CASE WHEN ? = '' THEN exit_order_ref ELSE ? END,
                    closed_at = CASE WHEN ? = '' THEN closed_at ELSE ? END,
                    last_reconciled_at = ?
                WHERE symbol = ? AND status IN ('OPEN', 'EXIT_PENDING', 'RECONCILIATION_REQUIRED')
                    AND (? = '' OR position_id = ?)
                """,
                (
                    status,
                    exit_order_ref,
                    exit_order_ref,
                    closed_at,
                    closed_at,
                    now,
                    symbol,
                    position_id,
                    position_id,
                ),
            )

    def replace_broker_positions(self, positions: Iterable[BrokerPosition]) -> None:
        observed_at = utc_now_iso()
        with self._connect() as conn:
            conn.execute("DELETE FROM broker_positions")
            conn.executemany(
                """
                INSERT INTO broker_positions(
                    account_id, con_id, symbol, security_type, quantity, average_cost,
                    expiry, strike, right, multiplier, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        p.account_id,
                        p.con_id,
                        p.symbol,
                        p.security_type,
                        p.quantity,
                        p.average_cost,
                        p.expiry,
                        p.strike,
                        p.right,
                        p.multiplier,
                        observed_at,
                    )
                    for p in positions
                ],
            )

    def record_cycle(self, started_at: str, status: str, detail: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO cycles(started_at, finished_at, status, detail) VALUES (?, ?, ?, ?)",
                (started_at, utc_now_iso(), status, detail),
            )
        self.set_meta("last_cycle", {"status": status, "detail": detail, "at": utc_now_iso()})

    def write_heartbeat(self, snapshot: HealthSnapshot) -> None:
        self.set_meta("heartbeat", snapshot.to_dict())

    def shadow_sessions(self) -> list[str]:
        return list(self.get_meta("shadow_sessions", []))

    def mark_shadow_session(self, session_date: str) -> int:
        sessions = set(self.shadow_sessions())
        sessions.add(session_date)
        ordered = sorted(sessions)
        self.set_meta("shadow_sessions", ordered)
        return len(ordered)

    def monitor_sessions(self) -> list[str]:
        return list(self.get_meta("monitor_sessions", []))

    def mark_monitor_session(self, session_date: str) -> int:
        sessions = set(self.monitor_sessions())
        sessions.add(session_date)
        ordered = sorted(sessions)
        self.set_meta("monitor_sessions", ordered)
        return len(ordered)

    def entry_attempted(self, session_date: str) -> bool:
        return bool(self.get_meta(f"entry_attempt:{session_date}", False))

    def mark_entry_attempt(self, session_date: str, intent_id: str) -> None:
        self.set_meta(f"entry_attempt:{session_date}", {"intent_id": intent_id, "at": utc_now_iso()})

    def mark_close_completed(self, session_date: str) -> None:
        self.set_meta(f"close_completed:{session_date}", True)

    def close_completed(self, session_date: str) -> bool:
        return bool(self.get_meta(f"close_completed:{session_date}", False))

    def should_send_alert(self, alert_key: str, minutes: int, message: str) -> bool:
        now = datetime.now(timezone.utc)
        with self._connect() as conn:
            row = conn.execute("SELECT sent_at FROM alerts WHERE alert_key = ?", (alert_key,)).fetchone()
            if row:
                try:
                    sent_at = datetime.fromisoformat(row["sent_at"])
                    if now - sent_at < timedelta(minutes=minutes):
                        return False
                except ValueError:
                    pass
            conn.execute(
                """
                INSERT INTO alerts(alert_key, sent_at, message) VALUES (?, ?, ?)
                ON CONFLICT(alert_key) DO UPDATE SET sent_at=excluded.sent_at, message=excluded.message
                """,
                (alert_key, now.isoformat(), message),
            )
        return True

    def status_dict(self, halt_file: Path | None = None) -> dict[str, Any]:
        halted, reason = self.halt_state(halt_file)
        heartbeat = self.get_meta("heartbeat", {})
        last_cycle = self.get_meta("last_cycle", {})
        with self._connect() as conn:
            active_orders = conn.execute(
                "SELECT COUNT(*) AS n FROM orders WHERE status IN ('CREATED','SUBMITTED','PARTIALLY_FILLED')"
            ).fetchone()["n"]
            open_positions = conn.execute(
                "SELECT COUNT(*) AS n FROM strategy_positions WHERE status IN ('OPEN','EXIT_PENDING',"
                "'RECONCILIATION_REQUIRED')"
            ).fetchone()["n"]
            closed_positions = conn.execute(
                "SELECT COUNT(*) AS n FROM strategy_positions WHERE status = 'CLOSED'"
            ).fetchone()["n"]
            cycles = conn.execute(
                "SELECT COUNT(*) AS total, SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END) AS healthy FROM cycles"
            ).fetchone()
        total_cycles = int(cycles["total"] or 0)
        healthy_cycles = int(cycles["healthy"] or 0)
        return {
            "halted": halted,
            "halt_reason": reason,
            "heartbeat": heartbeat,
            "last_cycle": last_cycle,
            "active_orders": active_orders,
            "open_positions": open_positions,
            "completed_trade_cycles": closed_positions,
            "monitoring_cycles": total_cycles,
            "healthy_cycle_pct": round(healthy_cycles / total_cycles * 100, 2) if total_cycles else 0.0,
            "shadow_sessions": len(self.shadow_sessions()),
            "monitored_trading_sessions": len(self.monitor_sessions()),
            "database": str(self.path),
        }

    def import_legacy_positions(self, path: Path) -> int:
        """Import legacy JSON as reconciliation-required records exactly once."""
        if self.get_meta("legacy_import_done", False):
            return 0
        self.set_meta("legacy_import_done", True)
        if not path.is_file():
            return 0
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.set_meta("legacy_import_error", f"unable to read {path}")
            return 0
        imported = 0
        now = utc_now_iso()
        with self._connect() as conn:
            existing = conn.execute("SELECT COUNT(*) AS n FROM strategy_positions").fetchone()["n"]
            if existing:
                return 0
            for legacy_id, item in payload.get("positions", {}).items():
                if item.get("status", "open") != "open":
                    continue
                legs = item.get("legs", [])
                if not legs:
                    continue
                leg = legs[0]
                conn.execute(
                    """
                    INSERT OR IGNORE INTO strategy_positions(
                        position_id, symbol, expiry, strike, right, con_id, quantity,
                        entry_credit, entry_order_ref, status, opened_at, last_reconciled_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'RECONCILIATION_REQUIRED', ?, ?)
                    """,
                    (
                        f"legacy:{legacy_id}",
                        str(item.get("symbol", leg.get("symbol", ""))),
                        str(item.get("expiry", leg.get("expiry", ""))),
                        float(leg.get("strike", 0.0)),
                        str(leg.get("right", "C")),
                        int(leg.get("con_id", 0)),
                        int(item.get("quantity", 0)),
                        float(item.get("entry_premium", 0.0)),
                        f"legacy:{legacy_id}",
                        str(item.get("opened_at", now)),
                        now,
                    ),
                )
                imported += 1
        if imported:
            self.set_meta("legacy_import_pending", {"count": imported, "path": str(path), "at": now})
        return imported
