"""SQLite WAL state, idempotency records, heartbeat, HALT, and JSONL audit journal."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from alphaflow.scalping.types import (
    ACTIVE_STOCK_ORDER_STATES,
    BracketIntent,
    ScalpDirection,
    ScalpPosition,
    StockFillRecord,
    StockOrderRecord,
    StockOrderRole,
    utc_now_iso,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    order_ref TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL,
    parent_order_ref TEXT NOT NULL,
    role TEXT NOT NULL,
    action TEXT NOT NULL,
    symbol TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    order_type TEXT NOT NULL,
    limit_price REAL NOT NULL DEFAULT 0,
    stop_price REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    broker_order_id INTEGER NOT NULL DEFAULT 0,
    perm_id INTEGER NOT NULL DEFAULT 0,
    filled_quantity INTEGER NOT NULL DEFAULT 0,
    average_fill_price REAL NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_perm_id ON orders(perm_id) WHERE perm_id > 0;
CREATE INDEX IF NOT EXISTS idx_orders_intent ON orders(intent_id);
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
CREATE TABLE IF NOT EXISTS positions (
    intent_id TEXT PRIMARY KEY,
    direction TEXT NOT NULL,
    symbol TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    entry_price REAL NOT NULL,
    stop_price REAL NOT NULL,
    take_profit_price REAL NOT NULL,
    opened_at_utc TEXT NOT NULL,
    session_date TEXT NOT NULL,
    state TEXT NOT NULL,
    entry_perm_id INTEGER NOT NULL DEFAULT 0,
    stop_perm_id INTEGER NOT NULL DEFAULT 0,
    take_profit_perm_id INTEGER NOT NULL DEFAULT 0,
    closed_at_utc TEXT,
    exit_price REAL NOT NULL DEFAULT 0,
    realized_pnl REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
    session_date TEXT PRIMARY KEY,
    opening_nlv REAL NOT NULL DEFAULT 0,
    entries INTEGER NOT NULL DEFAULT 0,
    consecutive_losses INTEGER NOT NULL DEFAULT 0,
    realized_pnl REAL NOT NULL DEFAULT 0,
    daily_locked INTEGER NOT NULL DEFAULT 0,
    last_exit_at TEXT NOT NULL DEFAULT '',
    rearmed_long INTEGER NOT NULL DEFAULT 1,
    rearmed_short INTEGER NOT NULL DEFAULT 1,
    shadow_complete INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
    alert_key TEXT PRIMARY KEY,
    last_sent_at TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 1,
    message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    status TEXT NOT NULL,
    details TEXT NOT NULL
);
"""


class ScalpingStore:
    def __init__(self, database: Path, journal: Path | None = None) -> None:
        self.database = database
        self.journal = journal
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def set_metadata(self, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO metadata(key, value, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (key, value, utc_now_iso()),
            )

    def get_metadata(self, key: str, default: str = "") -> str:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def reserve_bracket(self, intent: BracketIntent) -> bool:
        """Atomically reserve all orderRefs before any broker-side submission."""
        action = "BUY" if intent.direction is ScalpDirection.LONG else "SELL"
        child_action = "SELL" if action == "BUY" else "BUY"
        records = (
            StockOrderRecord(
                intent.intent_id,
                intent.parent_order_ref,
                intent.parent_order_ref,
                StockOrderRole.ENTRY.value,
                action,
                intent.symbol,
                intent.quantity,
                "LMT",
                limit_price=intent.entry_limit,
            ),
            StockOrderRecord(
                intent.intent_id,
                intent.take_profit_order_ref,
                intent.parent_order_ref,
                StockOrderRole.TAKE_PROFIT.value,
                child_action,
                intent.symbol,
                intent.quantity,
                "LMT",
                limit_price=intent.take_profit_price,
            ),
            StockOrderRecord(
                intent.intent_id,
                intent.stop_order_ref,
                intent.parent_order_ref,
                StockOrderRole.STOP_LOSS.value,
                child_action,
                intent.symbol,
                intent.quantity,
                "STP",
                stop_price=intent.stop_price,
            ),
        )
        try:
            with self._connect() as connection:
                for record in records:
                    connection.execute(
                        """INSERT INTO orders(
                            order_ref,intent_id,parent_order_ref,role,action,symbol,quantity,order_type,
                            limit_price,stop_price,status,broker_order_id,perm_id,filled_quantity,
                            average_fill_price,last_error,created_at,updated_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        _order_values(record),
                    )
        except sqlite3.IntegrityError:
            return False
        self.journal_event("bracket_reserved", asdict(intent))
        return True

    def save_order(self, record: StockOrderRecord) -> None:
        record.updated_at = utc_now_iso()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO orders(
                    order_ref,intent_id,parent_order_ref,role,action,symbol,quantity,order_type,
                    limit_price,stop_price,status,broker_order_id,perm_id,filled_quantity,
                    average_fill_price,last_error,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(order_ref) DO UPDATE SET
                    status=excluded.status,broker_order_id=excluded.broker_order_id,
                    perm_id=excluded.perm_id,filled_quantity=excluded.filled_quantity,
                    average_fill_price=excluded.average_fill_price,last_error=excluded.last_error,
                    limit_price=excluded.limit_price,stop_price=excluded.stop_price,
                    updated_at=excluded.updated_at""",
                _order_values(record),
            )

    def create_order(self, record: StockOrderRecord) -> bool:
        """Reserve a single exit orderRef without overwriting an earlier attempt."""
        try:
            with self._connect() as connection:
                connection.execute(
                    """INSERT INTO orders(
                        order_ref,intent_id,parent_order_ref,role,action,symbol,quantity,order_type,
                        limit_price,stop_price,status,broker_order_id,perm_id,filled_quantity,
                        average_fill_price,last_error,created_at,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    _order_values(record),
                )
        except sqlite3.IntegrityError:
            return False
        self.journal_event("order_reserved", asdict(record))
        return True

    def update_order(
        self,
        order_ref: str,
        *,
        status: str,
        broker_order_id: int | None = None,
        perm_id: int | None = None,
        filled_quantity: int | None = None,
        average_fill_price: float | None = None,
        last_error: str | None = None,
    ) -> None:
        assignments = ["status=?", "updated_at=?"]
        values: list[Any] = [status, utc_now_iso()]
        for column, value in (
            ("broker_order_id", broker_order_id),
            ("perm_id", perm_id),
            ("filled_quantity", filled_quantity),
            ("average_fill_price", average_fill_price),
            ("last_error", last_error),
        ):
            if value is not None:
                assignments.append(f"{column}=?")
                values.append(value)
        values.append(order_ref)
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE orders SET {', '.join(assignments)} WHERE order_ref=?",
                values,
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown order_ref {order_ref}")

    def order(self, order_ref: str) -> StockOrderRecord | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM orders WHERE order_ref=?", (order_ref,)).fetchone()
        return _row_to_order(row) if row else None

    def order_by_perm_id(self, perm_id: int) -> StockOrderRecord | None:
        if perm_id <= 0:
            return None
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM orders WHERE perm_id=?", (perm_id,)).fetchone()
        return _row_to_order(row) if row else None

    def orders_for_intent(self, intent_id: str) -> list[StockOrderRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM orders WHERE intent_id=? ORDER BY created_at, order_ref", (intent_id,)
            ).fetchall()
        return [_row_to_order(row) for row in rows]

    def active_orders(self) -> list[StockOrderRecord]:
        placeholders = ",".join("?" for _ in ACTIVE_STOCK_ORDER_STATES)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM orders WHERE status IN ({placeholders}) ORDER BY created_at",
                sorted(ACTIVE_STOCK_ORDER_STATES),
            ).fetchall()
        return [_row_to_order(row) for row in rows]

    def recoverable_entries(self) -> list[StockOrderRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM orders
                   WHERE role=? AND filled_quantity>0
                   ORDER BY updated_at DESC""",
                (StockOrderRole.ENTRY.value,),
            ).fetchall()
        return [_row_to_order(row) for row in rows]

    def record_fill(self, fill: StockFillRecord) -> bool:
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT execution_id FROM fills WHERE execution_id=?", (fill.execution_id,)
            ).fetchone()
            connection.execute(
                """INSERT INTO fills(
                    execution_id,order_ref,perm_id,symbol,action,quantity,price,commission,occurred_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(execution_id) DO UPDATE SET
                    order_ref=excluded.order_ref,perm_id=excluded.perm_id,
                    commission=CASE WHEN excluded.commission != 0 THEN excluded.commission ELSE fills.commission END""",
                (
                    fill.execution_id,
                    fill.order_ref,
                    fill.perm_id,
                    fill.symbol,
                    fill.action,
                    fill.quantity,
                    fill.price,
                    fill.commission,
                    fill.occurred_at,
                ),
            )
        if existing:
            return False
        self.journal_event("fill", asdict(fill))
        return True

    def fills_for_refs(self, order_refs: set[str]) -> list[StockFillRecord]:
        if not order_refs:
            return []
        placeholders = ",".join("?" for _ in order_refs)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM fills WHERE order_ref IN ({placeholders}) ORDER BY occurred_at",
                sorted(order_refs),
            ).fetchall()
        return [
            StockFillRecord(
                execution_id=row["execution_id"],
                order_ref=row["order_ref"],
                perm_id=int(row["perm_id"]),
                symbol=row["symbol"],
                action=row["action"],
                quantity=int(row["quantity"]),
                price=float(row["price"]),
                commission=float(row["commission"]),
                occurred_at=row["occurred_at"],
            )
            for row in rows
        ]

    def save_position(self, position: ScalpPosition) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO positions(
                    intent_id,direction,symbol,quantity,entry_price,stop_price,take_profit_price,
                    opened_at_utc,session_date,state,entry_perm_id,stop_perm_id,take_profit_perm_id,
                    closed_at_utc,exit_price,realized_pnl
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(intent_id) DO UPDATE SET
                    quantity=excluded.quantity,entry_price=excluded.entry_price,
                    stop_price=excluded.stop_price,take_profit_price=excluded.take_profit_price,
                    state=excluded.state,entry_perm_id=excluded.entry_perm_id,
                    stop_perm_id=excluded.stop_perm_id,take_profit_perm_id=excluded.take_profit_perm_id,
                    closed_at_utc=excluded.closed_at_utc,exit_price=excluded.exit_price,
                    realized_pnl=excluded.realized_pnl""",
                (
                    position.intent_id,
                    position.direction.value,
                    position.symbol,
                    position.quantity,
                    position.entry_price,
                    position.stop_price,
                    position.take_profit_price,
                    position.opened_at_utc.isoformat(),
                    position.session_date.isoformat(),
                    position.state,
                    position.entry_perm_id,
                    position.stop_perm_id,
                    position.take_profit_perm_id,
                    position.closed_at_utc.isoformat() if position.closed_at_utc else None,
                    position.exit_price,
                    position.realized_pnl,
                ),
            )
        self.journal_event("position", asdict(position))

    def open_position(self) -> ScalpPosition | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM positions WHERE state IN ('OPEN','FLATTENING','RECONCILIATION_REQUIRED') "
                "ORDER BY opened_at_utc DESC LIMIT 1"
            ).fetchone()
        return _row_to_position(row) if row else None

    def session_state(self, session_date: date, opening_nlv: float = 0.0) -> dict[str, Any]:
        day = session_date.isoformat()
        now = utc_now_iso()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO sessions(session_date,opening_nlv,updated_at) VALUES (?,?,?)
                   ON CONFLICT(session_date) DO NOTHING""",
                (day, opening_nlv, now),
            )
            if opening_nlv > 0:
                connection.execute(
                    "UPDATE sessions SET opening_nlv=? WHERE session_date=? AND opening_nlv<=0",
                    (opening_nlv, day),
                )
            row = connection.execute("SELECT * FROM sessions WHERE session_date=?", (day,)).fetchone()
        assert row is not None
        return dict(row)

    def update_session(self, session_date: date, **fields: Any) -> None:
        allowed = {
            "opening_nlv",
            "entries",
            "consecutive_losses",
            "realized_pnl",
            "daily_locked",
            "last_exit_at",
            "rearmed_long",
            "rearmed_short",
            "shadow_complete",
        }
        invalid = set(fields) - allowed
        if invalid:
            raise ValueError(f"invalid session fields: {sorted(invalid)}")
        if not fields:
            return
        self.session_state(session_date)
        assignments = [f"{name}=?" for name in fields]
        values = list(fields.values())
        assignments.append("updated_at=?")
        values.extend((utc_now_iso(), session_date.isoformat()))
        with self._connect() as connection:
            connection.execute(
                f"UPDATE sessions SET {', '.join(assignments)} WHERE session_date=?",
                values,
            )

    def shadow_sessions(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM sessions WHERE shadow_complete=1").fetchone()
        return int(row["count"]) if row else 0

    def paper_sessions(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(DISTINCT session_date) AS count FROM positions WHERE state='CLOSED'"
            ).fetchone()
        return int(row["count"]) if row else 0

    def closed_cycles(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM positions WHERE state='CLOSED'").fetchone()
        return int(row["count"]) if row else 0

    def set_halt(self, reason: str, halt_file: Path) -> None:
        halt_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = halt_file.with_name(f"{halt_file.name}.tmp")
        temporary.write_text(reason.strip() or "unspecified", encoding="utf-8")
        os.replace(temporary, halt_file)
        self.set_metadata("halt_reason", reason.strip() or "unspecified")
        self.journal_event("halt", {"reason": reason})

    def clear_halt(self, halt_file: Path) -> None:
        halt_file.unlink(missing_ok=True)
        self.set_metadata("halt_reason", "")
        self.journal_event("resume", {})

    def halt_reason(self, halt_file: Path) -> str:
        if halt_file.exists():
            return halt_file.read_text(encoding="utf-8").strip() or "unspecified"
        return self.get_metadata("halt_reason")

    def heartbeat(self, heartbeat_file: Path, status: str, details: dict[str, Any] | None = None) -> None:
        timestamp = utc_now_iso()
        self.set_metadata("last_heartbeat", timestamp)
        self.set_metadata("last_cycle_status", status)
        payload = {"timestamp": timestamp, "status": status, "details": details or {}}
        heartbeat_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = heartbeat_file.with_name(f"{heartbeat_file.name}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, default=_json_default), encoding="utf-8")
        os.replace(temporary, heartbeat_file)

    def record_cycle(self, started_at: str, status: str, details: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO cycles(started_at,completed_at,status,details) VALUES (?,?,?,?)",
                (started_at, utc_now_iso(), status, json.dumps(details, default=_json_default)),
            )

    def alert_due(self, key: str, message: str, dedupe_seconds: int) -> bool:
        now = datetime.now(timezone.utc)
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM alerts WHERE alert_key=?", (key,)).fetchone()
            if row:
                last = datetime.fromisoformat(row["last_sent_at"]).astimezone(timezone.utc)
                if (now - last).total_seconds() < dedupe_seconds:
                    return False
                connection.execute(
                    "UPDATE alerts SET last_sent_at=?,count=count+1,message=? WHERE alert_key=?",
                    (now.isoformat(), message, key),
                )
            else:
                connection.execute(
                    "INSERT INTO alerts(alert_key,last_sent_at,count,message) VALUES (?,?,1,?)",
                    (key, now.isoformat(), message),
                )
        return True

    def release_alert(self, key: str) -> None:
        """Allow a failed delivery to be retried instead of deduping it as successful."""
        with self._connect() as connection:
            connection.execute("DELETE FROM alerts WHERE alert_key=?", (key,))

    def status_dict(self, halt_file: Path) -> dict[str, Any]:
        position = self.open_position()
        halt_reason = self.halt_reason(halt_file)
        return {
            "connected": self.get_metadata("connected", "false") == "true",
            "halted": bool(halt_reason),
            "halt_reason": halt_reason,
            "last_heartbeat": self.get_metadata("last_heartbeat"),
            "last_cycle_status": self.get_metadata("last_cycle_status"),
            "account_id": self.get_metadata("account_id"),
            "broker_quantity": int(self.get_metadata("broker_quantity", "0")),
            "protected": int(self.get_metadata("broker_quantity", "0")) == 0
            or self.get_metadata("protected", "false") == "true",
            "active_orders": len(self.active_orders()),
            "position": asdict(position) if position else None,
            "shadow_sessions": self.shadow_sessions(),
            "paper_sessions": self.paper_sessions(),
            "closed_cycles": self.closed_cycles(),
            "backtest_passed": self.get_metadata("backtest_passed", "false") == "true",
        }

    def journal_event(self, event: str, payload: dict[str, Any]) -> None:
        if self.journal is None:
            return
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        record = {"timestamp": utc_now_iso(), "event": event, "payload": payload}
        with self.journal.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=_json_default) + "\n")


def _order_values(record: StockOrderRecord) -> tuple[Any, ...]:
    return (
        record.order_ref,
        record.intent_id,
        record.parent_order_ref,
        record.role,
        record.action,
        record.symbol,
        record.quantity,
        record.order_type,
        record.limit_price,
        record.stop_price,
        record.status,
        record.broker_order_id,
        record.perm_id,
        record.filled_quantity,
        record.average_fill_price,
        record.last_error,
        record.created_at,
        record.updated_at,
    )


def _row_to_order(row: sqlite3.Row) -> StockOrderRecord:
    return StockOrderRecord(
        intent_id=row["intent_id"],
        order_ref=row["order_ref"],
        parent_order_ref=row["parent_order_ref"],
        role=row["role"],
        action=row["action"],
        symbol=row["symbol"],
        quantity=int(row["quantity"]),
        order_type=row["order_type"],
        limit_price=float(row["limit_price"]),
        stop_price=float(row["stop_price"]),
        status=row["status"],
        broker_order_id=int(row["broker_order_id"]),
        perm_id=int(row["perm_id"]),
        filled_quantity=int(row["filled_quantity"]),
        average_fill_price=float(row["average_fill_price"]),
        last_error=row["last_error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_position(row: sqlite3.Row) -> ScalpPosition:
    return ScalpPosition(
        intent_id=row["intent_id"],
        direction=ScalpDirection(row["direction"]),
        symbol=row["symbol"],
        quantity=int(row["quantity"]),
        entry_price=float(row["entry_price"]),
        stop_price=float(row["stop_price"]),
        take_profit_price=float(row["take_profit_price"]),
        opened_at_utc=datetime.fromisoformat(row["opened_at_utc"]),
        session_date=date.fromisoformat(row["session_date"]),
        state=row["state"],
        entry_perm_id=int(row["entry_perm_id"]),
        stop_perm_id=int(row["stop_perm_id"]),
        take_profit_perm_id=int(row["take_profit_perm_id"]),
        closed_at_utc=datetime.fromisoformat(row["closed_at_utc"]) if row["closed_at_utc"] else None,
        exit_price=float(row["exit_price"]),
        realized_pnl=float(row["realized_pnl"]),
    )


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, ScalpDirection):
        return value.value
    return str(value)
