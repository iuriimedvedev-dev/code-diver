from __future__ import annotations

from ..settings import Defaults, EmbeddingProviderId
from .openai_embedding_provider import OpenAIEmbeddingProvider


class OpenAICompatibleEmbeddingProvider(OpenAIEmbeddingProvider):
    def __init__(
        self,
        model: str,
        dimensions: int | None,
        api_key: str | None = None,
        batch_size: int = 32,
        url: str | None = None,
        timeout_seconds: float = Defaults.OPENAI_TIMEOUT_SECONDS,
    ):
        super().__init__(
            model=model,
            dimensions=dimensions or 0,
            api_key=api_key or "local",
            batch_size=batch_size,
            url=url or f"{Defaults.LOCAL_OPENAI_BASE_URL}/embeddings",
            timeout_seconds=timeout_seconds,
        )
        self.name = EmbeddingProviderId.OPENAI_COMPATIBLE.value

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers
