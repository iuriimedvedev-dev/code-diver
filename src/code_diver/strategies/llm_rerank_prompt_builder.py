from __future__ import annotations

import json
from pathlib import Path

from ..config.llm_rerank_config import LlmRerankConfig
from ..domain import CodeItemIndexKindResolver, SearchResult


class LlmRerankPromptBuilder:
    def __init__(self, config: LlmRerankConfig):
        self.config = config
        self.kind_resolver = CodeItemIndexKindResolver()
        self.repository_context = self._repository_context(config.repository_context_path)

    def build(self, query: str, candidates: list[SearchResult], limit: int) -> str:
        prepared_candidates = [self._candidate(index, result) for index, result in enumerate(candidates, start=1)]
        payload = {
            "query": query,
            "limit": limit,
            "candidate_groups": {
                "code_candidates": [
                    candidate for candidate in prepared_candidates if candidate["path_role"] != "doc"
                ],
                "documentation_candidates": [
                    candidate for candidate in prepared_candidates if candidate["path_role"] == "doc"
                ],
            },
        }
        return f"""
You are reranking code search candidates for a repository-agnostic code RAG system.

Goal:
- Select the candidates that best answer the user's informal code-navigation query.
- Prefer exact behavioral relevance over vague semantic similarity.
- Use path, title, symbol kind, line range, retrieval score, and preview together.
- The input has two lanes: code candidates and documentation candidates.
- Use documentation candidates for repository orientation, concepts, setup commands, and terminology.
- Prefer code candidates for implementation-behavior answers unless the query explicitly asks for docs, setup,
  README, architecture notes, or user-facing documentation.
- Prefer implementation owner files over tests, examples, docs, benchmarks, and generated artifacts unless the query
  explicitly asks for those supporting files.
- Keep related tests/examples/docs only after the implementation owner when both are directly relevant.
- Do not invent files, paths, indices, or evidence.
{self._mode_instruction()}
{self._repository_context_instruction()}

Return JSON only:
{{
  "results": [
    {self._result_schema()}
  ]
}}

Rules:
- Use only candidate indices from either input lane.
- Return up to "limit" results, ordered by expected usefulness.
- Confidence is 0.0 to 1.0.
- If no candidate is clearly relevant, still return the best available candidates with low confidence.
{self._reason_rule()}

Input:
{json.dumps(payload, ensure_ascii=False)}
""".strip()

    def _candidate(self, index: int, result: SearchResult) -> dict[str, object]:
        item = result.item
        kind = self.kind_resolver.resolve(item)
        return {
            "index": index,
            "id": item.id,
            "path": item.path,
            "title": item.title,
            "start_line": item.start_line,
            "end_line": item.end_line,
            "kind": kind,
            "path_role": self._path_role(item.path, kind),
            "score": round(float(result.score), 6),
            "preview": self._preview(item.content),
        }

    def _path_role(self, path: str, kind: str = "") -> str:
        if kind.startswith("doc_"):
            return "doc"
        normalized = path.lower().replace("\\", "/")
        parts = [part for part in normalized.split("/") if part]
        name = parts[-1] if parts else normalized
        suffix = name.rsplit(".", 1)[-1] if "." in name else ""
        if suffix in {"md", "mdx", "rst", "txt", "adoc"} or "docs" in parts or name.startswith("readme"):
            return "doc"
        if any(part in {"test", "tests", "spec", "specs", "__tests__"} for part in parts):
            return "test"
        if any(part in {"example", "examples", "demo", "demos", "benchmark", "benchmarks"} for part in parts):
            return "example"
        if any(part in {"generated", "gen", "dist", "build", "target"} for part in parts):
            return "generated"
        return "implementation"

    def _preview(self, content: str) -> str:
        compact = " ".join(content.split())
        if len(compact) <= self.config.max_preview_chars:
            return compact
        return compact[: self.config.max_preview_chars].rstrip() + "..."

    def _mode_instruction(self) -> str:
        if self.config.mode == "file_first":
            return (
                "- Rank repository files first: choose the file that owns the behavior, then choose the best "
                "candidate within that file.\n"
                "- Prefer implementation files over broad model, __init__, wrapper, or summary files unless the "
                "query explicitly asks for models, exports, wrappers, summaries, tests, examples, docs, or benchmarks."
            )
        if self.config.mode == "base_rank_prior":
            return (
                "- Treat the input order and retrieval score as a strong prior.\n"
                "- Move a lower candidate above an earlier one only when path/title/preview evidence is clearly "
                "more specific to the query."
            )
        if self.config.mode == "precision":
            return (
                "- Optimize rank 1: the first result should be the single best file/symbol to open.\n"
                "- Prefer specific implementation owner files over adjacent tests, examples, docs, models, wrappers, "
                "registries, or summaries."
            )
        if self.config.mode == "compact":
            return "- Be terse and return only the ordered indices with confidence."
        return "- Balance exact file ownership, behavior evidence, and retrieval score."

    def _result_schema(self) -> str:
        if not self.config.include_reasons:
            return '{"index": 1, "confidence": 0.0}'
        return '{"index": 1, "confidence": 0.0, "reason": "short reason"}'

    def _reason_rule(self) -> str:
        if not self.config.include_reasons:
            return "- Do not include reasons or any fields other than index and confidence."
        return "- Reasons must be short and grounded in candidate fields."

    def _repository_context(self, path: Path | None) -> str:
        if path is None:
            return ""
        try:
            text = path.expanduser().read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return f"[Configured repository context was not found: {path}]"
        if len(text) <= self.config.repository_context_max_chars:
            return text
        marker = "\n\n[Repository context truncated by llm_rerank.repository_context_max_chars.]"
        limit = max(0, self.config.repository_context_max_chars - len(marker))
        return text[:limit].rstrip() + marker

    def _repository_context_instruction(self) -> str:
        if not self.repository_context:
            return ""
        return f"""

Repository context:
- Use this as orientation for terminology, package layout, and project-specific naming.
- Do not rank a candidate only because it matches this context; candidate path/title/preview evidence wins.
- If repository context conflicts with candidate evidence, trust candidate evidence.

{self.repository_context}
""".rstrip()
