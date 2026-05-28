from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..settings import Defaults, EnvironmentVariable


class OpenAIGenerationProvider:
    def __init__(
        self,
        model: str = Defaults.OPENAI_GENERATION_MODEL,
        api_key: str | None = None,
        url: str = Defaults.OPENAI_RESPONSES_URL,
        timeout_seconds: float = Defaults.OPENAI_TIMEOUT_SECONDS,
    ):
        self.name = "openai"
        self.model = model
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.api_key = api_key or os.environ.get(EnvironmentVariable.OPENAI_API_KEY.value)
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAI generation.")

    def generate_json(self, prompt: str) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "input": prompt,
            "text": {
                "format": {"type": "json_object"},
            },
        }
        response = self._post(payload)
        text = response.get("output_text") or self._extract_text(response)
        if not text:
            raise RuntimeError("OpenAI returned an empty indexing response.")
        return str(text)

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers=self._headers(),
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI responses request failed: HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"OpenAI responses API is not reachable: {exc.reason}") from exc

    def _extract_text(self, response: dict[str, Any]) -> str:
        parts: list[str] = []
        for item in response.get("output", []):
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"}:
                    parts.append(str(content.get("text", "")))
        return "".join(parts)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
