from __future__ import annotations

import argparse
import json
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from code_diver.cli import (
    config_for_search_hypothesis,
    direct_search_eval_result,
    direct_search_metrics,
    eval_result_to_json,
    inspection_exclude_patterns,
    make_embedding_provider,
    make_ephemeral_search_tool_handler,
    make_retrieval_strategy,
    make_rerank_tool_handler,
    search_tool_hypotheses,
)
from code_diver.config import ConfigLoader
from code_diver.domain import CodeItemIndexKindResolver
from code_diver.generation import create_generation_provider
from code_diver.inspection import FileOutlineService, RgService, SymbolsService
from code_diver.services import DatasetLoader
from code_diver.store import create_vector_store


@dataclass(slots=True)
class DeterministicRun:
    hypothesis: str
    scenario: str
    metrics: dict[str, Any]
    orchestrator_usage: dict[str, Any]
    results: list[dict[str, Any]]
    errors: list[str]
    tool_metrics: dict[str, Any]


class DeterministicPostrankH2:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.config = ConfigLoader().load(args.config)
        self.limit = int(args.limit)
        self.locator_limit = int(args.locator_limit)
        self.run_id = args.run_id or uuid.uuid4().hex[:12]

    def run(self) -> dict[str, Any]:
        cases = DatasetLoader().load(self.args.dataset)
        if self.args.cases > 0:
            cases = cases[: self.args.cases]
        rows = []
        for hypothesis in search_tool_hypotheses(self.config, self.args.hypothesis):
            scenario = self._scenario(hypothesis.name)
            if scenario not in {"branch_a", "branch_b"}:
                continue
            rows.append(self._run_hypothesis(hypothesis, scenario, cases))
        result = {
            "run_id": self.run_id,
            "benchmark": {
                "config": str(self.args.config),
                "dataset": str(self.args.dataset),
                "cases": len(cases),
                "limit": self.limit,
                "locator_limit": self.locator_limit,
                "mode": "deterministic_postrank_h2",
            },
            "results": [self._run_to_json(row) for row in rows],
        }
        self.args.output.parent.mkdir(parents=True, exist_ok=True)
        self.args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        if self.args.report is not None:
            self._build_report()
        return result

    def _run_hypothesis(self, hypothesis: Any, scenario: str, cases: list[Any]) -> DeterministicRun:
        config = config_for_search_hypothesis(self.config, hypothesis)
        vector_store = create_vector_store(config)
        started = time.perf_counter()
        errors: list[str] = []
        degraded_case_ids: set[str] = set()
        durations_ms: list[float] = []
        eval_results = []
        usage = self._empty_usage()
        tool_metrics = {
            "locator_calls": 0,
            "outline_calls": 0,
            "symbol_calls": 0,
            "rg_calls": 0,
            "ephemeral_calls": 0,
            "rerank_calls": 0,
            "rerank_errors": 0,
            "rerank_error_attempts": 0,
            "rerank_error_cases": 0,
            "candidate_count_total": 0,
            "candidate_count_mean": 0.0,
            "ephemeral_build_ms_total": 0.0,
            "ephemeral_query_ms_total": 0.0,
            "temporary_vectors_total": 0,
        }
        try:
            provider = make_embedding_provider(config, vector_store.metadata())
            strategy = make_retrieval_strategy(config, provider, vector_store)
            generation_provider = create_generation_provider(config)
            rerank = make_rerank_tool_handler(config, generation_provider)
            ephemeral = make_ephemeral_search_tool_handler(config)
            outline = FileOutlineService(config.root, inspection_exclude_patterns(config), config.scanner.max_file_bytes)
            symbols = SymbolsService(config.root, inspection_exclude_patterns(config), config.scanner.max_file_bytes)
            rg = RgService(config.root, inspection_exclude_patterns(config), config.scanner.max_file_bytes)
            total_cases = len(cases)
            for case_index, case in enumerate(cases, start=1):
                if self._should_print_progress(case_index, total_cases):
                    print(
                        f"{hypothesis.name}: case {case_index}/{total_cases} "
                        f"(scenario={scenario}, degraded_cases={len(degraded_case_ids)})",
                        flush=True,
                    )
                case_started = time.perf_counter()
                try:
                    locator = self._locator_candidates(strategy, case.query, self.locator_limit)
                    tool_metrics["locator_calls"] += 1
                    if scenario == "branch_a":
                        candidates = self._branch_a_candidates(case.query, locator, outline, symbols, rg, tool_metrics)
                    else:
                        candidates = self._branch_b_candidates(case.query, locator, ephemeral, tool_metrics)
                    tool_metrics["candidate_count_total"] += len(candidates)
                    reranked, rerank_metrics, rerank_degraded = self._rerank(rerank, case.query, candidates, tool_metrics)
                    if rerank_degraded:
                        degraded_case_ids.add(str(case.id))
                    self._merge_usage(usage, rerank_metrics)
                    retrieved = [str(candidate.get("path") or "") for candidate in reranked if candidate.get("path")]
                    eval_results.append(direct_search_eval_result(case, retrieved, self.limit))
                except Exception as exc:
                    degraded_case_ids.add(str(case.id))
                    errors.append(f"{case.id}: {type(exc).__name__}: {exc}")
                    eval_results.append(direct_search_eval_result(case, [], self.limit))
                durations_ms.append((time.perf_counter() - case_started) * 1000)
                if self._should_print_progress(case_index, total_cases):
                    tool_metrics["candidate_count_mean"] = tool_metrics["candidate_count_total"] / max(case_index, 1)
                    self._write_partial(
                        hypothesis.name,
                        scenario,
                        case_index,
                        total_cases,
                        eval_results,
                        durations_ms,
                        usage,
                        tool_metrics,
                        errors,
                        degraded_case_ids,
                    )
        finally:
            close = getattr(vector_store, "close", None)
            if callable(close):
                close()
        if cases:
            tool_metrics["candidate_count_mean"] = tool_metrics["candidate_count_total"] / len(cases)
        metrics = direct_search_metrics(eval_results, durations_ms, self.limit)
        metrics["duration_ms"] = (time.perf_counter() - started) * 1000
        tool_metrics["rerank_error_cases"] = len(degraded_case_ids)
        metrics["degraded"] = bool(degraded_case_ids)
        metrics["degraded_cases"] = len(degraded_case_ids)
        return DeterministicRun(
            hypothesis=hypothesis.name,
            scenario=scenario,
            metrics=metrics,
            orchestrator_usage=usage,
            results=[eval_result_to_json(result) for result in eval_results],
            errors=errors[:20],
            tool_metrics=tool_metrics,
        )

    def _locator_candidates(self, strategy: Any, query: str, limit: int) -> list[dict[str, Any]]:
        resolver = CodeItemIndexKindResolver()
        return [
            {
                "id": result.item.id,
                "path": result.item.path,
                "title": result.item.title,
                "startLine": result.item.start_line,
                "endLine": result.item.end_line,
                "score": result.score,
                "indexKind": resolver.resolve(result.item),
                "source": "locator",
                "preview": self._preview(result.item.content, 420),
            }
            for result in strategy.search(query, limit)
        ]

    def _branch_a_candidates(
        self,
        query: str,
        locator: list[dict[str, Any]],
        outline: FileOutlineService,
        symbols: SymbolsService,
        rg: RgService,
        metrics: dict[str, Any],
    ) -> list[dict[str, Any]]:
        candidates = list(locator)
        terms = self._terms(query)
        pattern = "|".join(re.escape(term) for term in terms[:5])
        for candidate in locator[: self.args.probe_files]:
            path = str(candidate.get("path") or "")
            if not path:
                continue
            try:
                payload = outline.structured(path, symbol_limit=80, import_limit=30)
                metrics["outline_calls"] += 1
                candidates.extend(self._outline_candidates(payload))
            except Exception:
                pass
            try:
                payload = symbols.structured(path=path, limit=40, query=query)
                metrics["symbol_calls"] += 1
                candidates.extend(self._tool_candidates(payload, "symbols"))
            except Exception:
                pass
            if pattern:
                try:
                    payload = rg.structured(pattern, path=path, limit=20, include_text=False)
                    metrics["rg_calls"] += 1
                    candidates.extend(self._tool_candidates(payload, "rg"))
                except Exception:
                    pass
        return self._dedupe_candidates(candidates)[: self.args.rerank_candidate_limit]

    def _branch_b_candidates(
        self,
        query: str,
        locator: list[dict[str, Any]],
        ephemeral: Any,
        metrics: dict[str, Any],
    ) -> list[dict[str, Any]]:
        files = [str(candidate.get("path") or "") for candidate in locator if candidate.get("path")]
        payload = ephemeral(query, files[: self.locator_limit], self.args.ephemeral_limit, {"fileLimit": self.locator_limit})
        metrics["ephemeral_calls"] += 1
        deep_metrics = payload.get("metrics") or {}
        metrics["ephemeral_build_ms_total"] += float(deep_metrics.get("ephemeral_build_ms") or 0.0)
        metrics["ephemeral_query_ms_total"] += float(deep_metrics.get("ephemeral_query_ms") or 0.0)
        metrics["temporary_vectors_total"] += int(deep_metrics.get("temporary_vectors") or 0)
        deep = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
        for candidate in deep:
            if isinstance(candidate, dict):
                candidate["source"] = "ephemeral"
        return self._dedupe_candidates([*deep, *locator])[: self.args.rerank_candidate_limit]

    def _rerank(
        self,
        rerank: Any,
        query: str,
        candidates: list[dict[str, Any]],
        metrics: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
        cumulative = {
            "modelCalls": 0,
            "inputTokens": 0,
            "outputTokens": 0,
            "totalTokens": 0,
            "estimatedCost": 0.0,
            "models": [],
            "errors": 0,
            "attempts": 0,
        }
        last_ranked: list[dict[str, Any]] = candidates[: self.limit]
        degraded = False
        for attempt in range(1, max(int(self.args.rerank_attempts), 1) + 1):
            metrics["rerank_calls"] += 1
            cumulative["attempts"] = attempt
            try:
                result = rerank(
                    query,
                    candidates,
                    self.limit,
                    {
                        "mode": self.args.rerank_mode if attempt == 1 else "compact",
                        "candidateLimit": self.args.rerank_candidate_limit,
                    },
                )
                rerank_metrics = result.get("metrics") or {}
            except Exception as exc:
                rerank_metrics = {"errors": 1, "degraded": True, "error": str(exc)}
                result = {"candidates": []}
            self._merge_rerank_metrics(cumulative, rerank_metrics)
            ranked = result.get("candidates")
            if isinstance(ranked, list) and ranked:
                last_ranked = ranked[: self.limit]
            if not rerank_metrics.get("errors") and not rerank_metrics.get("degraded"):
                return last_ranked, cumulative, degraded
            degraded = True
            metrics["rerank_errors"] += 1
            metrics["rerank_error_attempts"] += 1
        return last_ranked, cumulative, degraded

    def _merge_rerank_metrics(self, target: dict[str, Any], source: dict[str, Any]) -> None:
        target["modelCalls"] += int(source.get("modelCalls") or source.get("model_calls") or 0)
        target["inputTokens"] += int(source.get("inputTokens") or source.get("input_tokens") or 0)
        target["outputTokens"] += int(source.get("outputTokens") or source.get("output_tokens") or 0)
        target["totalTokens"] += int(source.get("totalTokens") or source.get("total_tokens") or 0)
        target["estimatedCost"] += float(source.get("estimatedCost") or source.get("estimated_cost") or 0.0)
        target["errors"] += int(source.get("errors") or 0)
        target["degraded"] = bool(target["errors"])
        for model in source.get("models") or [source.get("model")]:
            if model and model not in target["models"]:
                target["models"].append(str(model))

    def _outline_candidates(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        rows = self._tool_candidates(payload, "outline")
        symbols = payload.get("symbols") if isinstance(payload.get("symbols"), list) else []
        preview = " ".join(str(symbol.get("signature") or symbol.get("name") or "") for symbol in symbols[:20] if isinstance(symbol, dict))
        for row in rows:
            row["preview"] = self._preview(preview, 420)
        return rows

    def _tool_candidates(self, payload: dict[str, Any], source: str) -> list[dict[str, Any]]:
        rows = payload.get("candidates")
        if not isinstance(rows, list):
            return []
        candidates: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            path = str(row.get("path") or "").strip()
            if not path:
                continue
            clone = dict(row)
            clone.setdefault("id", f"{path}:{clone.get('startLine') or ''}:{source}")
            clone.setdefault("title", path)
            clone.setdefault("score", clone.get("confidence") or 0.0)
            clone.setdefault("source", source)
            clone.setdefault("preview", " ".join(str(value) for value in clone.get("symbols") or clone.get("evidenceLines") or []))
            candidates.append(clone)
        return candidates

    def _dedupe_candidates(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        rows: list[dict[str, Any]] = []
        for candidate in candidates:
            path = str(candidate.get("path") or "").strip()
            if not path:
                continue
            key = str(candidate.get("id") or f"{path}:{candidate.get('startLine') or ''}")
            if key in seen:
                continue
            seen.add(key)
            rows.append(candidate)
        return rows

    def _terms(self, query: str) -> list[str]:
        return [term for term in re.split(r"[^A-Za-z0-9_]+", query.lower()) if len(term) >= 3]

    def _preview(self, text: str, limit: int) -> str:
        compact = " ".join(text.split())
        if len(compact) <= limit:
            return compact
        return compact[:limit].rstrip() + "..."

    def _scenario(self, name: str) -> str:
        lowered = name.lower()
        if "ephemeral" in lowered:
            return "branch_b"
        if "grep" in lowered or "read" in lowered:
            return "branch_a"
        return "unknown"

    def _should_print_progress(self, case_index: int, total_cases: int) -> bool:
        progress_every = int(self.args.progress_every)
        return case_index == 1 or case_index == total_cases or (progress_every > 0 and case_index % progress_every == 0)

    def _write_partial(
        self,
        hypothesis: str,
        scenario: str,
        case_index: int,
        total_cases: int,
        eval_results: list[Any],
        durations_ms: list[float],
        usage: dict[str, Any],
        tool_metrics: dict[str, Any],
        errors: list[str],
        degraded_case_ids: set[str],
    ) -> None:
        if self.args.partial_dir is None:
            return
        metrics = direct_search_metrics(eval_results, durations_ms, self.limit)
        metrics["degraded"] = bool(degraded_case_ids)
        metrics["degraded_cases"] = len(degraded_case_ids)
        payload = {
            "run_id": self.run_id,
            "hypothesis": hypothesis,
            "scenario": scenario,
            "completed_cases": case_index,
            "total_cases": total_cases,
            "metrics": metrics,
            "orchestrator_usage": usage,
            "tool_metrics": tool_metrics,
            "errors": errors[:20],
        }
        self.args.partial_dir.mkdir(parents=True, exist_ok=True)
        path = self.args.partial_dir / f"{hypothesis}.partial.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _empty_usage(self) -> dict[str, Any]:
        return {"model_calls": 0, "tool_calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "total_cost": 0.0, "models": []}

    def _merge_usage(self, target: dict[str, Any], metrics: dict[str, Any]) -> None:
        target["model_calls"] += int(metrics.get("modelCalls") or metrics.get("model_calls") or 0)
        target["tool_calls"] += 1
        target["input_tokens"] += int(metrics.get("inputTokens") or metrics.get("input_tokens") or 0)
        target["output_tokens"] += int(metrics.get("outputTokens") or metrics.get("output_tokens") or 0)
        target["total_tokens"] += int(metrics.get("totalTokens") or metrics.get("total_tokens") or 0)
        target["total_cost"] += float(metrics.get("estimatedCost") or metrics.get("estimated_cost") or 0.0)
        for model in metrics.get("models") or [metrics.get("model")]:
            if model and model not in target["models"]:
                target["models"].append(str(model))

    def _run_to_json(self, row: DeterministicRun) -> dict[str, Any]:
        return {
            "hypothesis": row.hypothesis,
            "scenario": row.scenario,
            "orchestrator": "deterministic_postrank_h2",
            "metrics": row.metrics,
            "orchestrator_usage": row.orchestrator_usage,
            "tool_metrics": row.tool_metrics,
            "errors": row.errors,
            "error_count": len(row.errors),
            "results": row.results if self.args.details else [],
        }

    def _build_report(self) -> None:
        import subprocess

        subprocess.run(
            [".venv/bin/python", "scripts/build_eval_report.py", str(self.args.output), "--output", str(self.args.report)],
            check=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic IntelliJ H2 post-ranking benchmark.")
    parser.add_argument("--config", type=Path, default=Path("configs/intellij-postrank-h2.yml"))
    parser.add_argument("--dataset", type=Path, default=Path("datasets/intellij_eval_1000.jsonl"))
    parser.add_argument("--cases", type=int, default=100)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--locator-limit", type=int, default=30)
    parser.add_argument("--probe-files", type=int, default=5)
    parser.add_argument("--ephemeral-limit", type=int, default=30)
    parser.add_argument("--rerank-candidate-limit", type=int, default=30)
    parser.add_argument("--rerank-attempts", type=int, default=2)
    parser.add_argument("--rerank-mode", default="file_first")
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument("--partial-dir", type=Path, default=Path(".code-diver/reports/partials"))
    parser.add_argument("--hypothesis", action="append", default=[])
    parser.add_argument("--details", action="store_true")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--output", type=Path, default=Path(".code-diver/reports/intellij-postrank-h2-deterministic-100.json"))
    parser.add_argument("--report", type=Path, default=Path(".code-diver/reports/intellij-postrank-h2-deterministic-100.html"))
    args = parser.parse_args()
    result = DeterministicPostrankH2(args).run()
    print(json.dumps({"run_id": result["run_id"], "output": str(args.output), "report": str(args.report)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
