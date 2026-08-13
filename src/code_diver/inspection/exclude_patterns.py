from __future__ import annotations

from ..config import AppConfig
from ..services.codebase_scanner import DEFAULT_EXCLUDES


def inspection_exclude_patterns(config: AppConfig) -> list[str]:
    return [*DEFAULT_EXCLUDES, *config.scanner.exclude]
