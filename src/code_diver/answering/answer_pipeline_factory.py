from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from ..config import AppConfig
from ..generation.generation_provider_factory import create_generation_provider
from ..inspection.exclude_patterns import inspection_exclude_patterns
from ..pi.repository_context_resolver import build_repository_context
from ..providers.embedding_provider_builder import make_embedding_provider
from ..settings import RetrievalStrategyId
from ..strategies.retrieval_strategy_builder import make_retrieval_strategy
from .answer_candidate_reranker_factory import AnswerCandidateRerankerFactory
from .answer_context_builder import AnswerContextBuilder
from .answer_pipeline import AnswerPipeline
from .answer_pipeline_options import AnswerPipelineOptions
from .answer_query_planner import AnswerQueryPlanner

NESTED_RERANK_NOTICE = (
    "Using hybrid probe search before the shared LLM rerank "
    "to avoid nested per-query reranking."
)


def search_uses_llm_rerank(config: AppConfig) -> bool:
    return config.search.strategy in {
        RetrievalStrategyId.HYBRID_RERANK.value,
        RetrievalStrategyId.GRAPH_FILE_RERANK.value,
    }


def default_answer_context_files(config: AppConfig) -> int:
    return 4 if search_uses_llm_rerank(config) else 8


class AnswerPipelineFactory:
    """Builds the answering pipeline from config plus explicit overrides.

    This assembly used to live inline in `cmd_evaluate_answers`, which meant the only way to
    construct it was to have an argparse namespace. Product paths could not, so they grew
    their own answering logic and the measured pipeline stopped describing the product.

    Judge construction stays out on purpose: a judge is a measurement instrument, never part
    of answering.
    """

    def create(
        self,
        config: AppConfig,
        vector_store: Any,
        options: AnswerPipelineOptions | None = None,
        on_notice: Callable[[str], None] | None = None,
    ) -> AnswerPipeline:
        options = options or AnswerPipelineOptions()
        limit = options.limit or config.evaluation.limit
        context_files = int(
            options.context_files or default_answer_context_files(config)
        )
        answer_provider = create_generation_provider(config)
        config, context_result, repository_context = self._with_repository_context(
            config, answer_provider
        )
        provider = make_embedding_provider(config, vector_store.metadata())
        strategy = make_retrieval_strategy(config, provider, vector_store)
        query_planner = (
            AnswerQueryPlanner(
                answer_provider,
                max_queries=options.query_count,
                repository_context=repository_context,
            )
            if options.agentic_queries
            else None
        )
        query_search_strategy = self._query_search_strategy(config, options, on_notice)
        query_retrieval_strategy = None
        if options.agentic_queries and query_search_strategy:
            query_config = replace(
                config, search=replace(config.search, strategy=query_search_strategy)
            )
            query_retrieval_strategy = make_retrieval_strategy(
                query_config, provider, vector_store
            )
        # Which primitive does the final rerank follows from `search.strategy`, not from the
        # probe strategy passed on the command line. Building it here rather than
        # hard-coding AnswerCandidateReranker is what makes a cross-encoder arm a config diff.
        query_result_reranker = (
            AnswerCandidateRerankerFactory().create(config, answer_provider)
            if options.agentic_queries and options.agentic_query_rerank
            else None
        )
        return AnswerPipeline(
            config=config,
            embedding_provider=provider,
            retrieval_strategy=strategy,
            answer_provider=answer_provider,
            context_builder=AnswerContextBuilder(
                config.root,
                max_files=context_files,
                lines_per_file=options.context_lines,
                exclude=inspection_exclude_patterns(config),
                max_file_bytes=config.scanner.max_file_bytes,
            ),
            repository_context=repository_context,
            repository_context_result=context_result,
            query_planner=query_planner,
            query_retrieval_strategy=query_retrieval_strategy,
            query_result_reranker=query_result_reranker,
            query_search_strategy=query_search_strategy,
            limit=limit,
            context_files=context_files,
            query_workers=options.query_workers,
        )

    def _with_repository_context(
        self, config: AppConfig, answer_provider: Any
    ) -> tuple[AppConfig, Any | None, str]:
        result = build_repository_context(config, answer_provider)
        if result is None:
            return config, None, ""
        repository_context = result.path.read_text(encoding="utf-8", errors="replace")
        if config.llm_rerank.repository_context_path is None:
            config = replace(
                config,
                llm_rerank=replace(
                    config.llm_rerank, repository_context_path=result.path
                ),
            )
        return config, result, repository_context

    def _query_search_strategy(
        self,
        config: AppConfig,
        options: AnswerPipelineOptions,
        on_notice: Callable[[str], None] | None,
    ) -> str | None:
        strategy_id = options.agentic_query_search_strategy
        if (
            options.agentic_queries
            and options.agentic_query_rerank
            and not strategy_id
            and config.search.strategy == RetrievalStrategyId.HYBRID_RERANK.value
        ):
            strategy_id = RetrievalStrategyId.HYBRID.value
            if on_notice is not None:
                on_notice(NESTED_RERANK_NOTICE)
        return strategy_id
