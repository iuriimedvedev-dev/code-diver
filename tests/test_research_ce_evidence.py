import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("research_ce_evidence", Path(__file__).parents[1] / "scripts/research_ce_evidence.py")
research = importlib.util.module_from_spec(spec)
spec.loader.exec_module(research)


def test_fragment_is_query_matched_source_not_head_proxy():
    source = "class Example {}\n" + "unrelated filler\n" * 100 + "void refreshVirtualFileSystem() {}\n"
    head, _ = research.document("Example.java", source, "virtual file system refresh")
    fragment, offset = research.document("Example.java", source, "virtual file system refresh", True)
    assert len(head) <= 850 and len(fragment) <= 850
    assert "refreshVirtualFileSystem" not in head
    assert "refreshVirtualFileSystem" in fragment
    assert offset > 0
    assert fragment.split("source:\n")[1] in source


def test_unmatched_query_and_short_source():
    assert research.document("A.java", "class A {}", "zzzz", True) == research.document("A.java", "class A {}", "zzzz")
    with pytest.raises(ValueError):
        research.document("A", "", "", budget=0)


def test_retry_floor_cap_zero_and_high_gold():
    assert research.retry_indices([0.3, 0.9]) == []
    assert research.retry_indices([0.9, 0.1, 0.2, 0.0], cap=2) == [1, 2]
    assert research.merge_scores([0.9, 0.1], [1], [0.8]) == [0.9, 0.8]
    assert research.merge_scores([0.9, 0.1], [1], [0.0]) == [0.9, 0.1]


def test_exact_metrics_ties_and_absent_gold():
    result = research.metrics(["a", "b"], [0.5, 0.5], ["b"])
    assert result["mrr10"] == 0.5
    assert result["hit1"] == 0
    assert research.metrics(["a"], [1], ["missing"])["hit10"] == 0
    assert research.metrics(["a"], [1], ["a", "glob:**"])["recall10"] == 1


def test_production_second_pass_failure_preserves_first_scores(monkeypatch):
    from code_diver.config.cross_encoder_rerank_config import CrossEncoderRerankConfig
    from code_diver.reranking import RerankScore
    from code_diver.strategies import cross_encoder_rerank_retrieval_strategy as module

    class FailingProvider:
        name = "deterministic_failure"
        model = "none"
        calls = 0

        def rerank(self, query, documents, limit):
            self.calls += 1
            raise RuntimeError("intentional offline provider failure")

    provider = FailingProvider()
    config = CrossEncoderRerankConfig(second_pass_enabled=True)
    strategy = module.CrossEncoderRerankRetrievalStrategy(None, provider, config)
    monkeypatch.setattr(module, "build_cross_encoder_document", lambda *args: "offline document")
    scores = [RerankScore(index=0, score=0.9), RerankScore(index=1, score=0.1)]
    assert strategy._with_second_pass("query", [None, None], scores) is scores
    assert provider.calls == 1
    assert strategy._with_second_pass("query", [None], scores[:1]) == scores[:1]
    assert provider.calls == 1