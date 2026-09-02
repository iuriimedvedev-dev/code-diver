# Final Verification Report

## Audit Metadata

- Repository: `/Users/iurii.medvedev/Work/code-diver`
- Verification date: 2026-09-02
- Scope: final verification of multi-query union-rerank implementation
- Report file: `docs/FINAL_VERIFICATION_REPORT.md`

## `pyproject.toml` diff

`git diff pyproject.toml` result: clean. The command returned no output.

## `multi_query_config.py`

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

## `config_loader.py (relevant excerpt)`

```python
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

## `defaults.py`

Relevant defaults file path: `src/code_diver/settings/defaults.py`.

```python
    # 0 = no cap. When capped, the sub-floor candidates the base fusion ranked highest win.
    CROSS_ENCODER_RERANK_SECOND_PASS_CANDIDATE_CAP = 0
    MULTI_QUERY_UNION_RERANK = False
    GRAPH_EXPANSION_DEPTH = 0
    GRAPH_NEIGHBOR_LIMIT = 0
```

## `multi_query_rrf_strategy.py`

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

## `retrieval_strategy_factory.py`

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
            # CROSS_ENCODER_RERANK sits on plain hybrid, so swapping to it from the
            # champion would change the base *and* the reranker and leave neither attributable.
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

## `test_multi_query_union_rerank.py`

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, Mock, call, patch

import pytest

from code_diver.config import AppConfig, MultiQueryConfig
from code_diver.domain import CodeItem, SearchResult
from code_diver.strategies.cross_encoder_rerank_retrieval_strategy import (
    CrossEncoderRerankRetrievalStrategy,
)
from code_diver.strategies.graph_file_retrieval_strategy import GraphFileRetrievalStrategy
from code_diver.strategies.multi_query_rrf_strategy import MultiQueryRrfStrategy
from code_diver.strategies.retrieval_strategy import RetrievalStrategy
from code_diver.strategies.retrieval_strategy_factory import RetrievalStrategyFactory

pytestmark = pytest.mark.unit


def _result(path: str, score: float = 1.0) -> SearchResult:
    return SearchResult(CodeItem(id=path, path=path, title=path, content=""), score)


def _factory_config(tmp_path: Path, *, union_rerank: bool) -> AppConfig:
    return AppConfig(
        root=tmp_path,
        multi_query=MultiQueryConfig(enabled=True, union_rerank=union_rerank),
    )


def test_multi_query_config_union_rerank_defaults_to_false() -> None:
    config = MultiQueryConfig()

    assert config.enabled is False
    assert config.union_rerank is False


def test_factory_keeps_cross_encoder_inside_multi_query_by_default(tmp_path: Path) -> None:
    config = _factory_config(tmp_path, union_rerank=False)
    provider = Mock()
    vector_store = Mock()

    with patch(
        "code_diver.strategies.retrieval_strategy_factory.RerankProviderFactory.create",
        return_value=Mock(name="rerank_provider"),
    ):
        strategy = RetrievalStrategyFactory().create(
            "graph_file_cross_encoder", config, provider, vector_store
        )

    assert isinstance(strategy, MultiQueryRrfStrategy)
    assert isinstance(strategy.underlying, CrossEncoderRerankRetrievalStrategy)
    assert isinstance(strategy.underlying.base_strategy, GraphFileRetrievalStrategy)
    assert strategy.fusion_pool_size is None


def test_factory_union_rerank_wraps_multi_query_before_one_cross_encoder(tmp_path: Path) -> None:
    config = _factory_config(tmp_path, union_rerank=True)
    config.cross_encoder_rerank.candidate_limit = 7

    with patch(
        "code_diver.strategies.retrieval_strategy_factory.RerankProviderFactory.create",
        return_value=MagicMock(name="rerank_provider"),
    ):
        strategy = RetrievalStrategyFactory().create(
            "graph_file_cross_encoder", config, Mock(), Mock()
        )

    assert isinstance(strategy, CrossEncoderRerankRetrievalStrategy)
    assert isinstance(strategy.base_strategy, MultiQueryRrfStrategy)
    assert not isinstance(strategy.base_strategy.underlying, CrossEncoderRerankRetrievalStrategy)
    assert isinstance(strategy.base_strategy.underlying, GraphFileRetrievalStrategy)
    assert strategy.base_strategy.fusion_pool_size == config.cross_encoder_rerank.candidate_limit


def test_rrf_overfetches_each_variant_and_respects_effective_limit() -> None:
    underlying = MagicMock(spec=RetrievalStrategy)
    underlying.search.side_effect = lambda query, limit: {
        "query": [_result("a"), _result("b"), _result("c")][:limit],
        "rewrite": [_result("d"), _result("e"), _result("f")][:limit],
    }[query]
    generator = Mock()
    generator.variants.return_value = ["query", "rewrite"]
    strategy = MultiQueryRrfStrategy(
        underlying,
        MultiQueryConfig(parallel_variants=False),
        generator=generator,
        fusion_pool_size=3,
    )

    results = strategy.search("query", 1)

    assert underlying.search.call_args_list == [
        call("query", 3),
        call("rewrite", 3),
    ]
    assert len(results) == 3


def test_rrf_without_fusion_pool_requests_exact_limit() -> None:
    underlying = MagicMock(spec=RetrievalStrategy)
    underlying.search.side_effect = lambda query, limit: [_result(query)][:limit]
    generator = Mock()
    generator.variants.return_value = ["query", "rewrite"]
    strategy = MultiQueryRrfStrategy(
        underlying,
        MultiQueryConfig(parallel_variants=False),
        generator=generator,
    )

    results = strategy.search("query", 2)

    assert underlying.search.call_args_list == [
        call("query", 2),
        call("rewrite", 2),
    ]
    assert len(results) == 2


def test_factory_disabled_multi_query_is_bit_exact_passthrough(tmp_path: Path) -> None:
    config = AppConfig(root=tmp_path, multi_query=MultiQueryConfig(enabled=False))
    base = Mock(spec=RetrievalStrategy)
    factory = RetrievalStrategyFactory()

    with patch.object(factory, "_create_base", return_value=base) as create_base:
        result = factory.create("vector", config, Mock(), Mock())

    assert result is base
    assert not isinstance(result, MultiQueryRrfStrategy)
    create_base.assert_called_once()
```

## `h84v2 arm config`

```yaml
# H-66b Champion: best-measured WHERE arm.
# Promoted to champion on 2026-08-31.
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

## Full test run output

Command used: `uv run --no-sync pytest tests/unit -v 2>&1 | tail -150`

Result: failed, with 1 failed and 1372 passed.

```text
tests/unit/test_sentence_transformers_embedding_provider.py::test_embedding_text_truncation_falls_back_to_conservative_character_limit PASSED [ 95%]
tests/unit/test_sentence_transformers_embedding_provider.py::test_sentence_transformers_provider_truncates_dense_punctuation_within_limit PASSED [ 95%]
tests/unit/test_sentence_transformers_embedding_provider.py::test_sentence_transformers_provider_truncates_generics_like_text_within_limit PASSED [ 96%]
tests/unit/test_sentence_transformers_embedding_provider.py::test_sentence_transformers_provider_keeps_short_text_unchanged PASSED [ 96%]
tests/unit/test_sentence_transformers_embedding_provider.py::test_sentence_transformers_retries_only_overflowing_item PASSED [ 96%]
tests/unit/test_sentence_transformers_embedding_provider.py::test_sentence_transformers_retry_stops_when_input_cannot_shrink PASSED [ 96%]
tests/unit/test_symbol_chunk_item_builder.py::test_builder_emits_a_point_per_type_and_public_callable PASSED [ 96%]
tests/unit/test_symbol_chunk_item_builder.py::test_chunk_keeps_the_full_file_path_so_dedup_and_path_scoring_still_work PASSED [ 96%]
tests/unit/test_symbol_chunk_item_builder.py::test_chunk_text_leads_with_the_symbol_identity_split_into_words PASSED [ 96%]
tests/unit/test_symbol_chunk_item_builder.py::test_chunk_text_uses_the_first_kdoc_sentence_as_purpose PASSED [ 96%]
tests/unit/test_symbol_chunk_item_builder.py::test_chunk_text_stays_inside_the_embedding_budget PASSED [ 96%]
tests/unit/test_symbol_chunk_item_builder.py::test_small_files_produce_no_chunks PASSED [ 96%]
tests/unit/test_symbol_chunk_item_builder.py::test_private_and_trivial_accessors_are_skipped PASSED [ 96%]
tests/unit/test_symbol_chunk_item_builder.py::test_chunks_per_file_are_capped PASSED [ 96%]
tests/unit/test_symbol_chunk_item_builder.py::test_non_source_files_produce_no_chunks PASSED [ 96%]
tests/unit/test_tool_observation_compressor.py::test_tool_observation_compressor_parses_json_and_drops_raw_matches PASSED [ 97%]
tests/unit/test_tool_observation_compressor.py::test_tool_observation_compressor_drops_nested_matches_in_lists_and_sections PASSED [ 97%]
tests/unit/test_tool_observation_compressor.py::test_tool_observation_compressor_keeps_non_json_content PASSED [ 97%]
tests/unit/test_tool_services.py::test_path_guard_accepts_relative_and_absolute_paths_inside_root PASSED [ 97%]
tests/unit/test_tool_services.py::test_path_guard_rejects_parent_traversal_and_absolute_escape PASSED [ 97%]
tests/unit/test_tool_services.py::test_tree_service_respects_gitignore_extra_excludes_depth_and_limit PASSED [ 97%]
tests/unit/test_tool_services.py::test_tree_service_file_path_returns_empty_structured_tree PASSED [ 97%]
tests/unit/test_tool_services.py::test_grep_service_python_backend_returns_structured_matches_without_text_by_default PASSED [ 97%]
tests/unit/test_tool_services.py::test_grep_service_python_backend_supports_regex_and_include_text PASSED [ 97%]
tests/unit/test_tool_services.py::test_grep_service_invalid_regex_fails_fast_in_python_backend PASSED [ 97%]
tests/unit/test_tool_services.py::test_rg_service_python_fallback_returns_regex_metadata_and_limits PASSED [ 97%]
tests/unit/test_tool_services.py::test_read_excerpt_service_bounds_lines_and_reports_truncation PASSED [ 97%]
tests/unit/test_tool_services.py::test_read_excerpt_service_rejects_ignored_missing_directory_and_large_files PASSED [ 97%]
tests/unit/test_tool_services.py::test_file_outline_service_returns_imports_symbols_and_candidates PASSED [ 97%]
tests/unit/test_tool_services.py::test_symbols_service_supports_fuzzy_symbol_definition_query PASSED [ 97%]
tests/unit/test_trace_logger.py::test_trace_logger_instances_share_artifact_lock PASSED [ 98%]
tests/unit/test_trace_monitor.py::test_trace_monitor_resets_offset_when_trace_file_is_truncated PASSED [ 98%]
tests/unit/test_trace_monitor.py::test_trace_monitor_resets_when_trace_file_is_replaced_with_larger_file PASSED [ 98%]
tests/unit/test_train_ltr_ranker.py::test_ndcg_rewards_a_relevant_file_placed_first PASSED [ 98%]
tests/unit/test_train_ltr_ranker.py::test_recall_counts_only_the_relevant_files_inside_the_cut PASSED [ 98%]
tests/unit/test_train_ltr_ranker.py::test_loading_a_dump_exported_with_other_features_is_refused PASSED [ 98%]
tests/unit/test_train_ltr_ranker.py::test_training_writes_a_loadable_artifact_and_holds_out_whole_queries PASSED [ 98%]
tests/unit/test_transient_generation_retry.py::test_transient_generation_retry_retries_rate_limits PASSED [ 98%]
tests/unit/test_transient_generation_retry.py::test_transient_generation_retry_respects_retry_after_header PASSED [ 98%]
tests/unit/test_transient_generation_retry.py::test_transient_generation_retry_does_not_retry_bad_requests PASSED [ 98%]
tests/unit/test_unjudgeable_row_policy.py::test_row_with_nonempty_prediction_and_no_error_is_judgeable PASSED [ 99%]
tests/unit/test_unjudgeable_row_policy.py::test_empty_prediction_is_unjudgeable_with_empty_prediction_reason PASSED [ 99%]
tests/unit/test_unjudgeable_row_policy.py::test_missing_prediction_key_is_unjudgeable PASSED [ 99%]
tests/unit/test_unjudgeable_row_policy.py::test_errored_row_is_unjudgeable_with_generation_error_reason_even_with_a_prediction PASSED [ 99%]
tests/unit/test_unjudgeable_row_policy.py::test_error_takes_precedence_over_empty_prediction_reason PASSED [ 99%]
tests/unit/test_unjudgeable_row_policy.py::test_falsy_error_value_does_not_make_a_row_unjudgeable PASSED [ 99%]
tests/unit/test_unjudgeable_row_policy.py::test_synthesized_judgment_zeroes_every_canonical_criterion PASSED [ 99%]
tests/unit/test_unjudgeable_row_policy.py::test_synthesized_judgment_sets_overall_zero_and_empty_answer_one PASSED [ 99%]
tests/unit/test_unjudgeable_row_policy.py::test_synthesized_judgment_is_flagged_and_carries_its_reason PASSED [ 99%]
tests/unit/test_unjudgeable_row_policy.py::test_synthesized_judgment_reports_no_usage_and_no_model PASSED [ 99%]
tests/unit/test_validate_eval_dataset.py::test_validate_eval_dataset_reports_errors_and_warnings FAILED [ 99%]
tests/unit/test_vertex_batch_test_service.py::test_vertex_batch_jsonl_builder_writes_gemini_batch_request PASSED [ 99%]
tests/unit/test_vertex_batch_test_service.py::test_vertex_batch_test_service_dry_run_writes_local_jsonl PASSED [ 99%]
tests/unit/test_vertex_batch_test_service.py::test_vertex_batch_test_service_submit_uploads_and_creates_job PASSED [ 99%]
tests/unit/test_vertex_batch_test_service.py::test_vertex_batch_test_service_submit_requires_gcs_prefix PASSED [ 99%]
tests/unit/test_vertex_providers.py::test_vertex_generation_provider_reuses_json_generation_contract PASSED [100%]
tests/unit/test_vertex_providers.py::test_vertex_embedding_provider_reuses_embedding_2_contract PASSED [100%]

=================================== FAILURES ===================================
____________ test_validate_eval_dataset_reports_errors_and_warnings ___________

tmp_path = PosixPath('/private/var/folders/_c/v962_6qd7f128tgcbwn5phc00000gn/T/pytest-of-iurii.medvedev/pytest-442/test_validate_eval_dataset_rep0')

    def test_validate_eval_dataset_reports_errors_and_warnings(tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        (root / "src").mkdir()
        (root / "src" / "UserService.kt").write_text("class UserService", encoding="utf-8")
        (root / "src" / "OtherService.kt").write_text("class OtherService", encoding="utf-8")
        dataset = tmp_path / "eval.jsonl"
        dataset.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "id": "case",
                            "query": "where is user service",
                            "expected": ["src/UserService.kt", "glob:**/*Service.kt"],
                        }
                    ),
                    json.dumps({"id": "case", "query": "duplicate", "expected": ["src/Missing.kt"]}),
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        completed = subprocess.run(
            [
                "uv",
                "run",
                "python",
                "scripts/validate_eval_dataset.py",
                str(dataset),
                "--root",
                str(root),
                "--max-glob-matches",
                "1",
            ],
            cwd=Path(__file__).resolve().parents[2],
            text=True,
            capture_output=True,
            check=False,
        )

        assert completed.returncode == 1
>       payload = json.loads(completed.stdout)
E       json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)

../../.local/share/uv/python/cpython-3.12.12-macos-aarch64-none/lib/python3.12/json/__init__.py:346: in loads
    return _default_decoder.decode(s)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^
../../.local/share/uv/python/cpython-3.12.12-macos-aarch64-none/lib/python3.12/json/decoder.py:338: in decode
    return self.raw_decode(s, idx=_w(s, 0).end())
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
 ../../.local/share/uv/python/cpython-3.12.12-macos-aarch64-none/lib/python3.12/json/decoder.py:356: in raw_decode
     obj, end = self.scan_once(s, idx)
                ^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

self = <json.decoder.JSONDecoder object at 0x1018c6ae0>, s = '', idx = 0

    def raw_decode(self, s, idx=0):
        """Decode a JSON document from ``s`` (a ``str`` beginning with
        a JSON document) and return a 2-tuple of the Python
        representation and the index where the document ended.

        This can be used to decode a JSON document from a string that has
        extraneous data at the end.
        """

        try:
            obj, end = self.scan_once(s, idx)
        except StopIteration as err:
            raise JSONDecodeError("Expecting value", s, err.value) from None
E           json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
../../.local/share/uv/python/cpython-3.12.12-macos-aarch64-none/lib/python3.12/json/decoder.py:356: in raw_decode
    raise JSONDecodeError("Expecting value", s, err.value) from None
json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
=============================== warnings summary ===============================
tests/unit/test_train_ltr_ranker.py::test_training_writes_a_loadable_artifact_and_holds_out_whole_queries
tests/unit/test_train_ltr_ranker.py::test_training_writes_a_loadable_artifact_and_holds_out_whole_queries
tests/unit/test_train_ltr_ranker.py::test_training_writes_a_loadable_artifact_and_holds_out_whole_queries
tests/unit/test_train_ltr_ranker.py::test_training_writes_a_loadable_artifact_and_holds_out_whole_queries
  /Users/iurii.medvedev/Work/code-diver/.venv/lib/python3.12/site-packages/joblib/numpy_pickle.py:207: DeprecationWarning: Setting the shape on a NumPy array has been deprecated. In NumPy 2.5.
  As an alternative, you can create a new view using np.reshape (with copy=False) instead.
    array.shape = shape

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/unit/test_validate_eval_dataset.py::test_validate_eval_dataset_reports_errors_and_warnings
================= 1 failed, 1372 passed, 4 warnings in 13.46s ==================
```

## Final Worktree Verification

Only `docs/FINAL_VERIFICATION_REPORT.md` was created. No source, test, config, or `pyproject.toml` files were modified.
