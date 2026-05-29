from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..generation import GenerationProvider
from ..tracing import TraceLogger
from .json_response import JsonResponse


@dataclass(slots=True)
class QueryPlan:
    queries: list[str] = field(default_factory=list)


class QueryPlanOrchestrator:
    def __init__(self, generation_provider: GenerationProvider, trace_logger: TraceLogger | None = None):
        self.generation_provider = generation_provider
        self.trace_logger = trace_logger or TraceLogger.disabled()

    def plan(self, query: str, metadata: dict[str, Any]) -> QueryPlan:
        prompt = f"""
You orchestrate retrieval over an existing code index. You do not read source code contents.
Given the user query and index metadata, produce complementary search queries for code retrieval.

Return JSON only:
{{"queries": ["query variant 1", "query variant 2", "query variant 3"]}}

Rules:
- Keep variants concise.
- Preserve exact identifiers from the user query.
- Add likely code terms only when they are generic: service, repository, config, settings, command, route, model, schema, test.
- Mix semantic variants with identifier/path-like variants.
- Do not invent project-specific file names.
- Return 2-5 variants, ordered by expected precision.

User query: {query}
Index metadata: {metadata}
""".strip()
        self.trace_logger.write(
            "query_plan_prompt",
            {
                "provider": self.generation_provider.name,
                "model": self.generation_provider.model,
                "query": query,
                **self.trace_logger.prompt_payload(prompt),
            },
        )
        try:
            response = self.generation_provider.generate_json(prompt)
            self.trace_logger.write(
                "query_plan_response",
                {
                    "provider": self.generation_provider.name,
                    "model": self.generation_provider.model,
                    "query": query,
                    "response_chars": len(response),
                    "response": response,
                },
            )
            payload = JsonResponse().parse_object(response)
        except Exception as exc:
            self.trace_logger.write(
                "query_plan_error",
                {
                    "provider": self.generation_provider.name,
                    "model": self.generation_provider.model,
                    "query": query,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            return QueryPlan(queries=[query])
        queries = [str(item) for item in payload.get("queries", []) if str(item).strip()]
        plan = QueryPlan(queries=queries or [query])
        self.trace_logger.write("query_plan_selected", {"query": query, "queries": plan.queries})
        return plan
