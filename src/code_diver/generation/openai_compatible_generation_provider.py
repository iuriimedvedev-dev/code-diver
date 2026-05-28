from __future__ import annotations

import json
from typing import Any

from ..settings import Defaults
from .openai_generation_provider import OpenAIGenerationProvider


class OpenAICompatibleGenerationProvider(OpenAIGenerationProvider):
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        url: str | None = None,
        timeout_seconds: float = Defaults.OPENAI_TIMEOUT_SECONDS,
    ):
        super().__init__(
            model=model,
            api_key=api_key or "local",
            url=url or f"{Defaults.LOCAL_OPENAI_BASE_URL}/chat/completions",
            timeout_seconds=timeout_seconds,
        )
        self.name = "openai_compatible"

    def generate_json(self, prompt: str) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "Return JSON only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        response = self._post(payload)
        text = self._extract_chat_text(response)
        if not text:
            raise RuntimeError("OpenAI-compatible server returned an empty response.")
        return text

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _extract_chat_text(self, response: dict[str, Any]) -> str:
        choices = response.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content
        return json.dumps(content) if content else ""
