from __future__ import annotations

from enum import StrEnum


class EnvironmentVariable(StrEnum):
    CODE_DIVER_CONFIG = "CODE_DIVER_CONFIG"
    CODE_DIVER_ROOT = "CODE_DIVER_ROOT"
    EDITOR = "EDITOR"
    GEMINI_API_KEY = "GEMINI_API_KEY"
