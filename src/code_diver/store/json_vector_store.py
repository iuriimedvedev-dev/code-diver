from __future__ import annotations

import json
from array import array
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import numpy as np
except ImportError:  # pragma: no cover - exercised when NumPy is unavailable
    np = None

from ..domain import CodeItem, SearchResult
from ..math_utils import normalize
from ..settings import SchemaKey
from .index_store_error import IndexStoreError
from .vector_store import VectorStore

SCHEMA_VERSION = 1


class JsonVectorStore(VectorStore):
    def __init__(self, artifact: Path):
        self.artifact = artifact
        self._payload_cache: dict[str, Any] | None = None
        self._records_cache: list[dict[str, Any]] | None = None
        self._items_cache: list[CodeItem] | None = None
        self._normalized_vectors_cache: Any | None = None
        self._vector_offsets_cache: list[tuple[int, int]] | None = None
        self._items_by_kind_cache: dict[str, list[int]] | None = None
        self._native_flat_vectors_cache: list[float] | None = None

    def exists(self) -> bool:
        return self.artifact.exists()

    def save(
        self,
        *,
        root: Path,
        provider: str,
        model: str,
        dimensions: int,
        items: list[CodeItem],
        vectors: list[list[float]],
    ) -> None:
        if len(items) != len(vectors):
            raise IndexStoreError(f"Item/vector mismatch: {len(items)} items, {len(vectors)} vectors")

        self.artifact.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            SchemaKey.SCHEMA_VERSION.value: SCHEMA_VERSION,
            SchemaKey.CREATED_AT.value: datetime.now(UTC).isoformat(),
            SchemaKey.ROOT.value: str(root.resolve()),
            SchemaKey.PROVIDER.value: provider,
            SchemaKey.MODEL.value: model,
            SchemaKey.DIMENSIONS.value: dimensions,
            SchemaKey.ITEMS.value: [
                {
                    SchemaKey.ITEM.value: item.to_json(),
                    SchemaKey.VECTOR.value: vector,
                }
                for item, vector in zip(items, vectors, strict=True)
            ],
        }
        self.artifact.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._invalidate_caches()

    def metadata(self) -> dict[str, Any]:
        payload = self._cached_payload()
        return {
            SchemaKey.PROVIDER.value: payload[SchemaKey.PROVIDER.value],
            SchemaKey.MODEL.value: payload[SchemaKey.MODEL.value],
            SchemaKey.DIMENSIONS.value: payload[SchemaKey.DIMENSIONS.value],
        }

    def search(self, query_vector: list[float], limit: int) -> list[SearchResult]:
        items = self._cached_items()
        return self._search_items(query_vector, items, range(len(items)), limit)

    def search_by_index_kind(self, query_vector: list[float], limit: int, index_kind: str) -> list[SearchResult]:
        items = self._cached_items()
        indices = (self._items_by_kind_cache or {}).get(index_kind, [])
        return self._search_items(query_vector, items, indices, limit)

    def _get_native_flat_vectors(self) -> list[float] | None:
        """Return a flat list of floats for native search, or None if unavailable."""
        if self._native_flat_vectors_cache is not None:
            return self._native_flat_vectors_cache
        try:
            import code_diver_search as mod

            if not hasattr(mod, "search_flat_f64_py"):
                return None
            vectors = self._cached_normalized_vectors()
            self._native_flat_vectors_cache = [float(value) for value in vectors]
            return self._native_flat_vectors_cache
        except Exception:
            return None

    def _search_items(
        self,
        query_vector: list[float],
        items: list[CodeItem],
        indices: Any,
        limit: int,
    ) -> list[SearchResult]:
        normalized_query = normalize(query_vector)
        # Ensure caches are populated (both normalized vectors and offsets)
        self._cached_normalized_vectors()
        offsets = self._vector_offsets_cache or []

        # NumPy fast path: vectorized matrix-vector dot product (1000x+ faster)
        # Works for both full-search and kind-filtered search
        if np is not None:
            try:
                vectors = self._cached_normalized_vectors()
                # vectors is a flat numpy array (float32) — reshape to matrix
                dim = len(normalized_query)
                n = len(offsets)
                matrix = np.asarray(vectors, dtype=np.float32).reshape(-1, dim)
                nq = np.asarray(normalized_query, dtype=np.float32)
                scores = matrix @ nq  # vectorized BLAS dot product

                if len(indices) == n:
                    # Full search: use all scores
                    if limit >= n:
                        top_k = n
                    else:
                        top_k = limit
                    top_indices = np.argpartition(-scores, top_k)[:top_k]
                    top_indices = top_indices[np.argsort(-scores[top_indices])]
                    return [SearchResult(item=items[idx], score=float(scores[idx])) for idx in top_indices]
                else:
                    # Kind-filtered search: filter by indices, then take top-k
                    filtered = [(idx, float(scores[idx])) for idx in indices]
                    filtered.sort(key=lambda x: x[1], reverse=True)
                    return [SearchResult(item=items[idx], score=score) for idx, score in filtered[:limit]]
            except Exception:
                pass

        # Python fallback
        vectors = self._cached_normalized_vectors()
        scored = []
        for index in indices:
            start, end = offsets[index]
            vector = vectors[start:end]
            scored.append(SearchResult(item=items[index], score=sum(
                a * b for a, b in zip(normalized_query, [float(value) for value in vector], strict=True)
            )))
        scored.sort(key=lambda result: result.score, reverse=True)
        return scored[:limit]

    def load_items_and_vectors(self) -> tuple[dict[str, Any], list[CodeItem], list[list[float]]]:
        payload = self._cached_payload()
        records = self._cached_records()
        items = self._cached_items()
        vectors = [[float(value) for value in record[SchemaKey.VECTOR.value]] for record in records]
        return payload, items, vectors

    def count_items(self) -> int:
        return len(self._cached_items())

    def _cached_items(self) -> list[CodeItem]:
        if self._items_cache is None:
            records = self._cached_records()
            self._items_cache = [CodeItem.from_json(record[SchemaKey.ITEM.value]) for record in records]
            self._items_by_kind_cache = defaultdict(list)
            for index, item in enumerate(self._items_cache):
                kind = str(item.metadata.get("index_kind") or "")
                self._items_by_kind_cache[kind].append(index)
        return self._items_cache

    def _cached_normalized_vectors(self) -> Any:
        if self._normalized_vectors_cache is None:
            records = self._cached_records()
            values: list[float] = []
            offsets: list[tuple[int, int]] = []
            for record in records:
                vector = normalize([float(value) for value in record[SchemaKey.VECTOR.value]])
                start = len(values)
                values.extend(vector)
                offsets.append((start, len(values)))
            # array('f') is the standard-library fallback for a NumPy-free float32 matrix.
            matrix = np.asarray(values, dtype=np.float32) if np is not None else array("f", values)
            self._normalized_vectors_cache = matrix
            self._vector_offsets_cache = offsets
        return self._normalized_vectors_cache

    def _invalidate_caches(self) -> None:
        self._payload_cache = None
        self._records_cache = None
        self._items_cache = None
        self._normalized_vectors_cache = None
        self._vector_offsets_cache = None
        self._items_by_kind_cache = None
        self._native_flat_vectors_cache = None

    def _cached_records(self) -> list[dict[str, Any]]:
        if self._records_cache is None:
            payload = self._cached_payload()
            self._records_cache = payload.get(SchemaKey.ITEMS.value) or []
        return self._records_cache

    def _cached_payload(self) -> dict[str, Any]:
        if self._payload_cache is None:
            self._payload_cache = self._load()
        return self._payload_cache

    def _load(self) -> dict[str, Any]:
        if not self.artifact.exists():
            raise IndexStoreError(f"Index artifact not found: {self.artifact}")
        payload = json.loads(self.artifact.read_text(encoding="utf-8"))
        if payload.get(SchemaKey.SCHEMA_VERSION.value) != SCHEMA_VERSION:
            raise IndexStoreError(
                f"Unsupported index schema {payload.get(SchemaKey.SCHEMA_VERSION.value)}; expected {SCHEMA_VERSION}"
            )
        return payload
