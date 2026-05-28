from __future__ import annotations

import hashlib

from .embedding_provider import EmbeddingProvider
from ..settings import Defaults, EmbeddingProviderId
from ..services.tokenizer import tokenize
from ..math_utils import normalize


class HashEmbeddingProvider(EmbeddingProvider):
    def __init__(self, dimensions: int = Defaults.HASH_DIMENSIONS):
        self.name = EmbeddingProviderId.HASH.value
        self.model = Defaults.HASH_MODEL
        self.dimensions = dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, query: str) -> list[float]:
        return self._embed(query)

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in tokenize(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign
        return normalize(vector)
