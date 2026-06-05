from __future__ import annotations

import json
from typing import Any

from ..settings import Defaults
from .generation_result import GenerationResult
from .openai_generation_provider import OpenAIGenerationProvider


class OpenAICompatibleGenerationProvider(OpenAIGenerationProvider):
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        url: str | None = None,
        timeout_seconds: float = Defaults.OPENAI_TIMEOUT_SECONDS,
        max_tokens: int | None = None,
        response_format: bool | str | dict[str, Any] = True,
        extra_body: dict[str, Any] | None = None,
        retry_attempts: int = Defaults.GENERATION_RETRY_ATTEMPTS,
        retry_base_delay_seconds: float = Defaults.GENERATION_RETRY_BASE_DELAY_SECONDS,
        retry_max_delay_seconds: float = Defaults.GENERATION_RETRY_MAX_DELAY_SECONDS,
    ):
        super().__init__(
            model=model,
            api_key=api_key or "local",
            url=url or f"{Defaults.LOCAL_OPENAI_BASE_URL}/chat/completions",
            timeout_seconds=timeout_seconds,
            retry_attempts=retry_attempts,
            retry_base_delay_seconds=retry_base_delay_seconds,
            retry_max_delay_seconds=retry_max_delay_seconds,
        )
        self.name = "openai_compatible"
        self._response_format_supported: bool | str | dict[str, Any] = response_format
        self.max_tokens = max_tokens
        self.extra_body = dict(extra_body or {})

    def generate_json(self, prompt: str) -> str:
        return self.generate_json_result(prompt).text

    def generate_json_result(self, prompt: str) -> GenerationResult:
        payload = self._payload(prompt, response_format=self._response_format_supported)
        try:
            response = self.retry.run(lambda: self._post(payload))
        except RuntimeError as exc:
            if not self._response_format_supported or not self._is_response_format_error(str(exc)):
                raise
            self._response_format_supported = False
            payload = self._payload(prompt, response_format=False)
            response = self.retry.run(lambda: self._post(payload))
        text = self._extract_chat_text(response)
        if not text:
            raise RuntimeError("OpenAI-compatible server returned an empty response.")
        usage = response.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or input_tokens + output_tokens)
        return GenerationResult(
            text=text,
            model=str(response.get("model") or self.model),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )

    def _payload(self, prompt: str, response_format: bool | str | dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "Return JSON only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "stream": False,
        }
        formatted = self._response_format_payload(response_format)
        if formatted is not None:
            payload["response_format"] = formatted
        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens
        payload.update(self.extra_body)
        return payload

    def _is_response_format_error(self, message: str) -> bool:
        normalized = message.lower()
        return "response_format" in normalized or "json_object" in normalized or "json_schema" in normalized

    def _response_format_payload(self, response_format: bool | str | dict[str, Any]) -> dict[str, Any] | None:
        if response_format is False or response_format is None:
            return None
        if isinstance(response_format, dict):
            return response_format
        if isinstance(response_format, str):
            normalized = response_format.strip().lower()
            if normalized in {"", "false", "none", "off"}:
                return None
            if normalized == "json_schema":
                return {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "code_diver_json",
                        "schema": {"type": "object"},
                    },
                }
            if normalized == "json_object":
                return {"type": "json_object"}
            raise ValueError(f"Unsupported response_format: {response_format}")
        return {"type": "json_object"}

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
        if isinstance(content, str) and content:
            return content
        if isinstance(content, list):
            return "".join(
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict) and part.get("type") in {"text", "output_text"}
            )
        reasoning = message.get("reasoning_content") or message.get("reasoning")
        if isinstance(reasoning, str):
            return reasoning
        text = choices[0].get("text")
        if isinstance(text, str):
            return text
        return json.dumps(content) if content else ""
