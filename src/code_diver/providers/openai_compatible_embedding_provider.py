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
        document_prefix: str | None = Defaults.EMBEDDING_DOCUMENT_PREFIX,
        query_prefix: str | None = Defaults.EMBEDDING_QUERY_PREFIX,
        max_input_chars: int | None = Defaults.EMBEDDING_MAX_INPUT_CHARS,
    ):
        super().__init__(
            model=model,
            dimensions=dimensions or 0,
            api_key=api_key or "local",
            batch_size=batch_size,
            url=url or f"{Defaults.LOCAL_OPENAI_BASE_URL}/embeddings",
            timeout_seconds=timeout_seconds,
            document_prefix=document_prefix,
            query_prefix=query_prefix,
            max_input_chars=max_input_chars,
            send_dimensions=bool(dimensions),
        )
        self.name = EmbeddingProviderId.OPENAI_COMPATIBLE.value

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers
