from __future__ import annotations

from dataclasses import dataclass

from ..settings import Defaults


@dataclass(slots=True)
class CrossEncoderRerankConfig:
    provider: str = Defaults.CROSS_ENCODER_RERANK_PROVIDER
    model: str = Defaults.CROSS_ENCODER_RERANK_MODEL
    url: str = Defaults.CROSS_ENCODER_RERANK_URL
    api_key: str | None = None
    candidate_limit: int = Defaults.CROSS_ENCODER_RERANK_CANDIDATE_LIMIT
    max_document_chars: int = Defaults.CROSS_ENCODER_RERANK_MAX_DOCUMENT_CHARS
    timeout_ms: int = Defaults.CROSS_ENCODER_RERANK_TIMEOUT_MS
    preserve_top_candidate: bool = Defaults.CROSS_ENCODER_RERANK_PRESERVE_TOP_CANDIDATE
    preserve_top_score_margin: float = Defaults.CROSS_ENCODER_RERANK_PRESERVE_TOP_SCORE_MARGIN
    skip_when_top_margin_at_least: float | None = Defaults.CROSS_ENCODER_RERANK_SKIP_WHEN_TOP_MARGIN_AT_LEAST
    widen_when_uncertain_enabled: bool = Defaults.CROSS_ENCODER_RERANK_WIDEN_WHEN_UNCERTAIN_ENABLED
    widen_candidate_limit: int = Defaults.CROSS_ENCODER_RERANK_WIDEN_CANDIDATE_LIMIT
    widen_margin_check_rank: int = Defaults.CROSS_ENCODER_RERANK_WIDEN_MARGIN_CHECK_RANK
    widen_score_margin_below: float = Defaults.CROSS_ENCODER_RERANK_WIDEN_SCORE_MARGIN_BELOW
    use_file_head_document: bool = Defaults.CROSS_ENCODER_RERANK_USE_FILE_HEAD_DOCUMENT
