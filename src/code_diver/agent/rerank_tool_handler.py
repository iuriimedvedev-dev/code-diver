from __future__ import annotations

import json
from dataclasses import replace
from time import perf_counter
from typing import Any

from ..config.llm_rerank_config import LlmRerankConfig
from ..generation import RERANK_SCHEMA, GenerationProvider
from ..orchestration.json_response import JsonResponse
from .model_cost_estimator import ModelCostEstimator


class RerankToolHandler:
    def __init__(self, generation_provider: GenerationProvider, config: LlmRerankConfig):
        self.generation_provider = generation_provider
        self.config = config
        self.response_parser = JsonResponse()
        self.cost_estimator = ModelCostEstimator()

    def rerank(self, query: str, candidates: list[dict[str, Any]], limit: int, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        config = self._config(args)
        normalized = self._normalized_candidates(candidates, max(limit, config.candidate_limit), config)
        if not normalized:
            return {"candidates": [], "metrics": {"candidateCount": 0, "returnedCount": 0}}

        prompt = self._prompt(query, normalized, limit, config)
        started = perf_counter()
        response = self.generation_provider.generate_json_result(prompt, schema=RERANK_SCHEMA)
        duration_ms = (perf_counter() - started) * 1000
        parse_error: str | None = None
        try:
            parsed = self.response_parser.parse_object(response.text)
        except ValueError as exc:
            parsed = {}
            parse_error = str(exc)
        selected = self._selected(parsed.get("results"), len(normalized))
        ranked = self._ranked_candidates(normalized, selected, limit)
        cost = self.cost_estimator.estimate(response.model, response.input_tokens, response.output_tokens)
        metrics = {
            "candidateCount": len(normalized),
            "returnedCount": len(ranked),
            "modelCalls": 1,
            "model": response.model,
            "models": [response.model],
            "inputTokens": response.input_tokens,
            "outputTokens": response.output_tokens,
            "totalTokens": response.total_tokens,
            "estimatedCost": cost,
            "durationMs": duration_ms,
            "mode": config.mode,
        }
        if parse_error:
            metrics["errors"] = 1
            metrics["degraded"] = True
            metrics["error"] = parse_error
        return {
            "candidates": ranked,
            "selectedIndices": [item["index"] for item in selected],
            "degraded": bool(parse_error),
            "fallback": "input_order" if parse_error else None,
            "metrics": metrics,
        }

    def _config(self, args: dict[str, Any]) -> LlmRerankConfig:
        config = self.config
        if args.get("mode"):
            config = replace(config, mode=str(args["mode"]))
        if "includeReasons" in args or "include_reasons" in args:
            config = replace(config, include_reasons=bool(args.get("includeReasons", args.get("include_reasons"))))
        if args.get("maxPreviewChars") or args.get("max_preview_chars"):
            config = replace(config, max_preview_chars=int(args.get("maxPreviewChars") or args.get("max_preview_chars")))
        if args.get("candidateLimit") or args.get("candidate_limit"):
            config = replace(config, candidate_limit=int(args.get("candidateLimit") or args.get("candidate_limit")))
        return config

    def _normalized_candidates(
        self,
        candidates: list[dict[str, Any]],
        candidate_limit: int,
        config: LlmRerankConfig,
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in candidates:
            if not isinstance(raw, dict):
                continue
            path = str(raw.get("path") or "").strip()
            if not path:
                continue
            key = str(raw.get("id") or f"{path}:{raw.get('startLine') or raw.get('start_line') or ''}")
            if key in seen:
                continue
            seen.add(key)
            normalized.append(
                {
                    "index": len(normalized) + 1,
                    "id": key,
                    "path": path,
                    "title": str(raw.get("title") or path),
                    "start_line": raw.get("startLine", raw.get("start_line")),
                    "end_line": raw.get("endLine", raw.get("end_line")),
                    "kind": str(raw.get("indexKind") or raw.get("kind") or "unknown"),
                    "path_role": str(raw.get("pathRole") or raw.get("path_role") or self._path_role(path)),
                    "score": self._float(raw.get("score")),
                    "source": str(raw.get("source") or raw.get("tool") or "candidate"),
                    "preview": self._preview(str(raw.get("preview") or raw.get("text") or ""), config.max_preview_chars),
                }
            )
            if len(normalized) >= candidate_limit:
                break
        return normalized

    def _prompt(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        limit: int,
        config: LlmRerankConfig,
    ) -> str:
        payload = {"query": query, "limit": limit, "candidates": candidates}
        return f"""
You are a code-search reranking tool inside a repository-agnostic search orchestrator.

Goal:
- Rank the provided structured candidates by usefulness for the user's code-navigation query.
- Prefer candidates that own the behavior, command, route, handler, model, strategy, or configuration being asked about.
- If the query asks about configuration, plugin descriptors, module content, messages, resources, package info, YAML, XML, or properties, prefer the exact config/resource file over nearby implementation code.
- If the query names or implies a class/symbol/file, treat exact path/title/symbol matches as strong evidence even if the file is generated, test data, or metadata.
- Prefer implementation owner files over tests, examples, docs, benchmarks, and generated artifacts unless the user explicitly asks for those supporting files.
- Tests/examples/docs can support evidence, but should not outrank the implementation owner for "where/how is this implemented?" queries.
- Use path, title, kind, line range, source tool, base score, and preview together.
- Do not invent paths, indices, or evidence.
{self._mode_instruction(config)}

Return JSON only:
{{
  "results": [
    {self._result_schema(config)}
  ]
}}

Rules:
- Use only candidate indices from the input.
- Return up to "limit" results, ordered by expected usefulness.
- Confidence is 0.0 to 1.0.
- If no candidate is clearly relevant, still return the best available candidates with low confidence.
{self._reason_rule(config)}

Input:
{json.dumps(payload, ensure_ascii=False)}
""".strip()

    def _mode_instruction(self, config: LlmRerankConfig) -> str:
        if config.mode == "file_first":
            return (
                "- Rank owning files first, then choose the best symbol/chunk inside the file.\n"
                "- Prefer implementation files over broad summaries, wrappers, tests, examples, docs, and benchmarks "
                "unless the query asks for them."
            )
        if config.mode == "base_rank_prior":
            return "- Treat input order and score as a strong prior; move candidates only with clearly better evidence."
        if config.mode == "precision":
            return "- Optimize rank 1: the first result should be the single best place to open."
        if config.mode == "compact":
            return "- Be terse and return only ordered indices with confidence."
        return "- Balance file ownership, exact anchors, behavior evidence, and retrieval score."

    def _result_schema(self, config: LlmRerankConfig) -> str:
        if config.include_reasons:
            return '{"index": 1, "confidence": 0.0, "reason": "short reason"}'
        return '{"index": 1, "confidence": 0.0}'

    def _reason_rule(self, config: LlmRerankConfig) -> str:
        if config.include_reasons:
            return "- Reasons must be short and grounded in candidate fields."
        return "- Do not include reasons or any fields other than index and confidence."

    def _selected(self, values: Any, candidate_count: int) -> list[dict[str, Any]]:
        if not isinstance(values, list):
            return []
        selected: list[dict[str, Any]] = []
        seen: set[int] = set()
        for value in values:
            if not isinstance(value, dict):
                continue
            index = self._int(value.get("index"))
            if index is None or index < 1 or index > candidate_count or index in seen:
                continue
            seen.add(index)
            selected.append(
                {
                    "index": index,
                    "confidence": self._float(value.get("confidence")),
                    "reason": str(value.get("reason") or "").strip(),
                }
            )
        return selected

    def _ranked_candidates(
        self,
        candidates: list[dict[str, Any]],
        selected: list[dict[str, Any]],
        limit: int,
    ) -> list[dict[str, Any]]:
        selected_by_index = {item["index"]: item for item in selected}
        ranked: list[dict[str, Any]] = []
        for rank, item in enumerate(selected, start=1):
            candidate = dict(candidates[item["index"] - 1])
            candidate["rerankRank"] = rank
            candidate["confidence"] = item["confidence"]
            if item["reason"]:
                candidate["rerankReason"] = item["reason"]
            ranked.append(candidate)
        for candidate in candidates:
            if candidate["index"] in selected_by_index:
                continue
            fallback = dict(candidate)
            fallback["rerankRank"] = len(ranked) + 1
            ranked.append(fallback)
            if len(ranked) >= limit:
                break
        return ranked[:limit]

    def _preview(self, text: str, max_chars: int) -> str:
        compact = " ".join(text.split())
        if len(compact) <= max_chars:
            return compact
        return compact[:max_chars].rstrip() + "..."

    def _path_role(self, path: str) -> str:
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

    def _int(self, value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _float(self, value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
