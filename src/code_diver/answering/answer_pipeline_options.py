from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AnswerPipelineOptions:
    """Knobs that used to live only on the `evaluate-answers` argparse namespace.

    Every field defaults to "ask the config", so a caller that constructs
    AnswerPipelineOptions() gets exactly the pipeline the config declares. The eval CLI
    passes overrides; product front-ends normally pass none. That asymmetry is the point:
    before this existed, the pipeline could only be expressed as command-line flags, which
    is why no product path could reproduce it.
    """

    # None means "take config.evaluation.limit".
    limit: int | None = None
    # None means "take default_answer_context_files(config)".
    context_files: int | None = None
    context_lines: int = 160
    agentic_queries: bool = False
    agentic_query_rerank: bool = False
    # None means "reuse the configured search strategy for probe queries".
    agentic_query_search_strategy: str | None = None
    query_count: int = 4
    query_workers: int = 4
