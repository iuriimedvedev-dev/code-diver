from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LtrQuerySplit:
    train_query_ids: tuple[str, ...]
    test_query_ids: tuple[str, ...]

    def overlap(self) -> set[str]:
        return set(self.train_query_ids) & set(self.test_query_ids)


class LtrQuerySplitter:
    """Splits a feature dump by QUERY, never by row.

    A row-level split puts candidates of the same query on both sides: the model then sees
    the answer for a query it is scored on, and the held-out number is meaningless. The
    split is a hash of the query id rather than a shuffle, so it is stable when the dump is
    regenerated with more or fewer candidates per query.
    """

    def split(self, query_ids: Iterable[str], test_fraction: float = 0.5, seed: int = 0) -> LtrQuerySplit:
        if not 0.0 < test_fraction < 1.0:
            raise ValueError(f"test_fraction must be strictly between 0 and 1, got {test_fraction}")
        unique_ids = sorted(dict.fromkeys(str(query_id) for query_id in query_ids))
        train: list[str] = []
        test: list[str] = []
        for query_id in unique_ids:
            bucket = test if self._unit_hash(query_id, seed) < test_fraction else train
            bucket.append(query_id)
        return LtrQuerySplit(train_query_ids=tuple(train), test_query_ids=tuple(test))

    def _unit_hash(self, query_id: str, seed: int) -> float:
        digest = hashlib.sha256(f"{seed}:{query_id}".encode()).digest()
        return int.from_bytes(digest[:8], "big") / float(1 << 64)
