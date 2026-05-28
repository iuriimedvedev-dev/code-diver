from __future__ import annotations

from dataclasses import dataclass, field

from ..settings import Defaults


@dataclass(slots=True)
class EditorConfig:
    command: str = Defaults.EDITOR_COMMAND
    args: list[str] = field(default_factory=lambda: list(Defaults.EDITOR_ARGS))
