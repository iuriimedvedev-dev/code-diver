from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LlmRerankSelection:
    index: int
    confidence: float | None = None
    reason: str | None = None
