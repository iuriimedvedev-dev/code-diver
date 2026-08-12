from __future__ import annotations

import json

import pytest

from code_diver.config import AppConfig
from code_diver.config.generation_config import GenerationConfig
from code_diver.generation.generation_provider_factory import create_generation_provider
from code_diver.generation.openai_compatible_generation_provider import OpenAICompatibleGenerationProvider
from code_diver.generation.openai_compatible_generation_provider_pool import OpenAICompatibleGenerationProviderPool
from code_diver.generation.openai_generation_provider import OpenAIGenerationProvider
from code_diver.generation.response_schemas import RERANK_SCHEMA
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


def test_openai_embedding_provider_bounds_prefixed_query_and_documents(monkeypatch) -> None:
    provider = OpenAIEmbeddingProvider(
        api_key="key",
        dimensions=3,
        document_prefix="doc: ",
        query_prefix="query: ",
        max_input_chars=12,
    )
    calls: list[dict] = []

    def fake_post(payload):
        calls.append(payload)
        return {"data": [{"index": 0, "embedding": [1, 2, 3]}]}

    monkeypatch.setattr(provider, "_post", fake_post)

    assert provider.embed_documents(["abcdefghijk"]) == [[1.0, 2.0, 3.0]]
    assert provider.embed_query("abcdefghijk") == [1.0, 2.0, 3.0]
    assert calls[0]["input"] == ["doc: abcdefg"]
    assert calls[1]["input"] == ["query: abcde"]


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


def test_openai_compatible_generation_provider_sends_the_task_schema_in_json_schema_mode(monkeypatch) -> None:
    provider = OpenAICompatibleGenerationProvider(
        model="local-model",
        api_key="local",
        response_format="json_schema",
    )
    calls: list[dict] = []

    def fake_post(payload):
        calls.append(payload)
        return {"choices": [{"message": {"content": '{"results":[]}'}}]}

    monkeypatch.setattr(provider, "_post", fake_post)

    assert provider.generate_json("rank", schema=RERANK_SCHEMA) == '{"results":[]}'
    assert calls[0]["response_format"]["type"] == "json_schema"
    assert calls[0]["response_format"]["json_schema"]["schema"] == RERANK_SCHEMA


def test_openai_compatible_generation_provider_falls_back_to_json_object_without_a_schema(monkeypatch) -> None:
    """json_schema mode with no task schema used to send `{"type": "object"}`, which `{}`
    satisfies -- the mode was on and enforced nothing. json_object is at least honest."""
    provider = OpenAICompatibleGenerationProvider(
        model="local-model",
        api_key="local",
        response_format="json_schema",
    )
    calls: list[dict] = []

    def fake_post(payload):
        calls.append(payload)
        return {"choices": [{"message": {"content": '{"results":[]}'}}]}

    monkeypatch.setattr(provider, "_post", fake_post)

    assert provider.generate_json("rank") == '{"results":[]}'
    assert calls[0]["response_format"] == {"type": "json_object"}


def test_openai_compatible_generation_provider_sends_extra_body(monkeypatch) -> None:
    provider = OpenAICompatibleGenerationProvider(
        model="local-model",
        api_key="local",
        response_format=False,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}, "top_k": 20},
    )
    calls: list[dict] = []

    def fake_post(payload):
        calls.append(payload)
        return {"choices": [{"message": {"content": '{"results":[]}'}}]}

    monkeypatch.setattr(provider, "_post", fake_post)

    assert provider.generate_json("rank") == '{"results":[]}'
    assert calls[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert calls[0]["top_k"] == 20
    assert "response_format" not in calls[0]


def test_openai_compatible_generation_provider_rejects_flat_chat_template_options() -> None:
    """A top-level `enable_thinking` is accepted by every server and applied by none.

    Two Qwen3.5 configs carried the flat form, ran with thinking enabled, and returned
    empty answers ~10% of the time. Silently accepting it is what hid that for a whole
    experiment round, so it is now a startup error naming the nested form.
    """
    with pytest.raises(ValueError, match="chat_template_kwargs"):
        OpenAICompatibleGenerationProvider(
            model="local-model",
            api_key="local",
            extra_body={"enable_thinking": False},
        )


def test_openai_compatible_generation_provider_rejects_extra_body_clobbering_reserved_keys() -> None:
    with pytest.raises(ValueError, match="messages"):
        OpenAICompatibleGenerationProvider(
            model="local-model",
            api_key="local",
            extra_body={"messages": [{"role": "user", "content": "hijacked"}]},
        )


def test_openai_compatible_generation_provider_rejects_a_reasoning_only_response(monkeypatch) -> None:
    """`reasoning_content` must never stand in for the answer.

    Returning a thinking trace as content produced JSON parse failures that were
    attributed to model answer quality; the real cause was thinking mode left enabled.
    """
    provider = OpenAICompatibleGenerationProvider(model="local-model", api_key="local")

    def fake_post(payload):
        return {
            "choices": [
                {
                    "message": {"content": "", "reasoning_content": "Let me think about the ranking..."},
                    "finish_reason": "length",
                }
            ]
        }

    monkeypatch.setattr(provider, "_post", fake_post)

    with pytest.raises(RuntimeError, match="only a reasoning trace"):
        provider.generate_json("rank")


def test_openai_compatible_generation_provider_pool_round_robins(monkeypatch) -> None:
    calls: list[str] = []

    def fake_post(self, payload):
        calls.append(self.url)
        return {"choices": [{"message": {"content": '{"results":[]}'}}]}

    monkeypatch.setattr(OpenAICompatibleGenerationProvider, "_post", fake_post)

    provider = OpenAICompatibleGenerationProviderPool(
        model="local-model",
        api_key="local",
        urls=[
            "http://127.0.0.1:8016/v1/chat/completions",
            "http://127.0.0.1:8017/v1/chat/completions",
        ],
    )

    assert provider.generate_json("rank") == '{"results":[]}'
    assert provider.generate_json("rank") == '{"results":[]}'
    assert provider.generate_json("rank") == '{"results":[]}'
    assert calls == [
        "http://127.0.0.1:8016/v1/chat/completions",
        "http://127.0.0.1:8017/v1/chat/completions",
        "http://127.0.0.1:8016/v1/chat/completions",
    ]


def test_generation_provider_factory_uses_openai_compatible_pool_for_urls() -> None:
    provider = create_generation_provider(
        AppConfig(
            generation=GenerationConfig(
                provider="openai_compatible",
                model="local-model",
                api_key="local",
                urls=[
                    "http://127.0.0.1:8016/v1/chat/completions",
                    "http://127.0.0.1:8017/v1/chat/completions",
                ],
            )
        )
    )

    # The factory wraps every backend in the schema guard, so assert on the backend.
    backend = provider.provider
    assert isinstance(backend, OpenAICompatibleGenerationProviderPool)
    assert backend.name == "openai_compatible_pool"
    assert provider.name == "schema_guarded:openai_compatible_pool"
    assert [child.url for child in backend.providers] == [
        "http://127.0.0.1:8016/v1/chat/completions",
        "http://127.0.0.1:8017/v1/chat/completions",
    ]


def test_openai_compatible_embedding_provider_allows_local_api_key(monkeypatch) -> None:
    provider = OpenAICompatibleEmbeddingProvider(model="embed", dimensions=None, api_key=None)

    def fake_post(payload):
        return {"data": [{"index": 0, "embedding": [0.1, 0.2]}]}

    monkeypatch.setattr(provider, "_post", fake_post)

    assert provider.embed_query("query") == [0.1, 0.2]
    assert provider.name == "openai_compatible"


def test_openai_compatible_embedding_provider_retries_transient_failures(monkeypatch) -> None:
    provider = OpenAICompatibleEmbeddingProvider(
        model="embed",
        dimensions=None,
        api_key=None,
        retry_attempts=2,
        retry_delay_seconds=0,
    )
    provider.retry.sleep = lambda _seconds: None
    provider.retry.jitter = lambda: 0.0
    calls = 0

    def fake_post(payload):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("HTTP 503: model is loading")
        return {"data": [{"index": 0, "embedding": [0.1, 0.2]}]}

    monkeypatch.setattr(provider, "_post", fake_post)

    assert provider.embed_query("query") == [0.1, 0.2]
    assert calls == 2
