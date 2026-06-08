from __future__ import annotations

import json

from ..explanation.jsonish_parser import JsonishParser
from ..generation import GenerationProvider, GenerationResult
from .answer_case import AnswerCase
from .answer_query_plan import AnswerQueryPlan


class AnswerQueryPlanner:
    def __init__(
        self,
        provider: GenerationProvider,
        *,
        max_queries: int = 4,
        repository_context: str = "",
        parser: JsonishParser | None = None,
    ):
        self.provider = provider
        self.max_queries = max(1, int(max_queries or 1))
        self.repository_context = repository_context.strip()
        self.parser = parser or JsonishParser()

    def plan_result(self, case: AnswerCase) -> tuple[AnswerQueryPlan, GenerationResult]:
        result = self.provider.generate_json_result(self._prompt(case))
        return self._parse(result.text, case.question), result

    def _parse(self, text: str, original_query: str) -> AnswerQueryPlan:
        payload = self.parser.parse_object(text)
        raw_queries = payload.get("queries")
        queries: list[str] = []
        if isinstance(raw_queries, list):
            for item in raw_queries:
                if isinstance(item, dict):
                    value = item.get("query")
                else:
                    value = item
                query = str(value or "").strip()
                if query and query not in queries:
                    queries.append(query)
        if original_query not in queries:
            queries.insert(0, original_query)
        return AnswerQueryPlan(
            queries=queries[: self.max_queries],
            rationale=str(payload.get("rationale") or "").strip(),
        )

    def _prompt(self, case: AnswerCase) -> str:
        context_section = ""
        if self.repository_context:
            context_section = f"""
Repository orientation:
{self.repository_context}
"""
        return f"""Generate targeted code search queries for a repository code exploration agent.

The agent will run these queries against a hybrid code index. Your job is to
translate the user's informal question into several complementary search probes.

Rules:
- Return JSON only.
- Include the original user wording as one query unless it is empty.
- Generate at most {self.max_queries} queries total.
- Prefer behavior, API, class/function names, likely file names, and workflow terms.
- For multi-hop questions, split the workflow into component responsibilities.
- Do not invent repository-specific names unless they are implied by the question.

Return shape:
{{
  "queries": [
    {{"query": "exact or semantic search query", "purpose": "why this probe helps"}}
  ],
  "rationale": "short planning rationale"
}}

Question:
{case.question}

{context_section}
Case metadata:
{json.dumps(case.metadata, ensure_ascii=False)}
"""
