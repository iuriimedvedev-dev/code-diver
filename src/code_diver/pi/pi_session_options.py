from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PiSessionOptions:
    session_dir: Path | None = None
    resume: bool = False
    continue_session: bool = False
    session: str | None = None
    session_id: str | None = None
    name: str | None = None
