from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..generation import GenerationProvider
from .json_response import JsonResponse


@dataclass(slots=True)
class QueryPlan:
    queries: list[str] = field(default_factory=list)


class QueryPlanOrchestrator:
    def __init__(self, generation_provider: GenerationProvider):
        self.generation_provider = generation_provider

    def plan(self, query: str, metadata: dict[str, Any]) -> QueryPlan:
        prompt = f"""
You orchestrate retrieval over an existing code index. You do not read source code contents.
Given the user query and index metadata, produce alternate search queries.
Return JSON only:
{{"queries": ["query variant 1", "query variant 2"]}}
Keep variants concise and language-agnostic.

User query: {query}
Index metadata: {metadata}
""".strip()
        try:
            payload = JsonResponse().parse_object(self.generation_provider.generate_json(prompt))
        except Exception:
            return QueryPlan(queries=[query])
        queries = [str(item) for item in payload.get("queries", []) if str(item).strip()]
        return QueryPlan(queries=queries or [query])
