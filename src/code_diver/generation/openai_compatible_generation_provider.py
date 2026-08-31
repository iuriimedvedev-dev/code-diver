from __future__ import annotations

import json
import os
from typing import Any, ClassVar

from ..settings import Defaults, EnvironmentVariable
from .generation_result import GenerationResult
from .openai_generation_provider import OpenAIGenerationProvider
from .served_model_identity import ServedModelIdentity


class OpenAICompatibleGenerationProvider(OpenAIGenerationProvider):
    # Keys the provider owns. `extra_body` used to be splatted over the payload with
    # `payload.update(...)`, so a stray `messages` or `temperature` in a config silently
    # replaced the prompt or the sampling setting with no warning anywhere.
    RESERVED_PAYLOAD_KEYS: ClassVar[frozenset[str]] = frozenset(
        {"model", "messages", "temperature", "stream", "response_format", "max_tokens"}
    )

    # Options that belong to the chat template, not the request body. A top-level
    # `enable_thinking: false` is accepted by every OpenAI-compatible server and applied
    # by none of them -- it has to be nested under `chat_template_kwargs`. Two Qwen3.5
    # configs carried the flat form, ran with thinking left on, spent their entire token
    # budget on reasoning traces, and returned empty answers about 10% of the time.
    CHAT_TEMPLATE_OPTIONS: ClassVar[frozenset[str]] = frozenset(
        {"enable_thinking", "thinking", "reasoning_effort", "add_generation_prompt"}
    )

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
        # Literal keys still win (local servers use api_key: local). When omitted, resolve
        # from the process env after EnvFileLoader has loaded `.env` — LITE_LLM_KEY for the
        # labs gateway, then OPENAI_API_KEY, then the local placeholder.
        resolved_api_key = api_key
        if resolved_api_key is None or str(resolved_api_key).strip() == "":
            resolved_api_key = (
                os.environ.get("LITE_LLM_KEY")
                or os.environ.get(EnvironmentVariable.OPENAI_API_KEY.value)
                or "local"
            )
        super().__init__(
            model=model,
            api_key=resolved_api_key,
            url=url or f"{Defaults.LOCAL_OPENAI_BASE_URL}/chat/completions",
            timeout_seconds=timeout_seconds,
            retry_attempts=retry_attempts,
            retry_base_delay_seconds=retry_base_delay_seconds,
            retry_max_delay_seconds=retry_max_delay_seconds,
        )
        self.name = "openai_compatible"
        self._response_format_supported: bool | str | dict[str, Any] = response_format
        self.max_tokens = max_tokens
        self.extra_body = self._validated_extra_body(extra_body)
        self.served_model_identity = ServedModelIdentity()
        self._served_model_verified = False

    def generate_json(self, prompt: str, *, schema: dict[str, Any] | None = None) -> str:
        return self.generate_json_result(prompt, schema=schema).text

    def generate_json_result(self, prompt: str, *, schema: dict[str, Any] | None = None) -> GenerationResult:
        payload = self._payload(prompt, response_format=self._response_format_supported, schema=schema)
        try:
            response = self.retry.run(lambda: self._post(payload))
        except RuntimeError as exc:
            if not self._response_format_supported or not self._is_response_format_error(str(exc)):
                raise
            self._response_format_supported = False
            payload = self._payload(prompt, response_format=False, schema=schema)
            response = self.retry.run(lambda: self._post(payload))
        self._verify_served_model(response)
        text = self._extract_chat_text(response)
        if not text:
            raise RuntimeError(self._empty_response_message(response))
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

    def _verify_served_model(self, response: dict[str, Any]) -> None:
        """Fail on the first response if the port is held by a different model.

        Checked once per provider: the server cannot swap models mid-run, and a per-call
        comparison would add nothing but noise.
        """
        if self._served_model_verified:
            return
        served = response.get("model")
        if not isinstance(served, str) or not served.strip():
            self._served_model_verified = True
            return
        if not self.served_model_identity.same_model(self.model, served):
            raise RuntimeError(self.served_model_identity.mismatch_message(self.model, served, self.url))
        self._served_model_verified = True

    def _validated_extra_body(self, extra_body: dict[str, Any] | None) -> dict[str, Any]:
        body = dict(extra_body or {})
        clobbered = sorted(self.RESERVED_PAYLOAD_KEYS & body.keys())
        if clobbered:
            raise ValueError(
                "generation.extra_body must not set request keys the provider owns: "
                f"{', '.join(clobbered)}. Use the dedicated generation settings instead "
                "(model, temperature, max_tokens, response_format)."
            )
        misplaced = sorted(self.CHAT_TEMPLATE_OPTIONS & body.keys())
        if misplaced:
            nested = ", ".join(f"{key}: <value>" for key in misplaced)
            raise ValueError(
                f"generation.extra_body sets chat-template options at the top level: {', '.join(misplaced)}. "
                "Servers accept and ignore them there, so the setting has no effect. Nest them instead:\n"
                f"  extra_body:\n    chat_template_kwargs:\n      {nested}"
            )
        return body

    def _payload(
        self,
        prompt: str,
        response_format: bool | str | dict[str, Any],
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = dict(self.extra_body)
        payload.update(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "Return JSON only."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
                "stream": False,
            }
        )
        formatted = self._response_format_payload(response_format, schema)
        if formatted is not None:
            payload["response_format"] = formatted
        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens
        return payload

    def _is_response_format_error(self, message: str) -> bool:
        normalized = message.lower()
        return "response_format" in normalized or "json_object" in normalized or "json_schema" in normalized

    def _response_format_payload(
        self,
        response_format: bool | str | dict[str, Any],
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if response_format is False or response_format is None:
            return None
        if isinstance(response_format, dict):
            return response_format
        if isinstance(response_format, str):
            normalized = response_format.strip().lower()
            if normalized in {"", "false", "none", "off"}:
                return None
            if normalized == "json_schema":
                return self._json_schema_payload(schema)
            if normalized == "json_object":
                return {"type": "json_object"}
            raise ValueError(f"Unsupported response_format: {response_format}")
        return {"type": "json_object"}

    def _json_schema_payload(self, schema: dict[str, Any] | None) -> dict[str, Any]:
        # Without a task schema this used to send `{"type": "object"}`, which `{}`
        # satisfies -- json_schema mode was on, enforcing nothing. Fall back to
        # json_object, which is at least honest about constraining only the outer type.
        if schema is None:
            return {"type": "json_object"}
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "code_diver_json",
                "schema": _without_local_keywords(schema),
                "strict": True,
            },
        }

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _empty_response_message(self, response: dict[str, Any]) -> str:
        choices = response.get("choices") or []
        message = choices[0].get("message") or {} if choices else {}
        reasoning = message.get("reasoning_content") or message.get("reasoning")
        finish_reason = choices[0].get("finish_reason") if choices else None
        if isinstance(reasoning, str) and reasoning.strip():
            return (
                f"{self.model} returned only a reasoning trace and no content "
                f"(finish_reason={finish_reason!r}). The model spent its whole token budget "
                "thinking. Disable thinking mode via "
                "extra_body.chat_template_kwargs.enable_thinking: false, or raise max_tokens."
            )
        return (
            "OpenAI-compatible server returned an empty response "
            f"(model={self.model}, finish_reason={finish_reason!r})."
        )

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
        # `reasoning_content` is deliberately NOT used as a fallback. Returning a thinking
        # trace as if it were the answer produced JSON parse failures attributed to the
        # model's answer quality, when the real cause was thinking mode left enabled.
        text = choices[0].get("text")
        if isinstance(text, str):
            return text
        return json.dumps(content) if content else ""


# Keywords this repo adds to its response schemas that are not JSON Schema. They exist for
# `JsonSchemaValidator`, which runs locally after parsing; sending them on the wire would hand
# a server a keyword it never agreed to. llama.cpp compiles the schema into a GBNF grammar and
# Vertex validates it, so an unknown keyword is at best ignored and at worst a hard rejection.
_LOCAL_ONLY_SCHEMA_KEYWORDS: frozenset[str] = frozenset({"allowEmpty"})


def _without_local_keywords(schema: Any) -> Any:
    """Deep-copy a response schema with this repo's local-only keywords removed."""
    if isinstance(schema, dict):
        return {
            key: _without_local_keywords(value)
            for key, value in schema.items()
            if key not in _LOCAL_ONLY_SCHEMA_KEYWORDS
        }
    if isinstance(schema, list):
        return [_without_local_keywords(item) for item in schema]
    return schema
