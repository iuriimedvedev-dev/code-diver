from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from time import perf_counter

from ..config import AppConfig
from ..generation import GenerationProvider, create_generation_provider
from .embedding_provider import EmbeddingProvider
from .provider_factory import create_embedding_provider


@dataclass(slots=True)
class ProviderCheckResult:
    name: str
    provider: str
    model: str | None
    status: str
    latency_ms: int = 0
    details: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    @property
    def ok(self) -> bool:
        return self.status in {"ok", "skipped"}

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "provider": self.provider,
            "model": self.model,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "details": self.details,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(slots=True)
class ProviderTestOptions:
    generation: bool = True
    embedding: bool = True
    fallback_chain: bool = False
    prompt: str = 'Return JSON only: {"ok": true, "provider_test": true}'
    embedding_text: str = "Find where authentication is handled in this codebase."


class ProviderTestService:
    INVALID_PRIMARY_MODEL = "__code_diver_provider_test_invalid_primary__"

    def __init__(
        self,
        generation_factory: Callable[[AppConfig], GenerationProvider] = create_generation_provider,
        embedding_factory: Callable[[AppConfig], EmbeddingProvider] | None = None,
    ):
        self.generation_factory = generation_factory
        self.embedding_factory = embedding_factory or self._embedding_provider

    def run(self, config: AppConfig, options: ProviderTestOptions) -> list[ProviderCheckResult]:
        results: list[ProviderCheckResult] = []
        if options.generation:
            results.extend(self._generation_checks(config, options))
        if options.embedding:
            results.append(self._embedding_check(config, options))
        return results

    def _generation_checks(
        self,
        config: AppConfig,
        options: ProviderTestOptions,
    ) -> list[ProviderCheckResult]:
        results = [self._generation_check(config, options.prompt, "generation.primary")]
        for index, model in enumerate(config.generation.fallback_models, start=1):
            fallback_config = self._generation_model_config(config, model=model, fallback_models=[])
            results.append(self._generation_check(fallback_config, options.prompt, f"generation.fallback[{index}]"))
        if options.fallback_chain:
            results.append(self._fallback_chain_check(config, options.prompt))
        return results

    def _generation_check(self, config: AppConfig, prompt: str, name: str) -> ProviderCheckResult:
        started = perf_counter()
        provider_name = config.generation.provider
        model = config.generation.model
        try:
            provider = self.generation_factory(config)
            result = provider.generate_json_result(prompt)
            parsed = json.loads(result.text)
            if not isinstance(parsed, dict):
                raise ValueError("generation response was valid JSON but not an object")
            return ProviderCheckResult(
                name=name,
                provider=getattr(provider, "name", provider_name),
                model=result.model or model,
                status="ok",
                latency_ms=self._elapsed_ms(started),
                details=self._compact_json(parsed),
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                total_tokens=result.total_tokens,
            )
        except Exception as exc:
            return ProviderCheckResult(
                name=name,
                provider=provider_name,
                model=model,
                status="failed",
                latency_ms=self._elapsed_ms(started),
                details=str(exc),
            )

    def _fallback_chain_check(self, config: AppConfig, prompt: str) -> ProviderCheckResult:
        if not config.generation.fallback_models:
            return ProviderCheckResult(
                name="generation.fallback_chain",
                provider=config.generation.provider,
                model=None,
                status="skipped",
                details="no fallback_models configured",
            )
        fallback_config = self._generation_model_config(
            config,
            model=self.INVALID_PRIMARY_MODEL,
            fallback_models=list(config.generation.fallback_models),
        )
        result = self._generation_check(fallback_config, prompt, "generation.fallback_chain")
        if result.status != "ok":
            return result
        if result.model not in config.generation.fallback_models:
            result.status = "failed"
            result.details = (
                "response succeeded but did not report a configured fallback model; "
                f"reported={result.model!r}"
            )
        return result

    def _embedding_check(self, config: AppConfig, options: ProviderTestOptions) -> ProviderCheckResult:
        started = perf_counter()
        embedding = config.embedding
        try:
            provider = self.embedding_factory(config)
            query_vector = provider.embed_query(options.embedding_text)
            document_vectors = provider.embed_documents([options.embedding_text])
            query_dim = len(query_vector)
            document_dim = len(document_vectors[0]) if document_vectors else 0
            if query_dim <= 0 or document_dim <= 0:
                raise ValueError("embedding provider returned an empty vector")
            if query_dim != document_dim:
                raise ValueError(f"query/document dimensions differ: query={query_dim}, document={document_dim}")
            return ProviderCheckResult(
                name="embedding.query_and_document",
                provider=getattr(provider, "name", embedding.provider),
                model=getattr(provider, "model", embedding.model),
                status="ok",
                latency_ms=self._elapsed_ms(started),
                details=f"dimension={query_dim}",
            )
        except Exception as exc:
            return ProviderCheckResult(
                name="embedding.query_and_document",
                provider=embedding.provider,
                model=embedding.model,
                status="failed",
                latency_ms=self._elapsed_ms(started),
                details=str(exc),
            )

    def _generation_model_config(self, config: AppConfig, model: str, fallback_models: list[str]) -> AppConfig:
        return replace(config, generation=replace(config.generation, model=model, fallback_models=fallback_models))

    def _embedding_provider(self, config: AppConfig) -> EmbeddingProvider:
        embedding = config.embedding
        return create_embedding_provider(
            provider=embedding.provider,
            model=embedding.model,
            dimensions=embedding.dimensions,
            api_key=embedding.api_key,
            url=embedding.url,
            project=embedding.project,
            location=embedding.location,
            batch_size=embedding.batch_size,
            retry_attempts=embedding.retry_attempts,
            retry_delay_seconds=embedding.retry_delay_seconds,
            document_prefix=embedding.document_prefix,
            query_prefix=embedding.query_prefix,
            max_input_chars=embedding.max_input_chars,
        )

    def _elapsed_ms(self, started: float) -> int:
        return int((perf_counter() - started) * 1000)

    def _compact_json(self, value: object) -> str:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return text if len(text) <= 180 else text[:177] + "..."
