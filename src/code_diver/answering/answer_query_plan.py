from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class AnswerQueryPlan:
    queries: list[str] = field(default_factory=list)
    rationale: str = ""
