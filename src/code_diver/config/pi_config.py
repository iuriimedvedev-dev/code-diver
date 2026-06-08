from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..settings import Defaults
from .pi_repo_context_config import PiRepoContextConfig


@dataclass(slots=True)
class PiConfig:
    binary: str = Defaults.PI_BINARY
    launcher_args: list[str] = field(default_factory=lambda: list(Defaults.PI_LAUNCHER_ARGS))
    extension: Path = Defaults.PI_EXTENSION
    prompt_template: Path | None = Defaults.PI_PROMPT_TEMPLATE
    provider: str | None = Defaults.PI_PROVIDER
    model: str | None = Defaults.PI_MODEL
    fallback_models: list[str] = field(default_factory=list)
    timeout_seconds: int = Defaults.PI_TIMEOUT_SECONDS
    session_dir: Path = Defaults.PI_SESSION_DIR
    tools: list[str] = field(default_factory=list)
    toolsets: dict[str, list[str]] = field(default_factory=dict)
    extra_args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    repo_context: PiRepoContextConfig = field(default_factory=PiRepoContextConfig)
