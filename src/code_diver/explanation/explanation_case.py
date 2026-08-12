from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ExplanationCase:
    id: str
    code: str
    reference: str
    prompt: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, row: dict[str, Any]) -> ExplanationCase:
        return cls(
            id=str(row["id"]),
            code=str(row["code"]),
            reference=str(row["reference"]),
            prompt=str(row.get("prompt") or "Explain what this code does."),
            metadata=dict(row.get("metadata") or {}),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "code": self.code,
            "reference": self.reference,
            "prompt": self.prompt,
            "metadata": self.metadata,
        }
