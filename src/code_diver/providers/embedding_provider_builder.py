from __future__ import annotations

from typing import Any

from ..config import AppConfig
from ..config.embedding_profile_registry import EmbeddingProfileRegistry
from ..runtime import EmbeddingRuntimeManager, RuntimeConfigStore
from ..settings import Defaults, EmbeddingProviderId, SchemaKey
from .provider_factory import create_embedding_provider


def make_embedding_provider(config: AppConfig, payload: dict[str, Any] | None = None):
    ensure_configured_embedding_runtime(config)
    embedding = config.embedding
    if payload:
        validate_embedding_metadata(config, payload)
    provider_name = embedding.provider or str(
        (payload or {}).get(SchemaKey.PROVIDER.value, Defaults.EMBEDDING_PROVIDER)
    )
    model = embedding.model or (payload or {}).get(SchemaKey.MODEL.value)
    dimensions = embedding.dimensions
    if (
        dimensions is None
        and provider_name != EmbeddingProviderId.OPENAI_COMPATIBLE.value
    ):
        dimensions = (payload or {}).get(SchemaKey.DIMENSIONS.value)
    return create_embedding_provider(
        provider_name,
        model=model,
        dimensions=int(dimensions) if dimensions else None,
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
        max_input_tokens=embedding.max_input_tokens,
        token_safety_margin=embedding.token_safety_margin,
    )


def validate_embedding_metadata(config: AppConfig, payload: dict[str, Any]) -> None:
    expected_provider = config.embedding.provider
    actual_provider = str(payload.get(SchemaKey.PROVIDER.value) or "")
    if expected_provider and actual_provider and expected_provider != actual_provider:
        raise ValueError(
            "Index embedding provider mismatch: "
            f"config expects {expected_provider!r}, artifact has {actual_provider!r}. "
            "Rebuild the index with `--reindex` or select the matching config."
        )

    expected_model = config.embedding.model
    actual_model = str(payload.get(SchemaKey.MODEL.value) or "")
    if expected_model and actual_model and expected_model != actual_model:
        raise ValueError(
            "Index embedding model mismatch: "
            f"config expects {expected_model!r}, artifact has {actual_model!r}. "
            "Rebuild the index with `--reindex` or select the matching config."
        )

    expected_dimensions = config.embedding.dimensions
    actual_dimensions = payload.get(SchemaKey.DIMENSIONS.value)
    if (
        expected_dimensions is not None
        and actual_dimensions is not None
        and int(expected_dimensions) != int(actual_dimensions)
    ):
        raise ValueError(
            "Index embedding dimensions mismatch: "
            f"config expects {expected_dimensions}, artifact has {actual_dimensions}. "
            "Rebuild the index with `--reindex` or select the matching config."
        )


def ensure_configured_embedding_runtime(config: AppConfig) -> None:
    profile_key = local_embedding_profile_key(config)
    if profile_key is None:
        return
    store = RuntimeConfigStore()
    if not store.exists():
        profile = EmbeddingProfileRegistry().get(profile_key)
        platform = next(
            (item for item in profile.platforms if item not in {"external", "api"}),
            "external",
        )
        raise RuntimeError(
            "Local embedding runtime is not configured. Run "
            f"`uv run code-diver init --platform {platform} --embedding {profile_key} --yes --start` first."
        )
    runtime = store.load()
    if runtime.embedding_profile != profile_key:
        raise RuntimeError(
            "Configured local embedding runtime does not match this embedding model. "
            f"runtime={runtime.embedding_profile}, requested={profile_key}. "
            f"Run `uv run code-diver init --embedding {profile_key}`."
        )
    EmbeddingRuntimeManager(runtime).ensure_running()


def local_embedding_profile_key(config: AppConfig) -> str | None:
    embedding = config.embedding
    if embedding.provider != EmbeddingProviderId.OPENAI_COMPATIBLE.value:
        return None
    registry = EmbeddingProfileRegistry()
    for profile in registry.profiles():
        candidate = profile.config
        if candidate.provider != EmbeddingProviderId.OPENAI_COMPATIBLE.value:
            continue
        if candidate.model == embedding.model and candidate.url == embedding.url:
            return profile.key
    return None
