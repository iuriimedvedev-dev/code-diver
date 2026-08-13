from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock

import pytest

from code_diver.answering import AnswerCase, AnswerContextBuilder, AnswerEvaluator, AnswerQueryPlanner
from code_diver.answering import answer_service as answer_service_module
from code_diver.answering.answer_query_merge import merge_query_results
from code_diver.config import CrossEncoderRerankConfig, LlmRerankConfig
from code_diver.domain import CodeItem, SearchResult
from code_diver.generation import GenerationResult
from code_diver.strategies import CrossEncoderRerankRetrievalStrategy, LlmRerankRetrievalStrategy

pytestmark = pytest.mark.unit

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "replay_pool_recall.py"


def _load_replay_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("replay_pool_recall", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


replay = _load_replay_module()


class FakeGenerationProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, responses: list[str]):
        self.responses = list(responses)

    def generate_json_result(self, prompt: str, *, schema: dict | None = None) -> GenerationResult:
        return GenerationResult(
            text=self.responses.pop(0),
            model=self.model,
            input_tokens=1,
            output_tokens=1,
            total_tokens=2,
        )


class FakeRetrievalStrategy:
    def __init__(self, results_by_query: dict[str, list[SearchResult]]):
        self.results_by_query = results_by_query

    def search(self, query: str, limit: int) -> list[SearchResult]:
        return self.results_by_query.get(query, [])[:limit]


class NonRerankWrapperWithBaseStrategy:
    """Mimics `GraphFileRetrievalStrategy` / `HybridRetrievalStrategy`: wraps an inner
    strategy as `.base_strategy` and has a `.config.candidate_limit`, but is NOT a rerank
    stage. `unwrap_probe_strategy` must not peel through this -- see its docstring."""

    def __init__(self, base_strategy: Any, candidate_limit: int):
        self.base_strategy = base_strategy
        self.config = MagicMock(candidate_limit=candidate_limit)

    def search(self, query: str, limit: int) -> list[SearchResult]:
        raise AssertionError("not expected to be searched directly in this test")


def _result(path: str, score: float) -> SearchResult:
    return SearchResult(CodeItem(id=path, path=path, title=path, content="content"), score)


def test_micro_recall_at_k_is_micro_averaged_across_cases() -> None:
    records = [
        replay.CaseReplayRecord(
            case_id="a",
            expected_paths=("src/a.py", "src/b.py"),
            ranked_paths=("src/a.py", "src/x.py", "src/b.py"),
            ranked_ids=(),
            ranked_scores=(),
            probe_queries=("q",),
            wall_seconds=0.0,
        ),
        replay.CaseReplayRecord(
            case_id="b",
            expected_paths=("src/c.py",),
            ranked_paths=("src/z.py", "src/c.py"),
            ranked_ids=(),
            ranked_scores=(),
            probe_queries=("q",),
            wall_seconds=0.0,
        ),
    ]

    # k=1: only case a's src/a.py is within the top 1 of its own ranking -> 1 hit / 3 expected total.
    assert replay.micro_recall_at_k(records, 1) == pytest.approx(1 / 3)
    # k=2: case a still only has src/a.py within top 2; case b's src/c.py enters at rank 2 -> 2/3.
    assert replay.micro_recall_at_k(records, 2) == pytest.approx(2 / 3)
    # k=3: every expected path is now reachable -> 3/3.
    assert replay.micro_recall_at_k(records, 3) == pytest.approx(1.0)


def test_micro_recall_at_k_is_zero_when_no_expected_paths() -> None:
    records = [
        replay.CaseReplayRecord(
            case_id="a",
            expected_paths=(),
            ranked_paths=("src/a.py",),
            ranked_ids=(),
            ranked_scores=(),
            probe_queries=("q",),
            wall_seconds=0.0,
        )
    ]

    assert replay.micro_recall_at_k(records, 10) == 0.0


def test_bundle_complete_rate_requires_every_expected_path_within_k() -> None:
    records = [
        replay.CaseReplayRecord(
            case_id="complete",
            expected_paths=("src/a.py", "src/b.py"),
            ranked_paths=("src/a.py", "src/b.py", "src/c.py"),
            ranked_ids=(),
            ranked_scores=(),
            probe_queries=("q",),
            wall_seconds=0.0,
        ),
        replay.CaseReplayRecord(
            case_id="partial",
            expected_paths=("src/a.py", "src/z.py"),
            ranked_paths=("src/a.py", "src/b.py"),
            ranked_ids=(),
            ranked_scores=(),
            probe_queries=("q",),
            wall_seconds=0.0,
        ),
    ]

    assert replay.bundle_complete_rate(records, 2) == pytest.approx(0.5)
    assert replay.bundle_complete_rate(records, 1) == pytest.approx(0.0)


def test_extract_probe_queries_handles_plain_string_list() -> None:
    queries = replay.extract_probe_queries({"queries": ["find auth", "  find login  "]}, case_id="case-1")

    assert queries == ["find auth", "find login"]


def test_extract_probe_queries_handles_object_list() -> None:
    queries = replay.extract_probe_queries(
        {"queries": [{"query": "find auth"}, {"query": "find login"}]}, case_id="case-1"
    )

    assert queries == ["find auth", "find login"]


def test_extract_probe_queries_fails_loudly_on_unsupported_item_type() -> None:
    with pytest.raises(replay.ReplayPoolRecallError, match=r"unsupported query_plan\.queries item type"):
        replay.extract_probe_queries({"queries": [123]}, case_id="case-1")


def test_extract_probe_queries_fails_loudly_when_missing() -> None:
    with pytest.raises(replay.ReplayPoolRecallError, match="missing or not a non-empty list"):
        replay.extract_probe_queries({}, case_id="case-1")


def test_extract_probe_queries_fails_loudly_when_empty_after_filtering() -> None:
    with pytest.raises(replay.ReplayPoolRecallError, match="no usable query strings"):
        replay.extract_probe_queries({"queries": ["   ", ""]}, case_id="case-1")


def test_unwrap_probe_strategy_peels_llm_rerank_wrapper_and_reads_candidate_limit() -> None:
    inner = FakeRetrievalStrategy({})
    wrapped = LlmRerankRetrievalStrategy(inner, MagicMock(), LlmRerankConfig(candidate_limit=34))

    probe_strategy, candidate_limit = replay.unwrap_probe_strategy(wrapped)

    assert probe_strategy is inner
    assert candidate_limit == 34


def test_unwrap_probe_strategy_peels_cross_encoder_rerank_wrapper_and_reads_candidate_limit() -> None:
    inner = FakeRetrievalStrategy({})
    wrapped = CrossEncoderRerankRetrievalStrategy(inner, MagicMock(), CrossEncoderRerankConfig(candidate_limit=60))

    probe_strategy, candidate_limit = replay.unwrap_probe_strategy(wrapped)

    assert probe_strategy is inner
    assert candidate_limit == 60


def test_unwrap_probe_strategy_returns_unwrapped_strategy_unchanged() -> None:
    plain = FakeRetrievalStrategy({})

    probe_strategy, candidate_limit = replay.unwrap_probe_strategy(plain)

    assert probe_strategy is plain
    assert candidate_limit is None


def test_unwrap_probe_strategy_does_not_peel_through_non_rerank_base_strategy_attribute() -> None:
    """`GraphFileRetrievalStrategy` and `HybridRetrievalStrategy` also expose `.base_strategy`
    and `.config.candidate_limit`, but for an unrelated reason (their own hybrid candidate
    fan-out size, not a rerank cap). Duck-typing on the attribute alone would wrongly unwrap
    past a real rerank wrapper into this and report the wrong candidate_limit -- this is the
    regression this test guards against."""
    inner = FakeRetrievalStrategy({})
    non_rerank_wrapper = NonRerankWrapperWithBaseStrategy(inner, candidate_limit=360)

    probe_strategy, candidate_limit = replay.unwrap_probe_strategy(non_rerank_wrapper)

    assert probe_strategy is non_rerank_wrapper
    assert candidate_limit is None


def test_replay_case_merges_probe_results_with_the_shared_merge_helper() -> None:
    strategy = FakeRetrievalStrategy(
        {
            "find auth": [_result("src/auth.py", 0.9), _result("src/other.py", 0.1)],
            "find login": [_result("src/login.py", 0.8)],
        }
    )

    record = replay.replay_case(
        strategy,
        case_id="case-1",
        expected_paths=["src/auth.py", "src/login.py"],
        probe_queries=["find auth", "find login"],
        query_limit=10,
        query_workers=1,
    )

    expected_merge = merge_query_results(
        [strategy.search("find auth", 10), strategy.search("find login", 10)], 10
    )
    assert record.ranked_paths == tuple(result.item.path for result in expected_merge)
    assert record.expected_paths == ("src/auth.py", "src/login.py")


def test_case_detail_reports_found_ranks_and_missing_paths() -> None:
    record = replay.CaseReplayRecord(
        case_id="case-1",
        expected_paths=("src/auth.py", "src/missing.py"),
        ranked_paths=("src/other.py", "src/auth.py"),
        ranked_ids=("id-other", "id-auth"),
        ranked_scores=(0.4, 0.3),
        probe_queries=("find auth",),
        wall_seconds=0.5,
    )

    detail = replay.case_detail(record, candidate_limit=10)

    assert detail["found"] == {"src/auth.py": 2}
    assert detail["missing"] == ["src/missing.py"]
    assert detail["recall"] == pytest.approx(0.5)
    assert detail["bundle_complete"] is False
    assert detail["pool"] == [
        {"rank": 1, "path": "src/other.py", "id": "id-other", "score": 0.4},
        {"rank": 2, "path": "src/auth.py", "id": "id-auth", "score": 0.3},
    ]


def test_answer_evaluator_still_delegates_to_the_shared_merge_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guards against the answering pipeline and this script drifting apart: if a future
    refactor stops routing the probe-query merge through `merge_query_results`, this test fails
    even though the behavioral tests would not notice. Driven through `AnswerEvaluator` on
    purpose, so it also pins the evaluator -> `AnswerService` -> merge chain."""
    spy = MagicMock(side_effect=merge_query_results)
    monkeypatch.setattr(answer_service_module, "merge_query_results", spy)

    retrieval = FakeRetrievalStrategy(
        {
            "original question": [],
            "probe one": [_result("src/one.py", 0.5)],
            "probe two": [_result("src/two.py", 0.4)],
        }
    )
    planner_provider = FakeGenerationProvider(
        [json.dumps({"queries": [{"query": "probe one"}, {"query": "probe two"}], "rationale": "r"})]
    )
    answer_provider = FakeGenerationProvider([json.dumps({"answer": "", "citations": [], "confidence": 0.0})])
    case = AnswerCase(id="case-1", question="original question", reference="src/one.py handles it.")

    AnswerEvaluator(
        retrieval,
        answer_provider,
        AnswerContextBuilder(Path("/tmp"), max_files=1, lines_per_file=10),
        query_planner=AnswerQueryPlanner(planner_provider),
        limit=5,
    ).evaluate([case])

    assert spy.call_count == 1
