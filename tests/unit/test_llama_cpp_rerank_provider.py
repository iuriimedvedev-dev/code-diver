from __future__ import annotations

import pytest

from code_diver.reranking.llama_cpp_rerank_provider import LlamaCppRerankProvider

pytestmark = pytest.mark.unit


def test_llama_cpp_rerank_provider_parses_results_shape() -> None:
    provider = LlamaCppRerankProvider(model="reranker", url="http://localhost/v1/rerank")

    scores = provider._parse_scores(
        {
            "results": [
                {"index": 1, "relevance_score": 0.2},
                {"index": 0, "relevance_score": 0.9},
            ]
        }
    )

    assert [(score.index, score.score) for score in scores] == [(0, 0.9), (1, 0.2)]


def test_llama_cpp_rerank_provider_parses_data_shape() -> None:
    provider = LlamaCppRerankProvider(model="reranker", url="http://localhost/v1/rerank")

    scores = provider._parse_scores({"data": [{"index": "2", "score": "0.7"}]})

    assert [(score.index, score.score) for score in scores] == [(2, 0.7)]
