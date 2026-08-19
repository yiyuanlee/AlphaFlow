"""Single-process lock used by the Windows unattended runner."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import IO


class ProcessLock:
    def __init__(self, path: Path):
        self.path = path
        self.handle: IO[str] | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # The handle intentionally stays open for the lifetime of the lock.
        handle = open(self.path, "a+", encoding="utf-8")  # noqa: SIM115
        try:
            if sys.platform == "win32":
                import msvcrt

                handle.seek(0)
                if not handle.read(1):
                    handle.write("0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]
        except OSError as exc:
            handle.close()
            raise RuntimeError(f"another AlphaFlow V11 process holds {self.path}") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        self.handle = handle

    def release(self) -> None:
        if self.handle is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]
        finally:
            self.handle.close()
            self.handle = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()
