from __future__ import annotations

from types import SimpleNamespace

import pytest

from code_diver.generation import GeminiGenerationProvider, TransientGenerationRetry


pytestmark = pytest.mark.unit


class FakeGenerateContentConfig:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeThinkingConfig:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeModels:
    def __init__(self):
        self.calls: list[dict] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            raise RuntimeError(
                "400 INVALID_ARGUMENT. Unknown name \"responseMimeType\" at 'generation_config'. "
                "Unknown name \"thinkingConfig\" at 'generation_config'."
            )
        return SimpleNamespace(
            text='{"explanation": "ok"}',
            usage_metadata=SimpleNamespace(
                prompt_token_count=11,
                candidates_token_count=7,
                total_token_count=18,
            ),
        )


def test_gemini_generation_retries_without_unsupported_json_config() -> None:
    models = FakeModels()
    provider = GeminiGenerationProvider.__new__(GeminiGenerationProvider)
    provider.model = "gemini-test"
    provider.fallback_models = []
    provider.temperature = 0
    provider.thinking_budget = 128
    provider.retry = TransientGenerationRetry(attempts=1, sleep=lambda _: None)
    provider.client = SimpleNamespace(models=models)
    provider.types = SimpleNamespace(
        GenerateContentConfig=FakeGenerateContentConfig,
        ThinkingConfig=FakeThinkingConfig,
    )

    result = provider.generate_json_result("return json")

    assert result.text == '{"explanation": "ok"}'
    assert result.total_tokens == 18
    assert models.calls[0]["config"].kwargs["response_mime_type"] == "application/json"
    assert "thinking_config" in models.calls[0]["config"].kwargs
    assert models.calls[1]["config"].kwargs == {"temperature": 0}
