from __future__ import annotations

from ..orchestration.json_response import JsonResponse


class LlmRerankResponseParser:
    def parse_indices(self, response: str, candidate_count: int) -> list[int]:
        payload = JsonResponse().parse_object(response)
        raw_results = payload.get("results", [])
        if not isinstance(raw_results, list):
            return []
        indices: list[int] = []
        seen: set[int] = set()
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            index = self._parse_index(item.get("index"))
            if index is None or index < 1 or index > candidate_count or index in seen:
                continue
            indices.append(index)
            seen.add(index)
        return indices

    def _parse_index(self, value: object) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
