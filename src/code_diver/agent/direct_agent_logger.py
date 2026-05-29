from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class DirectAgentLogger:
    def __init__(self, path: Path, include_prompts: bool = True):
        self.path = path
        self.include_prompts = include_prompts

    def write(self, event: str, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "payload": payload,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
