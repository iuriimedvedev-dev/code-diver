from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain import SearchResult
from .answer_context import AnswerContext


@dataclass(slots=True)
class AnswerOutcome:
    """One answered question, before anyone decides whether it was any good.

    The evaluator derives every metric from these fields, and the product surfaces read the
    same object. Anything an eval needs but a product does not (expected paths, reference
    answers, judge verdicts) stays out — this is the answering result, not a scored row.
    """

    question: str
    answer: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    confidence: float | None = None
    search_results: list[SearchResult] = field(default_factory=list)
    retrieved_files: list[str] = field(default_factory=list)
    context: AnswerContext | None = None
    query_plan: dict[str, Any] = field(default_factory=dict)
    raw_prediction: str = ""
    generation_model: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    planning_usage: dict[str, int] | None = None
    planning_model: str | None = None
    rerank_usage: dict[str, int] | None = None
    rerank_model: str | None = None
    retrieval_duration_ms: float = 0.0
    context_duration_ms: float = 0.0
    generation_duration_ms: float = 0.0
    # Set when the model replied but the reply was not parseable JSON. The evaluator turns
    # this into a parse-failure row; a product surface should show the raw text and say so.
    parse_error: str | None = None
