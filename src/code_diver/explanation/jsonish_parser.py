from __future__ import annotations

import json
import re
from typing import Any


class JsonishParser:
    def parse_object(self, text: str) -> dict[str, Any]:
        candidates = [text, self._strip_fence(text), self._extract_object(text)]
        last_error: Exception | None = None
        for candidate in candidates:
            if not candidate:
                continue
            for repaired in [candidate, self._repair_invalid_escapes(candidate)]:
                try:
                    parsed = json.loads(repaired)
                except json.JSONDecodeError as exc:
                    last_error = exc
                    continue
                if isinstance(parsed, dict):
                    return parsed
        if last_error is not None:
            raise last_error
        raise json.JSONDecodeError("No JSON object found", text, 0)

    def _strip_fence(self, text: str) -> str:
        stripped = text.strip()
        match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL | re.IGNORECASE)
        return match.group(1) if match else stripped

    def _extract_object(self, text: str) -> str:
        stripped = self._strip_fence(text)
        start = stripped.find("{")
        if start < 0:
            return stripped
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(stripped)):
            char = stripped[index]
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return stripped[start : index + 1]
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        return match.group(0) if match else stripped

    def _repair_invalid_escapes(self, text: str) -> str:
        return re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", text)
