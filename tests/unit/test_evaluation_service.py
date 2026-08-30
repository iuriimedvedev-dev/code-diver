from __future__ import annotations

import json
from threading import Lock

import pytest

from code_diver.config.trace_config import TraceConfig
from code_diver.domain import CodeItem, EvalCase, SearchResult
from code_diver.services.evaluation_service import EvaluationService
from code_diver.strategies import RetrievalStrategy
from code_diver.tracing import TraceLogger

pytestmark = pytest.mark.unit


class StaticStrategy(RetrievalStrategy):
    def search(self, query: str, limit: int) -> list[SearchResult]:
        return [
            SearchResult(
                CodeItem(id="wrong#1", path="wrong.py", title="Wrong", content="", metadata={"index_kind": "chunk"}),
                0.9,
            ),
            SearchResult(
                CodeItem(
                    id="target.py#1",
                    path="target.py",
                    title="Target",
                    content="",
                    metadata={"index_kind": "file_summary"},
                ),
                0.8,
            ),
        ][:limit]


def test_evaluation_service_computes_ranked_metrics() -> None:
    metrics, results = EvaluationService(StaticStrategy()).evaluate(
        [EvalCase(id="case", query="find target", expected=["target.py"])],
        limit=2,
    )

    assert results[0].hit is True
    assert results[0].reciprocal_rank == 0.5
    assert results[0].precision == 0.5
    assert results[0].recall == 1.0
    assert metrics["hit_rate@2"] == 1.0
    assert metrics["hit_rate@2_ci95_low"] <= metrics["hit_rate@2"] <= metrics["hit_rate@2_ci95_high"]
    assert metrics["mrr@2_variance"] == 0.0
    assert metrics["search_duration_ms_mean_ci95_width"] >= 0.0
    assert metrics["mrr@2"] == 0.5
    assert metrics["hit_rate@1"] == 0.0
    assert metrics["hit_rate@3"] == 1.0
    assert metrics["hit_rate@5"] == 1.0
    assert metrics["file_hit_rate@1"] == 0.0
    assert metrics["file_hit_rate@3"] == 1.0
    assert metrics["file_hit_rate@5"] == 1.0
    assert metrics["file_hit_rate@2"] == 1.0
    assert metrics["file_mrr@2"] == 0.5
    assert metrics["file_precision@R"] == 0.0
    assert metrics["file_recall@2"] == 1.0
    assert metrics["ndcg@2"] == pytest.approx(0.6309297536)
    assert metrics["map@2"] == 0.5
    assert metrics["miss_rate@1"] == 1.0
    assert metrics["miss_rate@2"] == 0.0
    assert metrics["coverage_gap@2"] == 0.0
    assert metrics["file_coverage_gap@2"] == 0.0
    assert metrics["rerank_headroom@2"] == 1.0
    assert metrics["bundle_complete_rate@2"] == 1.0
    assert metrics["bundle_partial_rate@2"] == 0.0
    assert metrics["bundle_empty_rate@2"] == 0.0
    assert metrics["multi_expected_rate"] == 0.0
    assert metrics["expected_files_mean"] == 1.0
    assert metrics["retrieved_files_mean"] == 2.0
    assert metrics["unique_file_ratio@2"] == 1.0
    assert metrics["bucket.semantic.cases"] == 1
    assert metrics["bucket.semantic.hit_rate@5"] == 1.0
    assert metrics["bucket.semantic.file_hit_rate@3"] == 1.0
    assert metrics["bucket.semantic.file_hit_rate@2"] == 1.0
    assert metrics["top_result_kind.chunk.rate"] == 1.0
    assert metrics["first_relevant_kind.file_summary.rate"] == 1.0
    assert results[0].retrieved_files == ["wrong.py", "target.py"]
    assert results[0].bucket == "semantic"
    assert results[0].top_result_kind == "chunk"
    assert results[0].first_relevant_kind == "file_summary"
    assert results[0].file_reciprocal_rank == 0.5


class WinningKindStrategy(RetrievalStrategy):
    def search(self, query: str, limit: int) -> list[SearchResult]:
        return [
            SearchResult(
                CodeItem(
                    id="target.py#1",
                    path="target.py",
                    title="Target",
                    content="",
                    metadata={"index_kind": "file_summary", "winning_index_kind": "symbol_chunk"},
                ),
                0.9,
            )
        ][:limit]


def test_evaluation_service_prefers_winning_kind_for_diagnostics() -> None:
    metrics, results = EvaluationService(WinningKindStrategy()).evaluate(
        [EvalCase(id="case", query="find target", expected=["target.py"])],
        limit=1,
    )

    assert results[0].top_result_kind == "symbol_chunk"
    assert results[0].first_relevant_kind == "symbol_chunk"
    assert metrics["top_result_kind.symbol_chunk.rate"] == 1.0
    assert metrics["first_relevant_kind.symbol_chunk.rate"] == 1.0


def test_evaluation_service_uses_index_kind_for_legacy_results() -> None:
    metrics, results = EvaluationService(StaticStrategy()).evaluate(
        [EvalCase(id="case", query="find target", expected=["target.py"])],
        limit=2,
    )

    assert results[0].top_result_kind == "chunk"
    assert results[0].first_relevant_kind == "file_summary"
    assert metrics["top_result_kind.chunk.rate"] == 1.0
    assert metrics["first_relevant_kind.file_summary.rate"] == 1.0


class DuplicateFileStrategy(RetrievalStrategy):
    def search(self, query: str, limit: int) -> list[SearchResult]:
        return [
            SearchResult(CodeItem(id="target.py#1", path="target.py", title="Target 1", content=""), 0.9),
            SearchResult(CodeItem(id="target.py#2", path="target.py", title="Target 2", content=""), 0.8),
            SearchResult(CodeItem(id="other.py#1", path="other.py", title="Other", content=""), 0.7),
        ][:limit]


def test_evaluation_service_file_metrics_dedupe_retrieved_files() -> None:
    metrics, results = EvaluationService(DuplicateFileStrategy()).evaluate(
        [EvalCase(id="case", query="find target", expected=["target.py"])],
        limit=3,
    )

    assert metrics["precision@3"] == pytest.approx(2 / 3)
    assert metrics["file_precision@R"] == 1.0
    assert metrics["file_recall@3"] == 1.0
    assert metrics["ndcg@3"] == 1.0
    assert metrics["map@3"] == 1.0
    assert metrics["unique_file_ratio@3"] == pytest.approx(2 / 3)
    assert results[0].retrieved_files == ["target.py", "other.py"]


class MultiExpectedStrategy(RetrievalStrategy):
    def search(self, query: str, limit: int) -> list[SearchResult]:
        return [
            SearchResult(CodeItem(id="a.py#1", path="a.py", title="A", content=""), 0.9),
            SearchResult(CodeItem(id="wrong.py#1", path="wrong.py", title="Wrong", content=""), 0.8),
        ][:limit]


class DuplicateWrongFileStrategy(RetrievalStrategy):
    def search(self, query: str, limit: int) -> list[SearchResult]:
        return [
            SearchResult(CodeItem(id="wrong.py#1", path="wrong.py", title="Wrong 1", content=""), 0.9),
            SearchResult(CodeItem(id="wrong.py#2", path="wrong.py", title="Wrong 2", content=""), 0.8),
            SearchResult(CodeItem(id="wrong.py#3", path="wrong.py", title="Wrong 3", content=""), 0.7),
            SearchResult(CodeItem(id="target.py#1", path="target.py", title="Target", content=""), 0.6),
        ][:limit]


def test_evaluation_service_reports_file_hit_at_k_after_file_deduplication() -> None:
    metrics, _ = EvaluationService(DuplicateWrongFileStrategy()).evaluate(
        [EvalCase(id="case", query="find target", expected=["target.py"])],
        limit=4,
    )

    assert metrics["hit_rate@3"] == 0.0
    assert metrics["file_hit_rate@3"] == 1.0
    assert metrics["hit_rate@5"] == 1.0
    assert metrics["file_hit_rate@5"] == 1.0


def test_evaluation_service_reports_bundle_completion_metrics() -> None:
    metrics, _ = EvaluationService(MultiExpectedStrategy()).evaluate(
        [EvalCase(id="case", query="find workflow", expected=["a.py", "b.py"])],
        limit=2,
    )

    assert metrics["multi_expected_rate"] == 1.0
    assert metrics["expected_files_mean"] == 2.0
    assert metrics["file_recall@2"] == 0.5
    assert metrics["file_coverage_gap@2"] == 0.5
    assert metrics["bundle_complete_rate@2"] == 0.0
    assert metrics["bundle_partial_rate@2"] == 1.0
    assert metrics["bundle_empty_rate@2"] == 0.0


class SymbolIdStrategy(RetrievalStrategy):
    def search(self, query: str, limit: int) -> list[SearchResult]:
        return [
            SearchResult(
                CodeItem(id="target.py::TargetClass#abc", path="target.py", title="TargetClass", content=""),
                0.9,
            ),
        ][:limit]


def test_evaluation_service_hit_at_matches_symbol_ids_for_expected_file_paths() -> None:
    metrics, _ = EvaluationService(SymbolIdStrategy()).evaluate(
        [EvalCase(id="case", query="find target", expected=["target.py"])],
        limit=1,
    )

    assert metrics["hit_rate@1"] == 1.0


class PluginDescriptorStrategy(RetrievalStrategy):
    def search(self, query: str, limit: int) -> list[SearchResult]:
        return [
            SearchResult(
                CodeItem(
                    id="plugins/htmltools/resources/META-INF/plugin.xml",
                    path="plugins/htmltools/resources/META-INF/plugin.xml",
                    title="plugin.xml",
                    content="",
                ),
                0.9,
            ),
        ][:limit]


def test_evaluation_service_matches_glob_expected_file_patterns() -> None:
    metrics, results = EvaluationService(PluginDescriptorStrategy()).evaluate(
        [EvalCase(id="case", query="where is plugin descriptor", expected=["glob:**/resources/META-INF/plugin.xml"])],
        limit=1,
    )

    assert metrics["hit_rate@1"] == 1.0
    assert results[0].file_hit is True


class RecordingStrategy(RetrievalStrategy):
    def __init__(self) -> None:
        self.queries: list[str] = []
        self._lock = Lock()

    def search(self, query: str, limit: int) -> list[SearchResult]:
        with self._lock:
            self.queries.append(query)
        return [
            SearchResult(
                CodeItem(id=f"{query}.py#1", path=f"{query}.py", title=query, content=""),
                1.0,
            )
        ][:limit]


def test_evaluation_service_parallel_workers_preserve_case_order() -> None:
    strategy = RecordingStrategy()
    cases = [
        EvalCase(id="case-a", query="alpha", expected=["alpha.py"]),
        EvalCase(id="case-b", query="beta", expected=["beta.py"]),
        EvalCase(id="case-c", query="gamma", expected=["gamma.py"]),
    ]

    metrics, results = EvaluationService(strategy).evaluate(cases, limit=1, workers=3)

    assert metrics["evaluation_workers"] == 3
    assert [result.case_id for result in results] == ["case-a", "case-b", "case-c"]
    assert {result.query for result in results} == {"alpha", "beta", "gamma"}
    assert sorted(strategy.queries) == ["alpha", "beta", "gamma"]


def test_evaluation_service_traces_progress_with_parallel_workers(tmp_path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    strategy = RecordingStrategy()
    cases = [
        EvalCase(id="case-a", query="alpha", expected=["alpha.py"]),
        EvalCase(id="case-b", query="beta", expected=["beta.py"]),
        EvalCase(id="case-c", query="gamma", expected=["gamma.py"]),
    ]

    metrics, results = EvaluationService(
        strategy,
        trace_logger=TraceLogger(TraceConfig(enabled=True, artifact=trace_path, include_prompts=False)),
        progress_interval=1,
    ).evaluate(cases, limit=1, workers=3)

    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert [result.case_id for result in results] == ["case-a", "case-b", "case-c"]
    assert metrics["hit_rate@1"] == 1.0
    assert events[0]["event"] == "evaluation_started"
    assert events[-1]["event"] == "evaluation_completed"
    assert sum(1 for event in events if event["event"] == "evaluation_progress") == 3
    assert events[-2]["payload"]["completed"] == 3


def test_evaluation_service_reports_progress_callback_with_parallel_workers() -> None:
    calls: list[tuple[int, int]] = []
    cases = [
        EvalCase(id="case-a", query="alpha", expected=["alpha.py"]),
        EvalCase(id="case-b", query="beta", expected=["beta.py"]),
        EvalCase(id="case-c", query="gamma", expected=["gamma.py"]),
    ]

    EvaluationService(RecordingStrategy()).evaluate(
        cases,
        limit=1,
        workers=3,
        progress_callback=lambda completed, total: calls.append((completed, total)),
    )

    assert calls == [(1, 3), (2, 3), (3, 3)]


class FailingStrategy(RetrievalStrategy):
    def search(self, query: str, limit: int) -> list[SearchResult]:
        if query == "boom":
            raise RuntimeError("search exploded")
        return [
            SearchResult(
                CodeItem(id=f"{query}.py#1", path=f"{query}.py", title=query, content=""),
                1.0,
            )
        ][:limit]


def test_evaluation_service_records_degraded_cases_without_losing_parallel_results(tmp_path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    cases = [
        EvalCase(id="case-a", query="alpha", expected=["alpha.py"]),
        EvalCase(id="case-b", query="boom", expected=["boom.py"]),
        EvalCase(id="case-c", query="gamma", expected=["gamma.py"]),
    ]

    metrics, results = EvaluationService(
        FailingStrategy(),
        trace_logger=TraceLogger(TraceConfig(enabled=True, artifact=trace_path, include_prompts=False)),
        progress_interval=1,
    ).evaluate(cases, limit=1, workers=3)

    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert [result.case_id for result in results] == ["case-a", "case-b", "case-c"]
    assert [result.hit for result in results] == [True, False, True]
    assert metrics["cases"] == 3
    assert metrics["degraded"] is True
    assert metrics["degraded_cases"] == 1
    assert metrics["degraded_case_rate"] == pytest.approx(1 / 3)
    assert metrics["search_success_cases"] == 2
    assert metrics["search_failed_cases"] == 1
    assert metrics["search_failed_duration_ms_total"] >= 0.0
    assert metrics["failure_details"][0]["case_id"] == "case-b"
    assert metrics["failure_details"][0]["error_type"] == "RuntimeError"
    assert metrics["hit_rate@1"] == pytest.approx(2 / 3)
    assert any(event["event"] == "evaluation_case_failed" for event in events)
    assert events[-1]["event"] == "evaluation_completed"
    assert events[-1]["payload"]["degraded"] is True
    assert events[-1]["payload"]["degraded_cases"] == 1


def test_evaluation_service_successful_run_reports_not_degraded() -> None:
    metrics, _ = EvaluationService(RecordingStrategy()).evaluate(
        [EvalCase(id="case-a", query="alpha", expected=["alpha.py"])],
        limit=1,
        workers=1,
    )

    assert metrics["degraded"] is False
    assert metrics["degraded_cases"] == 0
    assert metrics["degraded_case_rate"] == 0.0
    assert metrics["search_success_cases"] == 1
    assert metrics["search_failed_cases"] == 0
    assert metrics["failure_details"] == []
