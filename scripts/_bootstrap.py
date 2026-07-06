"""Add AlphaFlow project root to sys.path for `python scripts/...` invocations."""

from __future__ import annotations

from pathlib import Path

from alphaflow.core.config import setup_project


def setup_path(caller_file: str) -> Path:
    """Legacy bootstrap — prefer ``pip install -e .`` and the ``alphaflow`` CLI."""
    return setup_project(caller_file)
