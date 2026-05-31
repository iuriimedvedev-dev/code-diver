from __future__ import annotations

import json

from ..domain import CodeItemIndexKindResolver, SearchResult


class LlmRerankPromptBuilder:
    def __init__(self, max_preview_chars: int = 700):
        self.max_preview_chars = max_preview_chars
        self.kind_resolver = CodeItemIndexKindResolver()

    def build(self, query: str, candidates: list[SearchResult], limit: int) -> str:
        payload = {
            "query": query,
            "limit": limit,
            "candidates": [self._candidate(index, result) for index, result in enumerate(candidates, start=1)],
        }
        return f"""
You are reranking code search candidates for a repository-agnostic code RAG system.

Goal:
- Select the candidates that best answer the user's informal code-navigation query.
- Prefer exact behavioral relevance over vague semantic similarity.
- Use path, title, symbol kind, line range, retrieval score, and preview together.
- Keep related implementation and test files when both are directly relevant.
- Do not invent files, paths, indices, or evidence.

Return JSON only:
{{
  "results": [
    {{"index": 1, "confidence": 0.0, "reason": "short reason"}}
  ]
}}

Rules:
- Use only candidate indices from the input.
- Return up to "limit" results, ordered by expected usefulness.
- Confidence is 0.0 to 1.0.
- If no candidate is clearly relevant, still return the best available candidates with low confidence.
- Reasons must be short and grounded in candidate fields.

Input:
{json.dumps(payload, ensure_ascii=False)}
""".strip()

    def _candidate(self, index: int, result: SearchResult) -> dict[str, object]:
        item = result.item
        return {
            "index": index,
            "id": item.id,
            "path": item.path,
            "title": item.title,
            "start_line": item.start_line,
            "end_line": item.end_line,
            "kind": self.kind_resolver.resolve(item),
            "score": round(float(result.score), 6),
            "preview": self._preview(item.content),
        }

    def _preview(self, content: str) -> str:
        compact = " ".join(content.split())
        if len(compact) <= self.max_preview_chars:
            return compact
        return compact[: self.max_preview_chars].rstrip() + "..."
