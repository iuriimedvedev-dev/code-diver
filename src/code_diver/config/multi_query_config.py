from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MultiQueryConfig:
    """H-84: deterministic multi-query expansion with reciprocal-rank fusion.

    The original query is always retained and receives an optional score weight;
    generated variants are bounded and can be searched concurrently. Disabled by
    default so existing retrieval behavior is unchanged.
    """

    enabled: bool = False
    max_variants: int = 4
    rrf_k: int = 60
    original_query_weight: float = 2.0
    llm_rewrites_enabled: bool = False
    parallel_variants: bool = True
    max_variant_workers: int = 4
