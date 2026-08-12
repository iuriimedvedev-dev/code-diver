from __future__ import annotations

import json
import re

from ..orchestration.json_response import JsonResponse
from .llm_rerank_selection import LlmRerankSelection


class LlmRerankResponseParser:
    def parse_indices(self, response: str, candidate_count: int) -> list[int]:
        return [selection.index for selection in self.parse_selections(response, candidate_count)]

    def parse_selections(self, response: str, candidate_count: int) -> list[LlmRerankSelection]:
        try:
            payload = JsonResponse().parse_object(response)
        except ValueError:
            return self._parse_loose_selections(response, candidate_count)
        raw_results = payload.get("results", [])
        if not isinstance(raw_results, list):
            return []
        return self._selections_from_items(raw_results, candidate_count)

    def _selections_from_items(self, raw_results: list[object], candidate_count: int) -> list[LlmRerankSelection]:
        selections: list[LlmRerankSelection] = []
        seen: set[int] = set()
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            index = self._parse_index(item.get("index"))
            if index is None or index < 1 or index > candidate_count or index in seen:
                continue
            selections.append(
                LlmRerankSelection(
                    index=index,
                    confidence=self._parse_confidence(item.get("confidence")),
                    reason=self._parse_reason(item.get("reason")),
                )
            )
            seen.add(index)
        return selections

    def _parse_loose_selections(self, response: str, candidate_count: int) -> list[LlmRerankSelection]:
        stripped = response.strip()
        if len(stripped) > 2000:
            return []
        parsed_list = self._parse_json_list(stripped)
        if parsed_list is not None:
            return self._selections_from_loose_values(parsed_list, candidate_count)
        patterns = [
            r'(?i)\bindex\b\s*[:=]\s*["\']?(\d+)',
            r'(?i)\bcandidate\b\s*#?\s*["\']?(\d+)',
        ]
        for pattern in patterns:
            selections = self._dedupe(
                [int(match) for match in re.findall(pattern, stripped)],
                candidate_count,
            )
            if selections:
                return selections
        if re.fullmatch(r"[\s,\d\[\]\-]+", stripped):
            return self._dedupe([int(match) for match in re.findall(r"\d+", stripped)], candidate_count)
        return []

    def _parse_json_list(self, response: str) -> list[object] | None:
        start = response.find("[")
        if start < 0:
            return None
        try:
            parsed, _ = json.JSONDecoder().raw_decode(response[start:])
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, list) else None

    def _selections_from_loose_values(self, values: list[object], candidate_count: int) -> list[LlmRerankSelection]:
        raw_indices: list[int] = []
        for value in values:
            index = self._parse_index(value.get("index")) if isinstance(value, dict) else self._parse_index(value)
            if index is not None:
                raw_indices.append(index)
        return self._dedupe(raw_indices, candidate_count)

    def _dedupe(self, values: list[int], candidate_count: int) -> list[LlmRerankSelection]:
        selections: list[LlmRerankSelection] = []
        seen: set[int] = set()
        for index in values:
            if index < 1 or index > candidate_count or index in seen:
                continue
            selections.append(LlmRerankSelection(index=index))
            seen.add(index)
        return selections

    def _parse_index(self, value: object) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _parse_confidence(self, value: object) -> float | None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return max(0.0, min(parsed, 1.0))

    def _parse_reason(self, value: object) -> str | None:
        if not isinstance(value, str):
            return None
        reason = value.strip()
        return reason or None
