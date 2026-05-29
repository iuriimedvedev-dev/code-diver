from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class DirectIndexingResult:
    exit_code: int
    indexed_items: int = 0
    tool_calls: int = 0
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost: float = 0.0
    models: list[str] = field(default_factory=list)
    error: str | None = None

    def to_usage_json(self) -> dict[str, Any]:
        return {
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "total_tokens": self.total_tokens,
            "input_cost": 0.0,
            "output_cost": 0.0,
            "cache_read_cost": 0.0,
            "cache_write_cost": 0.0,
            "total_cost": self.estimated_cost,
            "models": self.models,
        }
