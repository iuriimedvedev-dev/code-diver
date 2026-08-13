from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import AppConfig
from ..generation import GenerationProvider
from ..strategies import RetrievalStrategy
from .answer_candidate_reranker import AnswerCandidateReranker
from .answer_context_builder import AnswerContextBuilder
from .answer_query_planner import AnswerQueryPlanner


@dataclass(frozen=True, slots=True)
class AnswerPipeline:
    """Everything needed to answer a question, already wired.

    `config` is returned deliberately: building the repository context can back-fill
    `llm_rerank.repository_context_path`, and a factory that mutated the caller's config in
    place is how that back-fill became invisible in the first place. Callers must use this
    config from here on, not the one they passed in.
    """

    config: AppConfig
    embedding_provider: Any
    retrieval_strategy: RetrievalStrategy
    answer_provider: GenerationProvider
    context_builder: AnswerContextBuilder
    repository_context: str = ""
    # The RepositoryContextResult itself: reports record its mode and char count.
    repository_context_result: Any | None = None
    query_planner: AnswerQueryPlanner | None = None
    query_retrieval_strategy: RetrievalStrategy | None = None
    query_result_reranker: AnswerCandidateReranker | None = None
    # The probe strategy actually in force, after the nested-rerank substitution.
    query_search_strategy: str | None = None
    limit: int = 10
    context_files: int = 8
    query_workers: int = 4
