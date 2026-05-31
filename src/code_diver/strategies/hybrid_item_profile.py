from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HybridItemProfile:
    title_terms: frozenset[str]
    path_terms: frozenset[str]
    content_terms: frozenset[str]
    metadata_terms: frozenset[str]
