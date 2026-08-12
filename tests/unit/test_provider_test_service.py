from __future__ import annotations

import pytest

from code_diver.config import AppConfig
from code_diver.config.embedding_config import EmbeddingConfig
from code_diver.config.generation_config import GenerationConfig
from code_diver.generation import GenerationResult
from code_diver.providers import ProviderTestOptions, ProviderTestService

pytestmark = pytest.mark.unit


class FakeGenerationProvider:
    name = "fake-generation"

    def __init__(self, model: str):
        self.model = model

    def generate_json(self, prompt: str, *, schema: dict | None = None) -> str:
        return self.generate_json_result(prompt).text

    def generate_json_result(self, prompt: str, *, schema: dict | None = None) -> GenerationResult:
        if self.model == ProviderTestService.INVALID_PRIMARY_MODEL:
            raise RuntimeError("invalid model")
        return GenerationResult(
            text='{"ok":true}',
            model=self.model,
            input_tokens=3,
            output_tokens=2,
            total_tokens=5,
        )


class FakeFallbackGenerationProvider(FakeGenerationProvider):
    fallback_model: str

    def generate_json_result(self, prompt: str, *, schema: dict | None = None) -> GenerationResult:
        if self.model == ProviderTestService.INVALID_PRIMARY_MODEL:
            return GenerationResult(text='{"ok":true}', model=self.fallback_model, total_tokens=7)
        return super().generate_json_result(prompt)


class FakeEmbeddingProvider:
    name = "fake-embedding"
    model = "fake-embed"

    def embed_query(self, query: str) -> list[float]:
        return [0.1, 0.2, 0.3]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.3, 0.2, 0.1] for _ in texts]


def test_provider_test_service_checks_generation_fallbacks_and_embeddings() -> None:
    config = AppConfig(
        generation=GenerationConfig(
            provider="fake",
            model="primary-model",
            fallback_models=["fallback-model"],
        ),
        embedding=EmbeddingConfig(provider="fake", model="fake-embed", dimensions=3),
    )
    service = ProviderTestService(
        generation_factory=lambda config: FakeGenerationProvider(config.generation.model),
        embedding_factory=lambda _config: FakeEmbeddingProvider(),
    )

    results = service.run(config, ProviderTestOptions())

    assert [result.name for result in results] == [
        "generation.primary",
        "generation.fallback[1]",
        "embedding.query_and_document",
    ]
    assert all(result.status == "ok" for result in results)
    assert results[1].model == "fallback-model"


def test_provider_test_service_can_force_fallback_chain() -> None:
    config = AppConfig(
        generation=GenerationConfig(
            provider="fake",
            model="primary-model",
            fallback_models=["fallback-model"],
        ),
    )

    def generation_factory(config: AppConfig) -> FakeFallbackGenerationProvider:
        provider = FakeFallbackGenerationProvider(config.generation.model)
        provider.fallback_model = config.generation.fallback_models[0]
        return provider

    service = ProviderTestService(
        generation_factory=generation_factory,
        embedding_factory=lambda _config: FakeEmbeddingProvider(),
    )

    results = service.run(config, ProviderTestOptions(embedding=False, fallback_chain=True))

    chain = results[-1]
    assert chain.name == "generation.fallback_chain"
    assert chain.status == "ok"
    assert chain.model == "fallback-model"


def test_provider_test_service_marks_invalid_json_generation_as_failed() -> None:
    class BadJsonProvider(FakeGenerationProvider):
        def generate_json_result(self, prompt: str, *, schema: dict | None = None) -> GenerationResult:
            return GenerationResult(text="not json", model=self.model)

    config = AppConfig(generation=GenerationConfig(provider="fake", model="bad-json"))
    service = ProviderTestService(
        generation_factory=lambda config: BadJsonProvider(config.generation.model),
        embedding_factory=lambda _config: FakeEmbeddingProvider(),
    )

    results = service.run(config, ProviderTestOptions(embedding=False))

    assert results[0].status == "failed"
    assert "Expecting value" in results[0].details
