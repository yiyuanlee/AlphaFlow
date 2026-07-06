"""Append-only journal for options paper trades."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alphaflow.config import output_path
from alphaflow.core.persistence.journal import append_event, load_events

DEFAULT_LOG = output_path("options_trades.jsonl")


def log_options_event(event: str, log_file: Path | None = None, **fields: Any) -> None:
    append_event(log_file or DEFAULT_LOG, event, **fields)


def load_options_events(log_file: Path | None = None) -> list[dict[str, Any]]:
    return load_events(log_file or DEFAULT_LOG)
