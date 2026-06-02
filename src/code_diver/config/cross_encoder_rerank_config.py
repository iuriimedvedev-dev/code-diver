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
