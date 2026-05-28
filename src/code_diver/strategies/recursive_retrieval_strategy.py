from __future__ import annotations

from collections import defaultdict

from ..domain import SearchResult
from ..services.tokenizer import tokenize
from .retrieval_strategy import RetrievalStrategy


class RecursiveRetrievalStrategy(RetrievalStrategy):
    def __init__(
        self,
        base_strategy: RetrievalStrategy,
        *,
        rounds: int = 2,
        branch_limit: int = 3,
        per_round_limit: int = 5,
    ):
        self.base_strategy = base_strategy
        self.rounds = rounds
        self.branch_limit = branch_limit
        self.per_round_limit = per_round_limit

    def search(self, query: str, limit: int) -> list[SearchResult]:
        scores: dict[str, float] = defaultdict(float)
        items: dict[str, object] = {}
        frontier = [query]
        seen_queries = {query}

        for round_index in range(max(self.rounds, 1)):
            next_queries: list[str] = []
            for current_query in frontier:
                for result in self.base_strategy.search(current_query, self.per_round_limit):
                    items[result.item.id] = result.item
                    scores[result.item.id] += result.score * (0.85**round_index)
                    for expanded in self._expand_query(query, result):
                        if expanded not in seen_queries:
                            seen_queries.add(expanded)
                            next_queries.append(expanded)
            frontier = next_queries[: self.branch_limit]
            if not frontier:
                break

        results = [SearchResult(item=item, score=score) for item_id, item in items.items() for score in [scores[item_id]]]
        results.sort(key=lambda result: result.score, reverse=True)
        return results[:limit]

    def _expand_query(self, original_query: str, result: SearchResult) -> list[str]:
        path_tokens = " ".join(tokenize(result.item.path)[-6:])
        title_tokens = " ".join(tokenize(result.item.title)[:8])
        content_tokens = " ".join(tokenize(result.item.content)[:20])
        return [
            f"{original_query} {path_tokens}".strip(),
            f"{original_query} {title_tokens}".strip(),
            f"{original_query} {content_tokens}".strip(),
        ][: self.branch_limit]
