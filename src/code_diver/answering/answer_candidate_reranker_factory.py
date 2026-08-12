from __future__ import annotations

from ..config import AppConfig
from ..config.rerank_generation_config import rerank_generation_config
from ..generation import GenerationProvider, create_generation_provider
from ..reranking import RerankProviderFactory
from ..settings import RetrievalStrategyId
from .answer_candidate_cross_encoder_reranker import AnswerCandidateCrossEncoderReranker
from .answer_candidate_reranker import AnswerCandidateReranker

# Strategies whose rerank stage is a cross-encoder rather than a generative model. The final
# candidate rerank in answer evaluation has to agree with `search.strategy`: probes run through
# `--agentic-query-search-strategy` and the configured strategy object is never used, so if this
# mapping did not exist, switching `search.strategy` to a cross-encoder variant would change
# nothing and the arm would silently re-measure the champion.
CROSS_ENCODER_STRATEGY_IDS = frozenset(
    {
        RetrievalStrategyId.CROSS_ENCODER_RERANK,
        RetrievalStrategyId.GRAPH_FILE_CROSS_ENCODER,
    }
)


class AnswerCandidateRerankerFactory:
    def create(
        self,
        config: AppConfig,
        answer_provider: GenerationProvider,
    ) -> AnswerCandidateReranker | AnswerCandidateCrossEncoderReranker:
        if self.is_cross_encoder(config):
            return AnswerCandidateCrossEncoderReranker(
                RerankProviderFactory().create(config.cross_encoder_rerank),
                config.cross_encoder_rerank,
            )
        return AnswerCandidateReranker(self._provider(config, answer_provider), config.llm_rerank)

    def is_cross_encoder(self, config: AppConfig) -> bool:
        try:
            strategy_id = RetrievalStrategyId(config.search.strategy)
        except ValueError:
            # An unknown strategy is the retrieval factory's error to raise, with its own message.
            return False
        return strategy_id in CROSS_ENCODER_STRATEGY_IDS

    def _provider(self, config: AppConfig, answer_provider: GenerationProvider) -> GenerationProvider:
        rerank_config = rerank_generation_config(config)
        # Identity means no override: reuse the answer provider rather than opening a second
        # client against the same endpoint.
        if rerank_config is config:
            return answer_provider
        return create_generation_provider(rerank_config)
