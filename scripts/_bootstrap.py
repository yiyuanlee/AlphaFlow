"""Add AlphaFlow project root to sys.path for `python scripts/...` invocations."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def load_env_file(root: Path) -> None:
    """Load project .env into os.environ (does not override existing vars)."""
    env_path = root / '.env'
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def setup_path(caller_file: str) -> Path:
    start = Path(caller_file).resolve().parent
    for directory in (start, *start.parents):
        if (directory / 'config.yaml').is_file():
            load_env_file(directory)
            root = str(directory)
            if root not in sys.path:
                sys.path.insert(0, root)
            return directory
    raise RuntimeError('AlphaFlow project root not found (missing config.yaml)')
