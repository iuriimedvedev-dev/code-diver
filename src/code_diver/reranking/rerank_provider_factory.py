from __future__ import annotations

from ..config.cross_encoder_rerank_config import CrossEncoderRerankConfig
from .llama_cpp_rerank_provider import LlamaCppRerankProvider
from .rerank_provider import RerankProvider


class RerankProviderFactory:
    def create(self, config: CrossEncoderRerankConfig) -> RerankProvider:
        if config.provider == "llama_cpp":
            return LlamaCppRerankProvider(
                model=config.model,
                url=config.url,
                api_key=config.api_key,
                timeout_ms=config.timeout_ms,
            )
        raise ValueError(f"Unknown cross-encoder rerank provider: {config.provider}")
