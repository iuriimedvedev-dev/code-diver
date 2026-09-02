## FILE: src/code_diver/config/multi_query_config.py
```
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

## FILE: src/code_diver/strategies/retrieval_strategy_factory.py
```
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
        strategy_id = RetrievalStrategyId(strategy)
        if getattr(config.multi_query, "union_rerank", False) and strategy_id is not RetrievalStrategyId.GRAPH_FILE_CROSS_ENCODER:
            raise ValueError("union_rerank requires the graph_file_cross_encoder retrieval strategy")
        if getattr(config.multi_query, "union_rerank", False) and strategy_id is RetrievalStrategyId.GRAPH_FILE_CROSS_ENCODER:
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

## FILE: src/code_diver/strategies/multi_query_rrf_strategy.py
```
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
        return self._fuse(self._run(variants, effective_limit), limit)

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
        pool_size = self.fusion_pool_size if self.fusion_pool_size is not None else limit
        return [SearchResult(representatives[path].item, scores[path] + representatives[path].score * 1e-9) for path in ordered[:pool_size]]
```

## FILE: configs/intellij/intellij-h84v2-union-rerank.yml
```
# H-84v2: pre-cross-encoder multi-query RRF, then one cross-encoder pass.
# Based on the H-66b champion search/index configuration.
#
# Metrics (IntelliJ Community):
# - WHERE-79: 0.5757-0.5905 recall@10 / 0.3630-0.3708 MRR
# - 1065: 0.8175 recall@10 (-0.0117 vs H46), 0.6376 hit@1 (+0.0113)
# - Workflow bucket: 0.8027 (best on record)
#
# NEW COLLECTION REQUIRED: build a new collection at index time. Changing purpose+terms content
# changes embedded/indexed content, so the H46 collection cannot be reused. The indexed file
# summary must use the purpose+terms section immediately after file/extension and
# before symbols, matching FileSummaryItemBuilder's file, extension, purpose+terms, symbols, imports order.
#
# H-66b budget: the embedder truncates at max_input_chars=500, so only the first lines reach the
# vector. This config enables file_summary_compact_budget: purpose+terms first, keyword/path noise
# dropped from terms, and the embedded file: line shortened to basename + last two segments.
# Weights are identical to H-66 -- only the collection, the suite label and the scanner flag differ.
#
# H46 is intentionally archived. This config copies its full schema and values, except for
# the experiment identifier and the collection name required by the changed indexed content.
root: ../intellij-community

storage:
  provider: qdrant
  qdrant:
    url: http://localhost:6333
    collection: intellij_h66b_budget_qwen
    batch_size: 1024

# Verbatim from intellij-postrank-h3-manifest.yml -- must match how the collection was built.
embedding:
  provider: openai_compatible
  model: mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ
  dimensions:
  url: http://127.0.0.1:8001/v1/embeddings
  api_key: local
  batch_size: 128
  workers: 4
  max_input_chars: 500

search:
  limit: 10
  preview_lines: 8
  strategy: graph_file_cross_encoder

multi_query:
  enabled: true
  union_rerank: true
  max_variants: 4
  rrf_k: 60
  original_query_weight: 2.0
  llm_rewrites_enabled: false
  parallel_variants: true
  max_variant_workers: 4

# Unused on the search axis (no generation), kept so the file loads standalone.
generation:
  provider: openai_compatible
  model: mlx-community/Qwen3.5-4B-OptiQ-4bit
  url: http://127.0.0.1:8012/v1/chat/completions
  api_key: local
  temperature: 0
  max_tokens: 2048
  timeout_ms: 240000

indexing:
  mode: scanner

# Verbatim from intellij-postrank-h3-manifest.yml. This collection must be re-indexed for
# the completed source reorder to change the summary content.
scanner:
  include:
    - README.md
    - CONTRIBUTING.md
    - build.gradle
    - build.gradle.kts
    - settings.gradle
    - settings.gradle.kts
    - "**/*.java"
    - "**/*.kt"
    - "**/*.kts"
    - "**/*.xml"
    - "**/*.properties"
    - "**/*.gradle"
    - "**/*.gradle.kts"
    - "**/*.md"
    - "**/*.json"
    - "**/*.yaml"
    - "**/*.yml"
  exclude:
    - .idea/**
    - .gradle/**
    - .ijwb/**
    - bazel-*/**
    - build/**
    - out/**
    - "**/build/**"
    - "**/out/**"
    - "**/test/**"
    - "**/tests/**"
    - "**/testData/**"
    - "**/testdata/**"
    - "**/generated/**"
    - "**/gen/**"
    - "**/.cache/**"
    - "**/node_modules/**"
  line_chunks: false
  structural_chunks: false
  symbol_chunks: false
  symbol_body: false
  file_summary_chunks: true
  file_manifest_chunks: true
  file_summary_compact_budget: true
  max_symbols_per_file: 96

# Champion weights, minus the doc_* kinds this collection does not contain.
hybrid_search:
  candidate_limit: 360
  lexical_candidate_limit: 1000
  vector_weight: 0.42
  lexical_weight: 0.26
  path_weight: 0.12
  symbol_weight: 0.10
  symbol_match_weight: 0.10
  graph_weight: 0.0
  file_vote_weight: 0.06
  graph_depth: 0
  graph_neighbor_limit: 0
  vector_kind_limits:
    file_summary: 170
    file_manifest: 170
  vector_kind_multipliers:
    file_summary: 1.0
    file_manifest: 1.08
  routing_enabled: true
  lexical_scoring: bm25
  fusion: weighted
  preserve_vector_top: true
  vector_top_score_margin: 0.03
  item_kind_weights:
    file_summary: 1.0
    file_manifest: 1.08
  min_token_length: 3

# Champion block, verbatim.
graph_file_search:
  seed_limit: 140
  lexical_seed_limit: 280
  vector_weight: 0.25
  lexical_weight: 0.25
  path_weight: 0.20
  symbol_weight: 0.10
  graph_weight: 0.0
  depth: 2
  neighbor_limit: 40
  decay: 0.65
  min_token_length: 3
  # H-77, promoted 2026-08-31. Candidates that reach _seed_scores through the vector lane
  # used to keep structural lexical/path/symbol zeros (they were simply absent from the
  # lexical seed top-280), capping them at vector_weight alone. Parity rescores them with the
  # same HybridCandidateScorer. WHERE-79 recall@10 0.5757 -> 0.6120, mech150 guard slice
  # 0.7977 -> 0.8381 with every mechanical bucket up, latency flat or better.
  seed_score_parity: true

# Champion block, verbatim. :8080 holds an unrelated jbcc-api listener on this machine, so
# the reranker is on :8081.
cross_encoder_rerank:
  provider: llama_cpp
  model: Qwen3-Reranker-0.6B
  url: http://127.0.0.1:8081/v1/rerank
  candidate_limit: 34
  max_document_chars: 850
  second_pass_enabled: true
  second_pass_score_floor: 0.3
  second_pass_max_document_chars: 2400
  second_pass_candidate_cap: 24
  preserve_top_candidate: true
  preserve_top_score_margin: 0.1
  timeout_ms: 60000

graph:
  enabled: true
  artifact: .code-diver/intellij-h37-jvm-graph.json
  ast_enabled: false
  reference_edges_enabled: false
  call_edges_enabled: false
  expansion_depth: 2
  neighbor_limit: 40

trace:
  enabled: false

evaluation:
  dataset: datasets/intellij_eval_1000.answer_sets.jsonl
  limit: 10
  workers: 1

experiments:
  suite: h84v2-union-rerank

metrics:
  enabled: false
```
