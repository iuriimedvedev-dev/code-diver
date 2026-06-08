from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..settings import Defaults


@dataclass(slots=True)
class PiRepoContextConfig:
    enabled: bool = Defaults.PI_REPO_CONTEXT_ENABLED
    mode: str = Defaults.PI_REPO_CONTEXT_MODE
    output: Path = Defaults.PI_REPO_CONTEXT_OUTPUT
    include_docs: bool = Defaults.PI_REPO_CONTEXT_INCLUDE_DOCS
    max_chars: int = Defaults.PI_REPO_CONTEXT_MAX_CHARS
    docs_limit: int = Defaults.PI_REPO_CONTEXT_DOCS_LIMIT
