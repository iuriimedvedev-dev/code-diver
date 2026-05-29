from __future__ import annotations

import json
import re
from typing import Any


class JsonResponseParser:
    def parse(self, text: str) -> dict[str, Any]:
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            value = json.loads(self._extract_object(text))
        if not isinstance(value, dict):
            raise ValueError("Agent response must be a JSON object.")
        return value

    def _extract_object(self, text: str) -> str:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise ValueError("Agent response did not contain a JSON object.")
        return match.group(0)
