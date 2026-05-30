from __future__ import annotations

import json
from typing import Any


class ToolObservationCompressor:
    def compress(self, content: str) -> Any:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return content
        return self._compress_payload(payload)

    def _compress_payload(self, value: Any) -> Any:
        if isinstance(value, list):
            return [self._compress_payload(item) for item in value]
        if not isinstance(value, dict):
            return value

        result = {key: self._compress_payload(item) for key, item in value.items()}
        result.pop("matches", None)
        sections = result.get("sections")
        if isinstance(sections, list):
            result["sections"] = [self._compress_payload(section) for section in sections]
        return result
