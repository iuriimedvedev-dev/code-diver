from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..settings import Defaults


@dataclass(slots=True)
class PiConfig:
    binary: str = Defaults.PI_BINARY
    extension: Path = Defaults.PI_EXTENSION
    prompt_template: Path | None = Defaults.PI_PROMPT_TEMPLATE
    provider: str | None = Defaults.PI_PROVIDER
    model: str | None = Defaults.PI_MODEL
    tools: list[str] = field(default_factory=list)
    extra_args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
