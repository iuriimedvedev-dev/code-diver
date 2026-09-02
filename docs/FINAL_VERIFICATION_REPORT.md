## multi_query_config.py

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MultiQueryConfig:
    """H-84: deterministic multi-query expansion with reciprocal-rank fusion.

    The original query is always retained and receives an optional score weight;
    generated variants are bounded and can be searched concurrently. Disabled by
    default so existing retrieval behavior is unchanged.
    """

    enabled: bool = False
    max_variants: int = 4
    rrf_k: int = 60
    original_query_weight: float = 2.0
    llm_rewrites_enabled: bool = False
    parallel_variants: bool = True
    max_variant_workers: int = 4
    union_rerank: bool = False
```

## config_loader.py (relevant excerpt)

```python
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from ..settings import Defaults
from .ai_index_config import AiIndexConfig
from .app_config import AppConfig
from .cross_encoder_rerank_config import CrossEncoderRerankConfig
from .editor_config import EditorConfig
from .embedding_config import EmbeddingConfig
from .env_file_config import EnvFileConfig
from .evaluation_config import EvaluationConfig
from .experiment_hypothesis_config import ExperimentHypothesisConfig
from .experiments_config import ExperimentsConfig
from .fan_out_fusion_config import FanOutFusionConfig
from .generation_config import GenerationConfig
from .graph_config import GraphConfig
from .graph_file_search_config import GraphFileSearchConfig
from .hybrid_search_config import HybridSearchConfig
from .indexing_config import IndexingConfig
from .llm_rerank_config import LlmRerankConfig
from .metrics_config import MetricsConfig
from .multi_query_config import MultiQueryConfig
from .pi_config import PiConfig
from .pi_repo_context_config import PiRepoContextConfig
from .qdrant_config import QdrantConfig
from .recursive_search_config import RecursiveSearchConfig
from .scanner_config import ScannerConfig
from .search_config import SearchConfig
from .storage_config import StorageConfig
from .trace_config import TraceConfig
from .ui_config import UiConfig
```

```python
    def load(self, path: Path | None) -> AppConfig:
        config_path = path or Defaults.CONFIG_PATH
        data = self._load_yaml(config_path)
        generation = self._generation(data.get("generation"))
        graph_file_search = self._graph_file_search(data.get("graph_file_search"))
        hybrid_search = self._hybrid_search(data.get("hybrid_search"))
        llm_rerank = self._llm_rerank(data.get("llm_rerank"), generation=generation)
        cross_encoder_rerank = self._cross_encoder_rerank(data.get("cross_encoder_rerank"))
        multi_query = self._multi_query(data.get("multi_query"))
        return AppConfig(
            root=Path(data.get("root", Defaults.ROOT)),
            artifact=Path(data.get("artifact", Defaults.ARTIFACT)),
            env_file=self._env_file(data.get("env_file")),
            storage=self._storage(data.get("storage")),
            embedding=self._embedding(data.get("embedding")),
            generation=generation,
            indexing=self._indexing(data.get("indexing")),
            pi=self._pi(data.get("pi")),
            scanner=self._scanner(data.get("scanner")),
            search=self._search(data.get("search")),
            recursive_search=self._recursive_search(data.get("recursive_search")),
            graph_file_search=graph_file_search,
            hybrid_search=hybrid_search,
            llm_rerank=llm_rerank,
            cross_encoder_rerank=cross_encoder_rerank,
            multi_query=multi_query,
            graph=self._graph(data.get("graph")),
            trace=self._trace(data.get("trace")),
            ui=self._ui(data.get("ui")),
            evaluation=self._evaluation(data.get("evaluation")),
            experiments=self._experiments(
                data.get("experiments"),
                generation=generation,
                graph_file_search=graph_file_search,
                hybrid_search=hybrid_search,
                llm_rerank=llm_rerank,
                cross_encoder_rerank=cross_encoder_rerank,
            ),
            metrics=self._metrics(data.get("metrics")),
            plugins=self._string_list(data.get("plugins")),
        )
```

```python
    def _fan_out_fusion(self, data: Any) -> FanOutFusionConfig:
        mapping = self._mapping(data)
        base = FanOutFusionConfig()
        return FanOutFusionConfig(
            enabled=bool(mapping.get("enabled", base.enabled)),
            queries=int(mapping.get("queries", base.queries)),
            search_limit=int(mapping.get("search_limit", base.search_limit)),
            rrf_k=int(mapping.get("rrf_k", base.rrf_k)),
            rerank=bool(mapping.get("rerank", base.rerank)),
            rerank_pool=int(mapping.get("rerank_pool", base.rerank_pool)),
            monotonic=bool(mapping.get("monotonic", base.monotonic)),
            baseline_head=int(mapping.get("baseline_head", base.baseline_head)),
            union_rerank=bool(mapping.get("union_rerank", base.union_rerank)),
            union_candidate_limit=int(mapping.get("union_candidate_limit", base.union_candidate_limit)),
            probe_search_limit=int(mapping.get("probe_search_limit", base.probe_search_limit)),
            parallel_probes=bool(mapping.get("parallel_probes", base.parallel_probes)),
            max_probe_workers=int(mapping.get("max_probe_workers", base.max_probe_workers)),
        )

    def _multi_query(self, data: Any) -> MultiQueryConfig:
        mapping = self._mapping(data)
        base = MultiQueryConfig()
        return MultiQueryConfig(
            enabled=bool(mapping.get("enabled", base.enabled)),
            union_rerank=bool(mapping.get("union_rerank", base.union_rerank)),
            max_variants=int(mapping.get("max_variants", base.max_variants)),
            rrf_k=int(mapping.get("rrf_k", base.rrf_k)),
            original_query_weight=float(mapping.get("original_query_weight", base.original_query_weight)),
            llm_rewrites_enabled=bool(mapping.get("llm_rewrites_enabled", base.llm_rewrites_enabled)),
            parallel_variants=bool(mapping.get("parallel_variants", base.parallel_variants)),
            max_variant_workers=int(mapping.get("max_variant_workers", base.max_variant_workers)),
        )
```

## defaults.py (relevant excerpt or note)

The requested source file `src/code_diver/config/defaults.py` does not exist. No defaults excerpt was available at that exact path.

## multi_query_rrf_strategy.py

```python
from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol

from ..config.multi_query_config import MultiQueryConfig
from ..domain import SearchResult
from .retrieval_strategy import RetrievalStrategy

logger = logging.getLogger(__name__)

QUERY_ALIASES = {
    "go to declaration": "navigate to declaration",
    "find usages": "usage search",
    "find in path": "search in files",
    "search everywhere": "SearchEverywhere",
    "quick documentation": "quick doc",
    "live template": "template expansion",
    "intention actions": "intention quick fix",
    "tool window": "toolwindow",
    "version control": "vcs",
    "code folding": "collapse regions",
    "refactoring": "refactor",
    "implemented": "implementation",
    "managed": "management",
    "handled": "handling",
    "registered": "registration",
    "executed": "execution",
    "coordinated": "coordination",
    "created": "creation",
    "detected": "detection",
    "collected": "collection",
    "rename": "rename refactor",
    "settings": "options",
    "keymap": "keyboard shortcut",
    "completion": "code completion lookup",
    "inspections": "inspection highlighting",
    "debugger": "debug",
    "breakpoints": "breakpoint",
    "vcs": "version control",
    "terminal": "console terminal",
    "notification": "notification balloon",
    "indexing": "index dumb mode",
    "diff": "compare diff",
}

# Interrogative scaffolding stripped by statement normalization: question word,
# optional auxiliary, optional "i find", optional article.
_QUESTION_PREFIX = re.compile(
    r"^(?:where|how|what|which|who|why|when)\s+"
    r"(?:is|are|was|were|does|do|did|can|could|should|would|will)?\s*"
    r"(?:i\s+find\s+)?(?:the\s+|a\s+|an\s+)?",
    re.IGNORECASE,
)
_TRAILING_SCOPE = re.compile(r"\s+in the (?:codebase|code|project|ide)\s*$", re.IGNORECASE)
# Filler and generic verbs dropped before guessing a camelCase symbol from content words.
_SYMBOL_STOP_WORDS = {
    "a", "an", "and", "are", "can", "code", "does", "do", "find", "for", "how",
    "in", "is", "me", "of", "on", "project", "show", "the", "to", "what", "where",
    "which", "why", "with", "you",
    "collected", "coordinated", "created", "detected", "displayed", "done", "executed",
    "handled", "happen", "happens", "implemented", "managed", "registered", "shown",
    "supported", "used",
}


class MultiQueryVariantGenerator:
    def variants(self, query: str, max_variants: int) -> list[str]:
        if not query.strip():
            return []
        statement = self._statement(query)
        candidates = [query.strip(), statement, self._aliased(statement), self._symbol_guess(statement)]
        result: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            candidate = candidate.strip()
            key = candidate.casefold()
            if candidate and key not in seen:
                seen.add(key)
                result.append(candidate)
            if len(result) >= max(1, max_variants):
                break
        return result

    def _statement(self, query: str) -> str:
        statement = query.strip().rstrip("?").strip()
        statement = _QUESTION_PREFIX.sub("", statement)
        return _TRAILING_SCOPE.sub("", statement).strip()

    def _aliased(self, statement: str) -> str:
        result = statement
        for source, target in sorted(QUERY_ALIASES.items(), key=lambda pair: len(pair[0]), reverse=True):
            result = re.sub(rf"\b{re.escape(source)}\b", target, result, flags=re.IGNORECASE)
        return result

    def _symbol_guess(self, statement: str) -> str:
        """camelCase symbol guess: "extract method refactoring" -> "ExtractMethodRefactoring"."""
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_]*", statement)
        tokens = [token for token in tokens if token.casefold() not in _SYMBOL_STOP_WORDS]
        if len(tokens) < 2:
            return ""
        return "".join(token[:1].upper() + token[1:] for token in tokens[:4])


class QueryRewriter(Protocol):
    def rewrite(self, query: str, max_variants: int) -> list[str]:
        ...


class LlmQueryRewriter:
    def __init__(self, generation_provider: Any):
        self.generation_provider = generation_provider

    def rewrite(self, query: str, max_variants: int) -> list[str]:
        schema = {
            "type": "object",
            "properties": {"variants": {"type": "array", "items": {"type": "string"}}},
            "required": ["variants"],
            "additionalProperties": False,
        }
        prompt = f"Rewrite this code search query into up to {max_variants} distinct queries: {query}"
        try:
            response = self.generation_provider.generate_json(prompt, schema=schema)
            values = json.loads(response).get("variants", [])
            return [str(value) for value in values if isinstance(value, str)] if isinstance(values, list) else []
        except Exception:
            logger.warning("LLM multi-query rewrite failed", exc_info=True)
            return []


class MultiQueryRrfStrategy(RetrievalStrategy):
    def __init__(
        self,
        underlying: RetrievalStrategy,
        config: MultiQueryConfig,
        generator: MultiQueryVariantGenerator | None = None,
        llm_rewriter: QueryRewriter | None = None,
        fusion_pool_size: int | None = None,
    ):
        self.underlying = underlying
        self.config = config
        self.generator = generator or MultiQueryVariantGenerator()
        self.llm_rewriter = llm_rewriter
        self.fusion_pool_size = fusion_pool_size

    def search(self, query: str, limit: int) -> list[SearchResult]:
        effective_limit = (
            max(limit, self.fusion_pool_size)
            if self.fusion_pool_size is not None
            else limit
        )
        variants = self._variants(query)
        if len(variants) <= 1:
            return self.underlying.search(query, effective_limit)
        return self._fuse(self._run(variants, effective_limit), effective_limit)

    def _variants(self, query: str) -> list[str]:
        variants = self.generator.variants(query, self.config.max_variants)
        if (
            self.config.llm_rewrites_enabled
            and self.llm_rewriter is not None
            and len(variants) < max(1, self.config.max_variants)
        ):
            variants.extend(self.llm_rewriter.rewrite(query, self.config.max_variants))
        result: list[str] = []
        seen: set[str] = set()
        for variant in variants:
            key = variant.strip().casefold()
            if key and key not in seen:
                seen.add(key)
                result.append(variant.strip())
            if len(result) >= max(1, self.config.max_variants):
                break
        return result

    def _run(self, variants: list[str], limit: int) -> list[list[SearchResult]]:
        if self.config.parallel_variants:
            with ThreadPoolExecutor(max_workers=max(1, self.config.max_variant_workers)) as executor:
                return list(executor.map(lambda variant: self.underlying.search(variant, limit), variants))
        return [self.underlying.search(variant, limit) for variant in variants]

    def _fuse(self, ranked_lists: list[list[SearchResult]], limit: int) -> list[SearchResult]:
        """Path-level RRF: score(f) = sum(w_i / (rrf_k + rank_i(f))), variant 0 is the original query."""
        scores: dict[str, float] = {}
        representatives: dict[str, SearchResult] = {}
        for index, results in enumerate(ranked_lists):
            weight = self.config.original_query_weight if index == 0 else 1.0
            seen_paths: set[str] = set()
            rank = 0
            for result in results:
                path = result.item.path
                if path in seen_paths:
                    continue
                seen_paths.add(path)
                rank += 1
                representatives.setdefault(path, result)
                scores[path] = scores.get(path, 0.0) + weight / (self.config.rrf_k + rank)
        ordered = sorted(scores, key=lambda path: (scores[path], representatives[path].score, path), reverse=True)
        return [SearchResult(representatives[path].item, scores[path] + representatives[path].score * 1e-9) for path in ordered[:limit]]
```

## retrieval_strategy_factory.py

```python
from __future__ import annotations

from ..config import AppConfig
from ..config.rerank_generation_config import rerank_generation_config
from ..generation import create_generation_provider
from ..graph import CodeGraphStore
from ..orchestration import OrchestratedRetrievalStrategy
from ..providers import EmbeddingProvider
from ..reranking import RerankProviderFactory
from ..settings import RetrievalStrategyId
from ..store import VectorStore
from ..store.qdrant_vector_store import QdrantVectorStore
from ..tracing import TraceLogger
from .cross_encoder_rerank_retrieval_strategy import CrossEncoderRerankRetrievalStrategy
from .dual_collection_vector_retrieval_strategy import DualCollectionVectorRetrievalStrategy
from .graph_file_retrieval_strategy import GraphFileRetrievalStrategy
from .graph_retrieval_strategy import GraphRetrievalStrategy
from .hybrid_retrieval_strategy import HybridRetrievalStrategy
from .llm_rerank_retrieval_strategy import LlmRerankRetrievalStrategy
from .multi_index_vector_retrieval_strategy import MultiIndexVectorRetrievalStrategy
from .multi_query_rrf_strategy import LlmQueryRewriter, MultiQueryRrfStrategy
from .recursive_retrieval_strategy import RecursiveRetrievalStrategy
from .retrieval_strategy import RetrievalStrategy
from .vector_retrieval_strategy import VectorRetrievalStrategy


class RetrievalStrategyFactory:
    def _create_base(
        self,
        strategy: str,
        config: AppConfig,
        provider: EmbeddingProvider,
        vector_store: VectorStore,
    ) -> RetrievalStrategy:
        strategy_id = RetrievalStrategyId(strategy)
        vector = VectorRetrievalStrategy(provider, vector_store)
        if strategy_id is RetrievalStrategyId.ORCHESTRATED:
            return OrchestratedRetrievalStrategy(
                vector,
                vector_store,
                create_generation_provider(config),
                per_query_limit=config.search.limit,
                trace_logger=TraceLogger(config.trace),
            )
        if strategy_id is RetrievalStrategyId.VECTOR:
            return vector
        if strategy_id is RetrievalStrategyId.RECURSIVE:
            recursive = config.recursive_search
            return RecursiveRetrievalStrategy(
                vector,
                rounds=recursive.rounds,
                branch_limit=recursive.branch_limit,
                per_round_limit=recursive.limit,
            )
        if strategy_id is RetrievalStrategyId.GRAPH:
            graph = config.graph
            return GraphRetrievalStrategy(
                vector,
                CodeGraphStore(graph.artifact),
                expansion_depth=graph.expansion_depth,
                neighbor_limit=graph.neighbor_limit,
            )
        if strategy_id is RetrievalStrategyId.GRAPH_FILE:
            return self._create_graph_file_base(config, provider, vector_store)
        if strategy_id is RetrievalStrategyId.GRAPH_FILE_RERANK:
            return LlmRerankRetrievalStrategy(
                self._graph_file_strategy(config, provider, vector_store),
                create_generation_provider(self._rerank_generation_config(config)),
                config.llm_rerank,
                trace_logger=TraceLogger(config.trace),
            )
        if strategy_id is RetrievalStrategyId.GRAPH_FILE_CROSS_ENCODER:
            # Same base as GRAPH_FILE_RERANK, different rerank primitive. The existing
            # CROSS_ENCODER_RERANK sits on plain hybrid, so swapping to it from the champion
            # would change the base *and* the reranker and leave neither attributable.
            return self._cross_encoder_strategy(self._create_graph_file_base(config, provider, vector_store), config)
        if strategy_id is RetrievalStrategyId.HYBRID:
            return self._hybrid_strategy(config, provider, vector_store)
        if strategy_id is RetrievalStrategyId.HYBRID_RERANK:
            hybrid = self._hybrid_strategy(config, provider, vector_store)
            return LlmRerankRetrievalStrategy(
                hybrid,
                create_generation_provider(self._rerank_generation_config(config)),
                config.llm_rerank,
                trace_logger=TraceLogger(config.trace),
            )
        if strategy_id is RetrievalStrategyId.CROSS_ENCODER_RERANK:
            hybrid = HybridRetrievalStrategy(
                self._hybrid_vector_strategy(config, provider, vector_store),
                CodeGraphStore(config.graph.artifact),
                config.hybrid_search,
                trace_logger=TraceLogger(config.trace),
            )
            return CrossEncoderRerankRetrievalStrategy(
                hybrid,
                RerankProviderFactory().create(config.cross_encoder_rerank),
                config.cross_encoder_rerank,
                trace_logger=TraceLogger(config.trace),
                repository_root=config.root,
            )
        raise ValueError(f"Unknown retrieval strategy: {strategy}")

    def _create_graph_file_base(
        self,
        config: AppConfig,
        provider: EmbeddingProvider,
        vector_store: VectorStore,
    ) -> RetrievalStrategy:
        return GraphFileRetrievalStrategy(
            HybridRetrievalStrategy(
                self._hybrid_vector_strategy(config, provider, vector_store),
                CodeGraphStore(config.graph.artifact),
                config.hybrid_search,
                trace_logger=TraceLogger(config.trace),
            ),
            CodeGraphStore(config.graph.artifact),
            config.graph_file_search,
        )

    def create(
        self,
        strategy: str,
        config: AppConfig,
        provider: EmbeddingProvider,
        vector_store: VectorStore,
    ) -> RetrievalStrategy:
        if not config.multi_query.enabled:
            return self._create_base(strategy, config, provider, vector_store)
        rewriter = LlmQueryRewriter(create_generation_provider(config)) if config.multi_query.llm_rewrites_enabled else None
        if getattr(config.multi_query, "union_rerank", False) and RetrievalStrategyId(strategy) is RetrievalStrategyId.GRAPH_FILE_CROSS_ENCODER:
            pre_ce = MultiQueryRrfStrategy(
                self._create_graph_file_base(config, provider, vector_store),
                config.multi_query,
                llm_rewriter=rewriter,
                fusion_pool_size=config.cross_encoder_rerank.candidate_limit,
            )
            return self._cross_encoder_strategy(pre_ce, config)
        base = self._create_base(strategy, config, provider, vector_store)
        return MultiQueryRrfStrategy(base, config.multi_query, llm_rewriter=rewriter)

    def _cross_encoder_strategy(self, base: RetrievalStrategy, config: AppConfig) -> RetrievalStrategy:
        return CrossEncoderRerankRetrievalStrategy(
            base,
            RerankProviderFactory().create(config.cross_encoder_rerank),
            config.cross_encoder_rerank,
            trace_logger=TraceLogger(config.trace),
            repository_root=config.root,
        )

    def _rerank_generation_config(self, config: AppConfig) -> AppConfig:
        """Swap in `llm_rerank.generation` so the rerank stage can run its own model."""
        return rerank_generation_config(config)

    def _hybrid_vector_strategy(
        self,
        config: AppConfig,
        provider: EmbeddingProvider,
        vector_store: VectorStore,
    ) -> RetrievalStrategy:
        primary = self._single_vector_strategy(config, provider, vector_store)
        secondary_collection = (config.hybrid_search.secondary_collection or "").strip()
        if not secondary_collection:
            return primary
        secondary_store = self._secondary_vector_store(config, secondary_collection)
        secondary = self._single_vector_strategy(config, provider, secondary_store)
        return DualCollectionVectorRetrievalStrategy(
            primary,
            secondary,
            fusion=config.hybrid_search.secondary_collection_fusion,
            rrf_k=config.hybrid_search.secondary_collection_rrf_k,
        )

    def _single_vector_strategy(
        self,
        config: AppConfig,
        provider: EmbeddingProvider,
        vector_store: VectorStore,
    ) -> RetrievalStrategy:
        if config.hybrid_search.vector_kind_limits or config.hybrid_search.vector_kind_multipliers:
            return MultiIndexVectorRetrievalStrategy(
                provider,
                vector_store,
                config.hybrid_search.vector_kind_limits,
                config.hybrid_search.vector_kind_multipliers,
                config.hybrid_search.vector_kind_path_dedup,
            )
        return VectorRetrievalStrategy(provider, vector_store)

    def _secondary_vector_store(self, config: AppConfig, collection: str) -> VectorStore:
        qdrant = config.storage.qdrant
        return QdrantVectorStore(
            url=qdrant.url,
            location=qdrant.location,
            collection=collection,
            api_key=qdrant.api_key,
            api_key_env=qdrant.api_key_env,
            batch_size=qdrant.batch_size,
        )

    def _graph_file_strategy(
        self,
        config: AppConfig,
        provider: EmbeddingProvider,
        vector_store: VectorStore,
    ) -> RetrievalStrategy:
        return GraphFileRetrievalStrategy(
            self._hybrid_strategy(config, provider, vector_store),
            CodeGraphStore(config.graph.artifact),
            config.graph_file_search,
        )

    def _hybrid_strategy(
        self,
        config: AppConfig,
        provider: EmbeddingProvider,
        vector_store: VectorStore,
    ) -> RetrievalStrategy:
        return HybridRetrievalStrategy(
            self._hybrid_vector_strategy(config, provider, vector_store),
            CodeGraphStore(config.graph.artifact),
            config.hybrid_search,
            trace_logger=TraceLogger(config.trace),
        )
```
