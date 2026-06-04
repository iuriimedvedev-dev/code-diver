from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from pathlib import Path

from ..config import AppConfig
from ..settings import Defaults, VectorStoreProviderId


class IndexCollectionResolver:
    def resolve(self, config: AppConfig) -> AppConfig:
        if config.storage.provider != VectorStoreProviderId.QDRANT.value:
            return config
        if config.storage.qdrant.collection != Defaults.QDRANT_COLLECTION:
            return config
        collection = self.collection_name(config.root, config)
        return replace(config, storage=replace(config.storage, qdrant=replace(config.storage.qdrant, collection=collection)))

    def collection_name(self, root: Path, config: AppConfig) -> str:
        repo = self.repo_prefix(root, config.storage.qdrant.collection)
        embedding = self._embedding_slug(config)
        return f"{repo}__emb_{embedding}"

    def repo_prefix(self, root: Path, base_collection: str = Defaults.QDRANT_COLLECTION) -> str:
        resolved = root.resolve()
        repo_slug = self._slug(resolved.name or "repo", max_length=40)
        repo_hash = hashlib.sha1(str(resolved).encode("utf-8")).hexdigest()[:10]
        return f"{self._slug(base_collection, max_length=40)}__repo_{repo_slug}_{repo_hash}"

    def _embedding_slug(self, config: AppConfig) -> str:
        provider = self._slug(config.embedding.provider or Defaults.EMBEDDING_PROVIDER, max_length=24)
        model = self._slug(config.embedding.model or Defaults.EMBEDDING_MODEL, max_length=48)
        dimensions = config.embedding.dimensions or "auto"
        max_chars = config.embedding.max_input_chars or "full"
        raw = f"{provider}_{model}_{dimensions}d_{max_chars}c"
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
        return f"{self._slug(raw, max_length=90)}_{digest}"

    def _slug(self, value: object, max_length: int) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", str(value).lower()).strip("_")
        return (slug or "default")[:max_length].strip("_") or "default"
