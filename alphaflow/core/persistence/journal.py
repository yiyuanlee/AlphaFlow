"""Append-only JSONL event journal."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def append_event(path: Path, event: str, **fields: Any) -> None:
    """Append one JSONL record with an ISO timestamp."""
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": datetime.now().isoformat(), "event": event, **fields}
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_events(path: Path) -> list[dict[str, Any]]:
    """Read all JSONL records from *path*."""
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events
