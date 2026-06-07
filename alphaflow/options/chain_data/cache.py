"""Disk cache for option chain API responses."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any

from alphaflow.config import output_path


class ChainDataCache:
    def __init__(self, root: Path | None = None):
        self.root = root or output_path('options_chain_cache')
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, namespace: str, key: str) -> Path:
        safe = hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]
        folder = self.root / namespace
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f'{safe}.json'

    def get(self, namespace: str, key: str) -> Any | None:
        path = self._path(namespace, key)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding='utf-8'))

    def set(self, namespace: str, key: str, payload: Any) -> None:
        path = self._path(namespace, key)
        path.write_text(json.dumps(payload), encoding='utf-8')

    def has(self, namespace: str, key: str) -> bool:
        return self._path(namespace, key).exists()
