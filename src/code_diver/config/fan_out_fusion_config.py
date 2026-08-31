from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class FanOutFusionConfig:
    """H-75: single-round fan-out over the champion retrieval pipeline.

    Disabled by default. When enabled the search orchestrator asks the model once for
    query rephrasings, runs them as parallel code_diver_search calls and fuses the
    returned ranked lists with reciprocal rank fusion, without a second model round.
    """

    enabled: bool = False
    queries: int = 4
    search_limit: int = 30
    rrf_k: int = 60
    rerank: bool = False
    rerank_pool: int = 30
    monotonic: bool = False
    baseline_head: int = 0
    # H-76: run the probes on the cross-encoder-less base strategy and rerank the union
    # of their candidates once, instead of one cross-encoder pass per probe followed by a
    # splice of already-truncated top-N lists.
    union_rerank: bool = False
    union_candidate_limit: int = 0
    probe_search_limit: int = 0
