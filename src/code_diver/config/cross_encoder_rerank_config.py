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
    # H-79: how many leading base candidates preserve_top_candidate protects. 1 keeps the
    # historical top-1-only behaviour, so the option is off by default.
    preserve_top_depth: int = Defaults.CROSS_ENCODER_RERANK_PRESERVE_TOP_DEPTH
    skip_when_top_margin_at_least: float | None = Defaults.CROSS_ENCODER_RERANK_SKIP_WHEN_TOP_MARGIN_AT_LEAST
    widen_when_uncertain_enabled: bool = Defaults.CROSS_ENCODER_RERANK_WIDEN_WHEN_UNCERTAIN_ENABLED
    widen_candidate_limit: int = Defaults.CROSS_ENCODER_RERANK_WIDEN_CANDIDATE_LIMIT
    widen_margin_check_rank: int = Defaults.CROSS_ENCODER_RERANK_WIDEN_MARGIN_CHECK_RANK
    widen_score_margin_below: float = Defaults.CROSS_ENCODER_RERANK_WIDEN_SCORE_MARGIN_BELOW
    use_file_head_document: bool = Defaults.CROSS_ENCODER_RERANK_USE_FILE_HEAD_DOCUMENT
    # H-62: scan entire file for ALL KDocs, method signatures, class declarations, pick best content.
    use_enhanced_file_document: bool = Defaults.CROSS_ENCODER_RERANK_USE_ENHANCED_FILE_DOCUMENT
    # H-57: LLM-generated purpose blurb (1-2 sentences) from the source file.
    use_llm_purpose_document: bool = Defaults.CROSS_ENCODER_RERANK_USE_LLM_PURPOSE_DOCUMENT
    # H-82: rank by the raw model logit (inverse sigmoid of the provider probability) instead
    # of the sigmoid-squashed score. Off by default -- reproduces the provider order exactly.
    rank_by_raw_logits: bool = Defaults.CROSS_ENCODER_RERANK_RANK_BY_RAW_LOGITS
    # H-82: when CE scores are equal within tie_break_epsilon, order the tied candidates by the
    # incoming fused base score instead of arbitrary provider/insertion order.
    tie_break_by_fused_score: bool = Defaults.CROSS_ENCODER_RERANK_TIE_BREAK_BY_FUSED_SCORE
    tie_break_epsilon: float = Defaults.CROSS_ENCODER_RERANK_TIE_BREAK_EPSILON
    # H-83: second CE pass with second_pass_max_document_chars, only for candidates the first
    # pass scored below second_pass_score_floor; the final score is max(first, second).
    second_pass_enabled: bool = Defaults.CROSS_ENCODER_RERANK_SECOND_PASS_ENABLED
    second_pass_score_floor: float = Defaults.CROSS_ENCODER_RERANK_SECOND_PASS_SCORE_FLOOR
    second_pass_max_document_chars: int = Defaults.CROSS_ENCODER_RERANK_SECOND_PASS_MAX_DOCUMENT_CHARS
    # Latency guard for the second pass: 0 = no cap; otherwise only the capped number of
    # sub-floor candidates (best base-fusion ranks first) are rescored.
    second_pass_candidate_cap: int = Defaults.CROSS_ENCODER_RERANK_SECOND_PASS_CANDIDATE_CAP
    # H-87: file-side hub prior (filename role + graph fan-in) folded into the CE ordering after
    # the second pass. Off by default -- the CE order is untouched. `additive` ranks by
    # ce_score + prior; `band` only reorders within runs of CE scores that lie within
    # hub_prior_band_width of each other (mirrors the H-82 tie-break grouping).
    hub_prior_enabled: bool = Defaults.CROSS_ENCODER_RERANK_HUB_PRIOR_ENABLED
    hub_prior_mode: str = Defaults.CROSS_ENCODER_RERANK_HUB_PRIOR_MODE
    hub_prior_role_weight: float = Defaults.CROSS_ENCODER_RERANK_HUB_PRIOR_ROLE_WEIGHT
    hub_prior_fanin_weight: float = Defaults.CROSS_ENCODER_RERANK_HUB_PRIOR_FANIN_WEIGHT
    hub_prior_band_width: float = Defaults.CROSS_ENCODER_RERANK_HUB_PRIOR_BAND_WIDTH
    hub_prior_protect_top: int = Defaults.CROSS_ENCODER_RERANK_HUB_PRIOR_PROTECT_TOP
    # H-90: dynamic protect_top based on CE margin. When > 0 and the gap between top-1 and
    # top-4 is >= this margin, protect only 1 instead of the configured protect_top.
    # 0.0 = off, use fixed hub_prior_protect_top.
    hub_prior_protect_margin: float = Defaults.CROSS_ENCODER_RERANK_HUB_PRIOR_PROTECT_MARGIN
    # H-91: CE-stage meta-ranker (LightGBM). When enabled, the learned model score replaces
    # the hub_prior additive formula. The model must be a LightGBM text file.
    ce_meta_ranker_enabled: bool = Defaults.CROSS_ENCODER_RERANK_CE_META_RANKER_ENABLED
    ce_meta_model_path: str = Defaults.CROSS_ENCODER_RERANK_CE_META_MODEL_PATH
