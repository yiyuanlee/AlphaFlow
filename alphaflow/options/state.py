"""Persist options positions and runtime state."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from alphaflow.config import state_path
from alphaflow.core.persistence.state import load_json, save_json


@dataclass
class StoredLeg:
    symbol: str
    expiry: str
    strike: float
    right: str
    action: str
    ratio: int = 1
    con_id: int = 0


@dataclass
class OptionsPosition:
    position_id: str
    strategy: str
    symbol: str
    quantity: int
    entry_premium: float
    limit_price: float
    max_loss: float
    expiry: str
    legs: list[StoredLeg] = field(default_factory=list)
    opened_at: str = ""
    status: str = "open"
    metadata: dict[str, Any] = field(default_factory=dict)


DEFAULT_STATE_FILE = state_path("options_positions.json")


def load_positions(path: Path | None = None) -> dict[str, OptionsPosition]:
    path = path or DEFAULT_STATE_FILE
    raw = load_json(path, default={})
    if not raw:
        return {}
    out: dict[str, OptionsPosition] = {}
    for pid, item in raw.get("positions", {}).items():
        legs = [StoredLeg(**leg) for leg in item.get("legs", [])]
        out[pid] = OptionsPosition(
            position_id=pid,
            strategy=item["strategy"],
            symbol=item["symbol"],
            quantity=int(item["quantity"]),
            entry_premium=float(item["entry_premium"]),
            limit_price=float(item.get("limit_price", item["entry_premium"])),
            max_loss=float(item["max_loss"]),
            expiry=item["expiry"],
            legs=legs,
            opened_at=item.get("opened_at", ""),
            status=item.get("status", "open"),
            metadata=item.get("metadata", {}),
        )
    return out


def save_positions(positions: dict[str, OptionsPosition], path: Path | None = None) -> None:
    path = path or DEFAULT_STATE_FILE
    payload = {
        "updated_at": datetime.now().isoformat(),
        "positions": {
            pid: {
                **{k: v for k, v in asdict(pos).items() if k != "legs"},
                "legs": [asdict(leg) for leg in pos.legs],
            }
            for pid, pos in positions.items()
            if pos.status == "open"
        },
    }
    save_json(path, payload)


def new_position_id(symbol: str, strategy: str) -> str:
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{symbol}_{strategy}_{ts}"
