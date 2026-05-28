from __future__ import annotations

import json
import re
from typing import Any


class JsonResponse:
    def parse_object(self, response: str) -> dict[str, Any]:
        candidate = self._candidate(response)
        start = candidate.find("{")
        if start < 0:
            raise ValueError("JSON response does not contain an object.")
        parsed, _ = json.JSONDecoder().raw_decode(candidate[start:])
        if not isinstance(parsed, dict):
            raise ValueError("JSON response must be an object.")
        return parsed

    def _candidate(self, response: str) -> str:
        stripped = response.strip()
        fenced = re.search(r"```(?:json)?\s*(.*?)```", stripped, flags=re.DOTALL)
        return fenced.group(1).strip() if fenced else stripped
