from __future__ import annotations

import json

import pytest

from code_diver.generation.openai_generation_provider import OpenAIGenerationProvider
from code_diver.generation.openai_compatible_generation_provider import OpenAICompatibleGenerationProvider
from code_diver.providers.openai_compatible_embedding_provider import OpenAICompatibleEmbeddingProvider
from code_diver.providers.openai_embedding_provider import OpenAIEmbeddingProvider


pytestmark = pytest.mark.unit


def test_openai_embedding_provider_posts_embedding_payload(monkeypatch) -> None:
    provider = OpenAIEmbeddingProvider(api_key="key", dimensions=3, batch_size=2)
    calls: list[dict] = []

    def fake_post(payload):
        calls.append(payload)
        return {
            "data": [
                {"index": 0, "embedding": [1, 2, 3]},
                {"index": 1, "embedding": [4, 5, 6]},
            ]
        }

    monkeypatch.setattr(provider, "_post", fake_post)

    assert provider.embed_documents(["a", "b"]) == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
    assert calls[0]["model"] == "text-embedding-3-large"
    assert calls[0]["dimensions"] == 3


def test_openai_embedding_provider_applies_document_and_query_prefixes(monkeypatch) -> None:
    provider = OpenAIEmbeddingProvider(
        api_key="key",
        dimensions=3,
        document_prefix="doc: ",
        query_prefix="query: ",
    )
    calls: list[dict] = []

    def fake_post(payload):
        calls.append(payload)
        return {"data": [{"index": 0, "embedding": [1, 2, 3]}]}

    monkeypatch.setattr(provider, "_post", fake_post)

    assert provider.embed_documents(["class Auth"]) == [[1.0, 2.0, 3.0]]
    assert provider.embed_query("where auth") == [1.0, 2.0, 3.0]
    assert calls[0]["input"] == ["doc: class Auth"]
    assert calls[1]["input"] == ["query: where auth"]


def test_openai_generation_provider_requests_json_output(monkeypatch) -> None:
    provider = OpenAIGenerationProvider(api_key="key")
    calls: list[dict] = []

    def fake_post(payload):
        calls.append(payload)
        return {"output_text": json.dumps({"items": []})}

    monkeypatch.setattr(provider, "_post", fake_post)

    assert provider.generate_json("build index") == '{"items": []}'
    assert calls[0]["model"] == "gpt-5.1"
    assert calls[0]["text"]["format"]["type"] == "json_object"


def test_openai_compatible_generation_provider_uses_chat_completions(monkeypatch) -> None:
    provider = OpenAICompatibleGenerationProvider(model="local-model", api_key="local", max_tokens=1536)
    calls: list[dict] = []

    def fake_post(payload):
        calls.append(payload)
        return {"choices": [{"message": {"content": '{"queries":["x"]}'}}]}

    monkeypatch.setattr(provider, "_post", fake_post)

    assert provider.generate_json("plan") == '{"queries":["x"]}'
    assert calls[0]["messages"][0]["role"] == "system"
    assert calls[0]["response_format"]["type"] == "json_object"
    assert calls[0]["max_tokens"] == 1536


def test_openai_compatible_generation_provider_retries_without_response_format(monkeypatch) -> None:
    provider = OpenAICompatibleGenerationProvider(model="local-model", api_key="local")
    calls: list[dict] = []

    def fake_post(payload):
        calls.append(payload)
        if len(calls) == 1:
            raise RuntimeError("HTTP 400: unsupported response_format json_object")
        return {"choices": [{"message": {"content": '{"results":[]}'}}]}

    monkeypatch.setattr(provider, "_post", fake_post)

    assert provider.generate_json("rank") == '{"results":[]}'
    assert provider.generate_json("rank again") == '{"results":[]}'
    assert "response_format" in calls[0]
    assert "response_format" not in calls[1]
    assert "response_format" not in calls[2]


def test_openai_compatible_generation_provider_can_disable_response_format(monkeypatch) -> None:
    provider = OpenAICompatibleGenerationProvider(
        model="local-model",
        api_key="local",
        response_format=False,
    )
    calls: list[dict] = []

    def fake_post(payload):
        calls.append(payload)
        return {"choices": [{"message": {"content": '{"results":[]}'}}]}

    monkeypatch.setattr(provider, "_post", fake_post)

    assert provider.generate_json("rank") == '{"results":[]}'
    assert "response_format" not in calls[0]


def test_openai_compatible_generation_provider_accepts_reasoning_content(monkeypatch) -> None:
    provider = OpenAICompatibleGenerationProvider(model="local-model", api_key="local")

    def fake_post(payload):
        return {"choices": [{"message": {"content": "", "reasoning_content": '{"results":[]}'}}]}

    monkeypatch.setattr(provider, "_post", fake_post)

    assert provider.generate_json("rank") == '{"results":[]}'


def test_openai_compatible_embedding_provider_allows_local_api_key(monkeypatch) -> None:
    provider = OpenAICompatibleEmbeddingProvider(model="embed", dimensions=None, api_key=None)

    def fake_post(payload):
        return {"data": [{"index": 0, "embedding": [0.1, 0.2]}]}

    monkeypatch.setattr(provider, "_post", fake_post)

    assert provider.embed_query("query") == [0.1, 0.2]
    assert provider.name == "openai_compatible"
