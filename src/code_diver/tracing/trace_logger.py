from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, ClassVar

from ..config.trace_config import TraceConfig


@dataclass(slots=True)
class TraceLogger:
    config: TraceConfig
    _artifact_locks: ClassVar[dict[Path, Lock]] = {}
    _artifact_locks_lock: ClassVar[Lock] = Lock()

    def write(self, event: str, payload: dict[str, Any]) -> None:
        if not self.config.enabled:
            return
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event": event,
            "payload": payload,
        }
        with self._write_lock():
            self.config.artifact.parent.mkdir(parents=True, exist_ok=True)
            with self.config.artifact.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def prompt_payload(self, prompt: str) -> dict[str, Any]:
        payload: dict[str, Any] = {"prompt_chars": len(prompt)}
        if self.config.include_prompts:
            payload["prompt"] = prompt
        return payload

    @classmethod
    def disabled(cls) -> TraceLogger:
        return cls(TraceConfig(enabled=False, artifact=Path("."), include_prompts=False))

    def _write_lock(self) -> Lock:
        try:
            path = self.config.artifact.resolve()
        except OSError:
            path = self.config.artifact.absolute()
        with self._artifact_locks_lock:
            lock = self._artifact_locks.get(path)
            if lock is None:
                lock = Lock()
                self._artifact_locks[path] = lock
            return lock
