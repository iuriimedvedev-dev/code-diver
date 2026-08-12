from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..settings import Defaults
from .generation_config import GenerationConfig


@dataclass(slots=True)
class LlmRerankConfig:
    # None means "rerank with the app-level `generation` block". Set it to run the rerank
    # stage on a cheaper model than the answer generator: the two stages have different
    # prompts, different output sizes, and no reason to share a latency budget. Spelled as
    # a full GenerationConfig to match `ExperimentHypothesisConfig.rerank_generation`;
    # unset keys inherit from the app-level block, so YAML usually names only `model`.
    generation: GenerationConfig | None = None
    candidate_limit: int = Defaults.LLM_RERANK_CANDIDATE_LIMIT
    rerank_limit: int = Defaults.LLM_RERANK_RERANK_LIMIT
    # Rank the candidates as several short lists instead of one long one. Measured transfer --
    # the share of pooled expected paths that survive reranking -- falls off with list length:
    # 92.9% at 20 candidates, 89.6% at 34, 82.0% at 60. Pool recall rises over that same range
    # (0.791 -> 0.859 -> 0.908) but end-to-end file recall does not: 0.735 / 0.770 / 0.745, an
    # inverted U peaking at 34. The reranker, not retrieval, is what caps quality here.
    # Chunking trades round trips for list length: prompt ingest is roughly conserved (3x20
    # previews cost about what 1x60 costs) while every call sees a list short enough to rank
    # well. None keeps the single-shot behaviour.
    chunk_size: int | None = None
    # How many candidates each chunk contributes to the final list. Distinct from `rerank_limit`,
    # which caps the final *output*: with `chunk_size: 20` over 60 candidates, keeping 7 per
    # chunk feeds a 21-item final list, while keeping `rerank_limit: 10` would feed 30 and
    # re-enter the regime chunking exists to avoid. None means "keep `rerank_limit` per chunk".
    chunk_keep: int | None = None
    max_preview_chars: int = Defaults.LLM_RERANK_MAX_PREVIEW_CHARS
    mode: str = Defaults.LLM_RERANK_MODE
    include_reasons: bool = Defaults.LLM_RERANK_INCLUDE_REASONS
    preserve_top_candidate: bool = Defaults.LLM_RERANK_PRESERVE_TOP_CANDIDATE
    preserve_top_score_margin: float = Defaults.LLM_RERANK_PRESERVE_TOP_SCORE_MARGIN
    retry_attempts: int = Defaults.LLM_RERANK_RETRY_ATTEMPTS
    retry_base_delay_seconds: float = Defaults.LLM_RERANK_RETRY_BASE_DELAY_SECONDS
    retry_max_delay_seconds: float = Defaults.LLM_RERANK_RETRY_MAX_DELAY_SECONDS
    repository_context_path: Path | None = Defaults.LLM_RERANK_REPOSITORY_CONTEXT_PATH
    repository_context_max_chars: int = Defaults.LLM_RERANK_REPOSITORY_CONTEXT_MAX_CHARS
