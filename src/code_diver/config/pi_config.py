from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..settings import Defaults


@dataclass(slots=True)
class PiConfig:
    binary: str = Defaults.PI_BINARY
    launcher_args: list[str] = field(default_factory=list)
    extension: Path = Defaults.PI_EXTENSION
    prompt_template: Path | None = Defaults.PI_PROMPT_TEMPLATE
    provider: str | None = Defaults.PI_PROVIDER
    model: str | None = Defaults.PI_MODEL
    fallback_models: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    toolsets: dict[str, list[str]] = field(default_factory=dict)
    extra_args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
