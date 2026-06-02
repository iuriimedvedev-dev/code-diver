from __future__ import annotations

import json
import urllib.request

from .rerank_provider import RerankProvider
from .rerank_score import RerankScore


class LlamaCppRerankProvider(RerankProvider):
    def __init__(self, model: str, url: str, api_key: str | None = None, timeout_ms: int = 20_000):
        self.name = "llama_cpp"
        self.model = model
        self.url = url
        self.api_key = api_key or "local"
        self.timeout_seconds = timeout_ms / 1000

    def rerank(self, query: str, documents: list[str], top_n: int) -> list[RerankScore]:
        payload = {
            "model": self.model,
            "query": query,
            "documents": documents,
            "top_n": top_n,
        }
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
        return self._parse_scores(data)

    def _parse_scores(self, data: dict) -> list[RerankScore]:
        raw_results = data.get("results")
        if raw_results is None:
            raw_results = data.get("data")
        if not isinstance(raw_results, list):
            raise ValueError("Rerank response must contain a results or data list.")
        scores: list[RerankScore] = []
        for result in raw_results:
            if not isinstance(result, dict):
                continue
            index = result.get("index")
            score = result.get("relevance_score", result.get("score"))
            if index is None or score is None:
                continue
            scores.append(RerankScore(index=int(index), score=float(score)))
        if not scores:
            raise ValueError("Rerank response did not contain scored indices.")
        scores.sort(key=lambda item: item.score, reverse=True)
        return scores
