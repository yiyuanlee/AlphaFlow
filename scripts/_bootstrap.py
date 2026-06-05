"""Add AlphaFlow project root to sys.path for `python scripts/...` invocations."""

from __future__ import annotations

import sys
from pathlib import Path


def setup_path(caller_file: str) -> Path:
    start = Path(caller_file).resolve().parent
    for directory in (start, *start.parents):
        if (directory / 'config.yaml').is_file():
            root = str(directory)
            if root not in sys.path:
                sys.path.insert(0, root)
            return directory
    raise RuntimeError('AlphaFlow project root not found (missing config.yaml)')
