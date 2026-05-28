from __future__ import annotations

import pytest

from code_diver.domain import CodeItem, SearchResult
from code_diver.strategies import RecursiveRetrievalStrategy, RetrievalStrategy


pytestmark = pytest.mark.unit


class BranchingStrategy(RetrievalStrategy):
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, limit: int) -> list[SearchResult]:
        self.queries.append(query)
        if len(self.queries) == 1:
            return [SearchResult(CodeItem("seed", "service.py", "Service", "repository save user"), 1.0)]
        return [SearchResult(CodeItem("expanded", "repository.py", "Repository", "save user"), 0.7)]


def test_recursive_strategy_expands_queries_and_merges_scores() -> None:
    base = BranchingStrategy()
    strategy = RecursiveRetrievalStrategy(base, rounds=2, branch_limit=1, per_round_limit=1)

    results = strategy.search("register user", limit=5)

    assert len(base.queries) == 2
    assert [result.item.id for result in results] == ["seed", "expanded"]
