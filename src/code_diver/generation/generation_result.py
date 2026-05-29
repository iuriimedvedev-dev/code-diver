from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class GenerationResult:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
