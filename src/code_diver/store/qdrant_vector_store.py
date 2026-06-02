from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from ..domain import CodeItem, SearchResult
from ..settings import Defaults, SchemaKey
from .vector_store import VectorStore


class QdrantVectorStore(VectorStore):
    def __init__(
        self,
        *,
        url: str = Defaults.QDRANT_URL,
        location: str | None = None,
        collection: str = Defaults.QDRANT_COLLECTION,
        api_key: str | None = None,
        api_key_env: str | None = Defaults.QDRANT_API_KEY_ENV,
        batch_size: int = Defaults.QDRANT_BATCH_SIZE,
    ):
        try:
            from qdrant_client import QdrantClient
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise RuntimeError("Install dependencies with `uv sync` before using Qdrant storage.") from exc

        resolved_key = api_key or (os.environ.get(api_key_env) if api_key_env else None)
        resolved_key = resolved_key.strip() if resolved_key else None
        if location == ":memory:":
            self.client = QdrantClient(location=location)
        elif location:
            self.client = QdrantClient(path=location)
        else:
            self.client = QdrantClient(url=url, api_key=resolved_key)
        self.collection = collection
        self.batch_size = batch_size

    def exists(self) -> bool:
        return bool(self.client.collection_exists(self.collection))

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
            raise ValueError(f"Item/vector mismatch: {len(items)} items, {len(vectors)} vectors")

        self.replace_batches(
            root=root,
            provider=provider,
            model=model,
            dimensions=dimensions,
            batches=[(items, vectors)],
        )

    def replace_batches(
        self,
        *,
        root: Path,
        provider: str,
        model: str,
        dimensions: int | Callable[[], int],
        batches: Iterable[tuple[list[CodeItem], list[list[float]]]],
    ) -> None:
        from qdrant_client import models

        iterator = iter(batches)
        try:
            first_items, first_vectors = next(iterator)
        except StopIteration:
            resolved_dimensions = self._resolved_dimensions(dimensions)
            if resolved_dimensions <= 0:
                raise ValueError("Cannot create an empty Qdrant collection without positive dimensions.")
            first_items, first_vectors = [], []
        if len(first_items) != len(first_vectors):
            raise ValueError(f"Item/vector mismatch: {len(first_items)} items, {len(first_vectors)} vectors")

        resolved_dimensions = self._resolved_dimensions(dimensions) or (len(first_vectors[0]) if first_vectors else 0)
        if resolved_dimensions <= 0:
            raise ValueError("Qdrant dimensions must be positive.")

        staging_collection = self._staging_collection_name()
        previous_target = self._alias_target(self.collection)
        published = False
        try:
            self.client.create_collection(
                collection_name=staging_collection,
                vectors_config=models.VectorParams(size=resolved_dimensions, distance=models.Distance.COSINE),
            )
            self._upsert_points_to_collection(
                staging_collection,
                root,
                provider,
                model,
                resolved_dimensions,
                first_items,
                first_vectors,
            )
            for item_batch, vector_batch in iterator:
                if len(item_batch) != len(vector_batch):
                    raise ValueError(f"Item/vector mismatch: {len(item_batch)} items, {len(vector_batch)} vectors")
                self._upsert_points_to_collection(
                    staging_collection,
                    root,
                    provider,
                    model,
                    resolved_dimensions,
                    item_batch,
                    vector_batch,
                )
            previous_target_to_delete = self._publish_staging_collection(staging_collection, previous_target)
            published = True
            if previous_target_to_delete is not None:
                self._delete_collection_if_exists(previous_target_to_delete)
        finally:
            if not published:
                self._delete_collection_if_exists(staging_collection)

    def append(
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
            raise ValueError(f"Item/vector mismatch: {len(items)} items, {len(vectors)} vectors")

        from qdrant_client import models

        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=models.VectorParams(size=dimensions, distance=models.Distance.COSINE),
            )
        else:
            metadata = self.metadata()
            existing_dimensions = metadata.get(SchemaKey.DIMENSIONS.value)
            if existing_dimensions and int(existing_dimensions) != int(dimensions):
                raise ValueError(f"Qdrant dimension mismatch: existing={existing_dimensions}, new={dimensions}")
        self._upsert_points(root, provider, model, dimensions, items, vectors)

    def metadata(self) -> dict[str, Any]:
        points, _ = self.client.scroll(collection_name=self.collection, limit=1, with_payload=True, with_vectors=False)
        if not points:
            return {}
        payload = points[0].payload or {}
        return {
            SchemaKey.PROVIDER.value: payload.get(SchemaKey.PROVIDER.value),
            SchemaKey.MODEL.value: payload.get(SchemaKey.MODEL.value),
            SchemaKey.DIMENSIONS.value: payload.get(SchemaKey.DIMENSIONS.value),
        }

    def search(self, query_vector: list[float], limit: int) -> list[SearchResult]:
        response = self.client.query_points(
            collection_name=self.collection,
            query=query_vector,
            limit=limit,
            with_payload=True,
        )
        return self._results_from_points(response.points)

    def search_by_index_kind(self, query_vector: list[float], limit: int, index_kind: str) -> list[SearchResult]:
        from qdrant_client import models

        response = self.client.query_points(
            collection_name=self.collection,
            query=query_vector,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key=f"{SchemaKey.ITEM.value}.{SchemaKey.METADATA.value}.index_kind",
                        match=models.MatchValue(value=index_kind),
                    )
                ]
            ),
            limit=limit,
            with_payload=True,
        )
        return self._results_from_points(response.points)

    def _results_from_points(self, points: Any) -> list[SearchResult]:
        return [
            SearchResult(item=CodeItem.from_json((point.payload or {})[SchemaKey.ITEM.value]), score=float(point.score))
            for point in points
        ]

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if callable(close):
            close()

    def count_items(self) -> int:
        if not self.client.collection_exists(self.collection):
            return 0
        return int(self.client.count(collection_name=self.collection, exact=True).count)

    def _point_id(self, item_id: str) -> str:
        return uuid.uuid5(uuid.NAMESPACE_URL, item_id).hex

    def _staging_collection_name(self) -> str:
        return f"{self.collection}__staging_{uuid.uuid4().hex}"

    def _resolved_dimensions(self, dimensions: int | Callable[[], int]) -> int:
        value = dimensions() if callable(dimensions) else dimensions
        return int(value or 0)

    def _alias_target(self, alias_name: str) -> str | None:
        aliases = self.client.get_aliases().aliases
        for alias in aliases:
            if alias.alias_name == alias_name:
                return alias.collection_name
        return None

    def _publish_staging_collection(self, staging_collection: str, previous_target: str | None) -> str | None:
        from qdrant_client import models

        if previous_target is not None:
            self.client.update_collection_aliases(
                [
                    models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=self.collection)),
                    models.CreateAliasOperation(
                        create_alias=models.CreateAlias(
                            collection_name=staging_collection,
                            alias_name=self.collection,
                        )
                    ),
                ]
            )
            return previous_target

        if self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)
        self.client.update_collection_aliases(
            [
                models.CreateAliasOperation(
                    create_alias=models.CreateAlias(
                        collection_name=staging_collection,
                        alias_name=self.collection,
                    )
                )
            ]
        )
        return None

    def _delete_collection_if_exists(self, collection: str) -> None:
        if self.client.collection_exists(collection):
            self.client.delete_collection(collection)

    def _upsert_points(
        self,
        root: Path,
        provider: str,
        model: str,
        dimensions: int,
        items: list[CodeItem],
        vectors: list[list[float]],
    ) -> None:
        self._upsert_points_to_collection(self.collection, root, provider, model, dimensions, items, vectors)

    def _upsert_points_to_collection(
        self,
        collection: str,
        root: Path,
        provider: str,
        model: str,
        dimensions: int,
        items: list[CodeItem],
        vectors: list[list[float]],
    ) -> None:
        from qdrant_client import models

        for offset in range(0, len(items), self.batch_size):
            points = [
                models.PointStruct(
                    id=self._point_id(item.id),
                    vector=vector,
                    payload={
                        SchemaKey.ITEM.value: item.to_json(),
                        SchemaKey.ROOT.value: str(root.resolve()),
                        SchemaKey.PROVIDER.value: provider,
                        SchemaKey.MODEL.value: model,
                        SchemaKey.DIMENSIONS.value: dimensions,
                    },
                )
                for item, vector in zip(items[offset : offset + self.batch_size], vectors[offset : offset + self.batch_size])
            ]
            self.client.upsert(collection_name=collection, points=points)
