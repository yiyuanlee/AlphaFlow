"""Tests for core.persistence (JSON state + JSONL journal)."""

from __future__ import annotations

import json
from pathlib import Path

from alphaflow.core.persistence.journal import append_event, load_events
from alphaflow.core.persistence.state import load_json, save_json, save_json_atomic


def test_save_and_load_json_atomic(tmp_path: Path):
    path = tmp_path / "state.json"
    save_json_atomic(path, {"a": 1, "b": [2, 3]})
    loaded = load_json(path)
    assert loaded == {"a": 1, "b": [2, 3]}
    assert not path.with_suffix(".json.tmp").exists()


def test_load_json_default(tmp_path: Path):
    assert load_json(tmp_path / "missing.json", default={"x": 0}) == {"x": 0}


def test_append_and_load_events(tmp_path: Path):
    log_path = tmp_path / "events.jsonl"
    append_event(log_path, "open", symbol="QQQ")
    append_event(log_path, "close", symbol="QQQ", pnl=100.0)
    events = load_events(log_path)
    assert len(events) == 2
    assert events[0]["event"] == "open"
    assert events[1]["pnl"] == 100.0


def test_load_events_missing_file(tmp_path: Path):
    assert load_events(tmp_path / "nope.jsonl") == []


def test_save_json_non_atomic(tmp_path: Path):
    path = tmp_path / "plain.json"
    save_json(path, {"k": "v"}, atomic=False)
    assert json.loads(path.read_text(encoding="utf-8")) == {"k": "v"}
