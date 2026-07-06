"""Atomic JSON state persistence."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")


def load_json(path: Path, default: T | None = None) -> Any | T:
    """Load JSON from *path*, returning *default* when missing or invalid."""
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def save_json_atomic(path: Path, data: Any, *, indent: int | None = 2) -> None:
    """Write JSON atomically via a temporary file and ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(data, indent=indent, ensure_ascii=False)
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def save_json(path: Path, data: Any, *, indent: int | None = 2, atomic: bool = True) -> None:
    """Persist JSON; uses atomic write by default."""
    if atomic:
        save_json_atomic(path, data, indent=indent)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=indent, ensure_ascii=False), encoding="utf-8")
