from __future__ import annotations

from dataclasses import dataclass

from ..settings import Defaults


@dataclass(slots=True)
class LlmRerankConfig:
    candidate_limit: int = Defaults.LLM_RERANK_CANDIDATE_LIMIT
    rerank_limit: int = 0
    max_preview_chars: int = Defaults.LLM_RERANK_MAX_PREVIEW_CHARS
    mode: str = Defaults.LLM_RERANK_MODE
    include_reasons: bool = Defaults.LLM_RERANK_INCLUDE_REASONS
    preserve_top_candidate: bool = Defaults.LLM_RERANK_PRESERVE_TOP_CANDIDATE
    preserve_top_score_margin: float = Defaults.LLM_RERANK_PRESERVE_TOP_SCORE_MARGIN
    retry_attempts: int = Defaults.LLM_RERANK_RETRY_ATTEMPTS
    retry_base_delay_seconds: float = Defaults.LLM_RERANK_RETRY_BASE_DELAY_SECONDS
    retry_max_delay_seconds: float = Defaults.LLM_RERANK_RETRY_MAX_DELAY_SECONDS
