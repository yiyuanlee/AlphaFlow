"""Append-only paper-trade journal for hot-stock sleeve."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from alphaflow.config import output_path

DEFAULT_LOG = output_path('hot_paper_trades.jsonl')


def log_hot_event(event: str, log_file: Path | None = None, **fields: Any) -> None:
    path = log_file or DEFAULT_LOG
    record = {'ts': datetime.now().isoformat(), 'event': event, **fields}
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')


def load_hot_events(log_file: Path | None = None) -> list[dict[str, Any]]:
    path = log_file or DEFAULT_LOG
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events
