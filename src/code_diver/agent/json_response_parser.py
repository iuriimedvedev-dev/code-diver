from __future__ import annotations

import json
from typing import Any


class JsonResponseParser:
    ACTION_KEYS = frozenset({"tool_calls", "index_items", "items", "results", "final"})

    def parse(self, text: str) -> dict[str, Any]:
        candidates = self._decode_candidates(text)
        for value in candidates:
            if isinstance(value, dict) and self.ACTION_KEYS.intersection(value):
                return value
        for value in candidates:
            if isinstance(value, dict):
                return value
        raise ValueError("Agent response did not contain a JSON object.")

    def _decode_candidates(self, text: str) -> list[Any]:
        try:
            return [json.loads(text)]
        except json.JSONDecodeError:
            pass

        decoder = json.JSONDecoder()
        candidates: list[Any] = []
        for index, char in enumerate(text):
            if char != "{":
                continue
            try:
                value, _ = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            candidates.append(value)
        return candidates
