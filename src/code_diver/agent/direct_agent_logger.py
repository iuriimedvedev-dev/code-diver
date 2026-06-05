from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any


class DirectAgentLogger:
    _artifact_locks: dict[Path, Lock] = {}
    _artifact_locks_lock: Lock = Lock()

    def __init__(self, path: Path, include_prompts: bool = True):
        self.path = path
        self.include_prompts = include_prompts

    def write(self, event: str, payload: dict[str, Any]) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "payload": payload,
        }
        with self._write_lock():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _write_lock(self) -> Lock:
        try:
            path = self.path.resolve()
        except OSError:
            path = self.path.absolute()
        with self._artifact_locks_lock:
            lock = self._artifact_locks.get(path)
            if lock is None:
                lock = Lock()
                self._artifact_locks[path] = lock
            return lock
