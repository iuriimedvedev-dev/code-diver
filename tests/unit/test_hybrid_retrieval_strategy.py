from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from code_diver.config import HybridSearchConfig
from code_diver.config.trace_config import TraceConfig
from code_diver.domain import CodeItem, SearchResult
from code_diver.graph import CodeGraph, CodeGraphStore, GraphEdge
from code_diver.strategies import HybridRetrievalStrategy, RetrievalStrategy
from code_diver.strategies.hybrid_item_profiler import HybridItemProfiler
from code_diver.strategies.hybrid_lexical_index import HybridLexicalIndex
from code_diver.tracing import TraceLogger

pytestmark = pytest.mark.unit


class FakeRetrievalStrategy(RetrievalStrategy):
    def __init__(self, results: list[SearchResult]):
        self.results = results

    def search(self, query: str, limit: int) -> list[SearchResult]:
        return self.results[:limit]


def test_hybrid_strategy_promotes_lexically_relevant_item(tmp_path: Path) -> None:
    auth_item = CodeItem(
        id="src/auth.py#1",
        path="src/auth.py",
        title="src/auth.py",
        content="def authorize_user():\n    validate authorization token and permissions",
    )
    cli_item = CodeItem(
        id="src/cli.py#1",
        path="src/cli.py",
        title="src/cli.py",
        content="def main():\n    parse arguments",
    )
    graph_store = _graph_store(tmp_path, [auth_item, cli_item], [])
    vector = FakeRetrievalStrategy([SearchResult(cli_item, 0.99)])
    strategy = HybridRetrievalStrategy(
        vector,
        graph_store,
        HybridSearchConfig(
            candidate_limit=5,
            lexical_candidate_limit=5,
            vector_weight=0.1,
            lexical_weight=0.6,
            path_weight=0.3,
            symbol_weight=0.0,
            graph_weight=0.0,
            preserve_vector_top=False,
        ),
    )

    results = strategy.search("where is authorization handled?", limit=2)

    assert [result.item.path for result in results] == ["src/auth.py", "src/cli.py"]


def test_hybrid_strategy_adds_graph_neighbors(tmp_path: Path) -> None:
    command_item = CodeItem(
        id="src/commands.py#1",
        path="src/commands.py",
        title="create command",
        content="def create_command(): return StrategyCommand()",
    )
    strategy_item = CodeItem(
        id="src/strategies.py#1",
        path="src/strategies.py",
        title="strategy runner",
        content="class StrategyRunner: pass",
    )
    graph_store = _graph_store(
        tmp_path,
        [command_item, strategy_item],
        [GraphEdge(source=command_item.id, target=strategy_item.id, kind="calls", weight=0.9)],
    )
    vector = FakeRetrievalStrategy([SearchResult(command_item, 0.8)])
    strategy = HybridRetrievalStrategy(
        vector,
        graph_store,
        HybridSearchConfig(
            candidate_limit=5,
            lexical_candidate_limit=5,
            vector_weight=0.5,
            lexical_weight=0.0,
            path_weight=0.0,
            symbol_weight=0.0,
            graph_weight=0.5,
            graph_depth=1,
            graph_neighbor_limit=5,
        ),
    )

    results = strategy.search("where is the strategy run?", limit=2)

    assert [result.item.path for result in results] == ["src/commands.py", "src/strategies.py"]


def test_hybrid_strategy_can_expand_graph_by_file(tmp_path: Path) -> None:
    api_summary = CodeItem(
        id="api-summary",
        path="src/api.py",
        title="src/api.py",
        content="user api endpoint",
        metadata={"index_kind": "file_summary"},
    )
    api_symbol = CodeItem(
        id="api-symbol",
        path="src/api.py",
        title="src/api.py::create_user",
        content="create user calls service",
        metadata={"index_kind": "symbol", "symbol": "create_user"},
    )
    service_summary = CodeItem(
        id="service-summary",
        path="src/service.py",
        title="src/service.py",
        content="user service implementation",
        metadata={"index_kind": "file_summary"},
    )
    service_symbol = CodeItem(
        id="service-symbol",
        path="src/service.py",
        title="src/service.py::save_user",
        content="save user",
        metadata={"index_kind": "symbol", "symbol": "save_user"},
    )
    graph_store = _graph_store(
        tmp_path,
        [api_summary, api_symbol, service_summary, service_symbol],
        [GraphEdge(source=api_symbol.id, target=service_symbol.id, kind="calls", weight=0.9)],
    )
    strategy = HybridRetrievalStrategy(
        FakeRetrievalStrategy([SearchResult(api_summary, 0.9)]),
        graph_store,
        HybridSearchConfig(
            candidate_limit=5,
            lexical_candidate_limit=5,
            vector_weight=0.4,
            lexical_weight=0.0,
            path_weight=0.0,
            symbol_weight=0.0,
            graph_weight=0.6,
            graph_depth=1,
            graph_neighbor_limit=5,
            graph_scope="file",
            preserve_vector_top=False,
        ),
    )

    results = strategy.search("where does the api save user", limit=2)

    assert [result.item.path for result in results] == ["src/api.py", "src/service.py"]


def test_hybrid_strategy_applies_routed_graph_depth(tmp_path: Path) -> None:
    seed_item = CodeItem(
        id="src/commands.py#1",
        path="src/commands.py",
        title="command dispatcher",
        content="def dispatch_command(): return handler()",
    )
    handler_item = CodeItem(
        id="src/handlers.py#1",
        path="src/handlers.py",
        title="command handler",
        content="def handle_command(): return workflow()",
    )
    workflow_item = CodeItem(
        id="src/workflow.py#1",
        path="src/workflow.py",
        title="workflow runner",
        content="def workflow(): pass",
    )
    graph_store = _graph_store(
        tmp_path,
        [seed_item, handler_item, workflow_item],
        [
            GraphEdge(source=seed_item.id, target=handler_item.id, kind="calls", weight=0.9),
            GraphEdge(source=handler_item.id, target=workflow_item.id, kind="calls", weight=0.9),
        ],
    )
    strategy = HybridRetrievalStrategy(
        FakeRetrievalStrategy([SearchResult(seed_item, 0.8)]),
        graph_store,
        HybridSearchConfig(
            candidate_limit=5,
            lexical_candidate_limit=5,
            routing_enabled=True,
            vector_weight=0.1,
            lexical_weight=0.0,
            path_weight=0.0,
            symbol_weight=0.0,
            graph_weight=0.9,
            graph_depth=1,
            graph_neighbor_limit=5,
        ),
    )

    results = strategy.search("where is command created and dispatched", limit=3)

    assert "src/workflow.py" in [result.item.path for result in results]


def test_hybrid_lexical_index_bm25_prefers_rare_exact_terms() -> None:
    target = CodeItem(
        id="target",
        path="src/auth.py",
        title="auth",
        content="authorization authorization token validator",
    )
    generic = CodeItem(
        id="generic",
        path="src/misc.py",
        title="misc",
        content="authorization helper common common common common",
    )
    index = HybridLexicalIndex([target, generic], HybridItemProfiler())

    scores = index.bm25_scores(("authorization", "token"), k1=1.2, b=0.75)

    assert scores[target.id] > scores[generic.id]


def test_hybrid_strategy_can_use_bm25_rrf(tmp_path: Path) -> None:
    target = CodeItem(
        id="target",
        path="src/auth.py",
        title="auth token",
        content="authorization token validator",
    )
    vector_only = CodeItem(
        id="vector",
        path="src/vector.py",
        title="semantic neighbor",
        content="login flow",
    )
    graph_store = _graph_store(tmp_path, [target, vector_only], [])
    strategy = HybridRetrievalStrategy(
        FakeRetrievalStrategy([SearchResult(vector_only, 0.99)]),
        graph_store,
        HybridSearchConfig(
            candidate_limit=5,
            lexical_candidate_limit=5,
            vector_weight=0.2,
            lexical_weight=0.8,
            path_weight=0.0,
            symbol_weight=0.0,
            graph_weight=0.0,
            lexical_scoring="bm25",
            fusion="rrf",
            rrf_k=1,
            preserve_vector_top=False,
        ),
    )

    results = strategy.search("authorization token", limit=2)

    assert results[0].item.path == "src/auth.py"


def test_hybrid_strategy_applies_item_kind_weights(tmp_path: Path) -> None:
    chunk_item = CodeItem(
        id="chunk",
        path="src/auth.py",
        title="auth chunk",
        content="authorization token",
        metadata={"index_kind": "chunk"},
    )
    summary_item = CodeItem(
        id="summary",
        path="src/auth.py",
        title="auth summary",
        content="authorization token",
        metadata={"index_kind": "file_summary"},
    )
    graph_store = _graph_store(tmp_path, [chunk_item, summary_item], [])
    strategy = HybridRetrievalStrategy(
        FakeRetrievalStrategy([SearchResult(chunk_item, 0.9), SearchResult(summary_item, 0.9)]),
        graph_store,
        HybridSearchConfig(
            candidate_limit=5,
            lexical_candidate_limit=5,
            vector_weight=1.0,
            lexical_weight=0.0,
            path_weight=0.0,
            symbol_weight=0.0,
            graph_weight=0.0,
            item_kind_weights={"file_summary": 1.2, "chunk": 1.0},
        ),
    )

    results = strategy.search("authorization token", limit=2)

    assert results[0].item.id == "summary"


def test_hybrid_strategy_promotes_file_consensus(tmp_path: Path) -> None:
    vector_top = CodeItem(
        id="vector-top",
        path="src/other.py",
        title="other",
        content="authorization",
    )
    target_symbol = CodeItem(
        id="target-symbol",
        path="src/auth.py",
        title="AuthService",
        content="token validator",
    )
    target_summary = CodeItem(
        id="target-summary",
        path="src/auth.py",
        title="auth summary",
        content="authorization flow",
    )
    vector_floor = CodeItem(
        id="vector-floor",
        path="src/floor.py",
        title="floor",
        content="misc",
    )
    graph_store = _graph_store(tmp_path, [vector_top, target_symbol, target_summary, vector_floor], [])
    strategy = HybridRetrievalStrategy(
        FakeRetrievalStrategy(
            [
                SearchResult(vector_top, 0.99),
                SearchResult(target_symbol, 0.985),
                SearchResult(vector_floor, 0.9),
            ]
        ),
        graph_store,
        HybridSearchConfig(
            candidate_limit=5,
            lexical_candidate_limit=5,
            vector_weight=0.1,
            lexical_weight=0.1,
            path_weight=0.0,
            symbol_weight=0.0,
            graph_weight=0.0,
            file_vote_weight=0.8,
        ),
    )

    results = strategy.search("authorization token", limit=3)

    assert results[0].item.path == "src/auth.py"


def test_hybrid_strategy_applies_symbol_match_prior(tmp_path: Path) -> None:
    symbol_item = CodeItem(
        id="symbol",
        path="src/auth.py",
        title="src/auth.py::AuthTokenVerifier",
        content="class AuthTokenVerifier: pass",
        metadata={"index_kind": "symbol", "symbol": "AuthTokenVerifier"},
    )
    vector_item = CodeItem(
        id="vector",
        path="src/vector.py",
        title="semantic neighbor",
        content="auth token",
        metadata={"index_kind": "chunk"},
    )
    graph_store = _graph_store(tmp_path, [symbol_item, vector_item], [])
    strategy = HybridRetrievalStrategy(
        FakeRetrievalStrategy([SearchResult(vector_item, 0.99)]),
        graph_store,
        HybridSearchConfig(
            candidate_limit=5,
            lexical_candidate_limit=5,
            vector_weight=0.1,
            lexical_weight=0.0,
            path_weight=0.0,
            symbol_weight=0.0,
            symbol_match_weight=0.9,
            graph_weight=0.0,
            preserve_vector_top=False,
        ),
    )

    results = strategy.search("AuthTokenVerifier", limit=2)

    assert results[0].item.id == "symbol"


def test_hybrid_strategy_traces_rank_stage_movement(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    item = CodeItem(
        id="symbol",
        path="src/auth.py",
        title="src/auth.py::AuthTokenVerifier",
        content="class AuthTokenVerifier: pass",
        metadata={"index_kind": "symbol", "symbol": "AuthTokenVerifier"},
    )
    graph_store = _graph_store(tmp_path, [item], [])
    strategy = HybridRetrievalStrategy(
        FakeRetrievalStrategy([SearchResult(item, 0.99)]),
        graph_store,
        HybridSearchConfig(candidate_limit=5, symbol_match_weight=0.1, graph_depth=1, graph_neighbor_limit=20),
        trace_logger=TraceLogger(TraceConfig(enabled=True, artifact=trace_path, include_prompts=False)),
    )

    strategy.search("AuthTokenVerifier", limit=1)

    records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    record = records[0]
    assert record["event"] == "hybrid_rank_stages"
    assert record["payload"]["graph"]["requested_depth"] == 1
    assert record["payload"]["graph"]["effective_depth"] == 1
    assert record["payload"]["graph"]["candidate_count"] == 0


def test_hybrid_strategy_can_preserve_confident_vector_top(tmp_path: Path) -> None:
    vector_top = CodeItem(
        id="vector-top",
        path="src/auth/token.py",
        title="token verifier",
        content="def verify_token(): pass",
    )
    lexical_top = CodeItem(
        id="lexical-top",
        path="src/auth/readme.py",
        title="authorization token token token",
        content="authorization token token token token token token token",
    )
    graph_store = _graph_store(tmp_path, [vector_top, lexical_top], [])
    strategy = HybridRetrievalStrategy(
        FakeRetrievalStrategy([SearchResult(vector_top, 0.95), SearchResult(lexical_top, 0.84)]),
        graph_store,
        HybridSearchConfig(
            candidate_limit=5,
            lexical_candidate_limit=5,
            vector_weight=0.05,
            lexical_weight=0.95,
            path_weight=0.0,
            symbol_weight=0.0,
            graph_weight=0.0,
            preserve_vector_top=True,
            vector_top_score_margin=0.05,
        ),
    )

    results = strategy.search("authorization token", limit=2)

    assert results[0].item.id == "vector-top"


def test_hybrid_strategy_does_not_preserve_vector_top_without_margin(tmp_path: Path) -> None:
    vector_top = CodeItem(
        id="vector-top",
        path="src/auth/token.py",
        title="token verifier",
        content="def verify_token(): pass",
    )
    lexical_top = CodeItem(
        id="lexical-top",
        path="src/auth/readme.py",
        title="authorization token token token",
        content="authorization token token token token token token token",
    )
    graph_store = _graph_store(tmp_path, [vector_top, lexical_top], [])
    strategy = HybridRetrievalStrategy(
        FakeRetrievalStrategy([SearchResult(vector_top, 0.95), SearchResult(lexical_top, 0.94)]),
        graph_store,
        HybridSearchConfig(
            candidate_limit=5,
            lexical_candidate_limit=5,
            vector_weight=0.05,
            lexical_weight=0.95,
            path_weight=0.0,
            symbol_weight=0.0,
            graph_weight=0.0,
            preserve_vector_top=True,
            vector_top_score_margin=0.05,
        ),
    )

    results = strategy.search("authorization token", limit=2)

    assert results[0].item.id == "lexical-top"


def _vector_kind_top_fixture(tmp_path: Path, *, preserve_vector_kind_top: int) -> HybridRetrievalStrategy:
    """A strong single-lane vector hit that fused ranking trims out of the pool.

    H-81: the file_manifest item never matches the query lexically, so its fused score lands
    below both file_summary distractors and the pool trim at limit=2 evicts it, even though it
    is the top vector hit of its own kind.
    """
    summary_top = CodeItem(
        id="summary-top",
        path="src/auth/token.py",
        title="authorization token",
        content="authorization token token token token token",
        metadata={"index_kind": "file_summary"},
    )
    summary_second = CodeItem(
        id="summary-second",
        path="src/auth/session.py",
        title="authorization token",
        content="authorization token token token token",
        metadata={"index_kind": "file_summary"},
    )
    manifest_gold = CodeItem(
        id="manifest-gold",
        path="src/find/manager.py",
        title="find manager",
        content="def locate(): pass",
        metadata={"index_kind": "file_manifest"},
    )
    graph_store = _graph_store(tmp_path, [summary_top, summary_second, manifest_gold], [])
    return HybridRetrievalStrategy(
        FakeRetrievalStrategy(
            [
                SearchResult(summary_top, 0.95),
                SearchResult(summary_second, 0.94),
                SearchResult(manifest_gold, 0.90),
            ]
        ),
        graph_store,
        HybridSearchConfig(
            candidate_limit=5,
            lexical_candidate_limit=5,
            vector_weight=0.1,
            lexical_weight=0.9,
            path_weight=0.0,
            symbol_weight=0.0,
            graph_weight=0.0,
            preserve_vector_top=False,
            preserve_vector_kind_top=preserve_vector_kind_top,
        ),
    )


def test_hybrid_strategy_trims_single_lane_vector_hit_without_kind_top_guard(tmp_path: Path) -> None:
    strategy = _vector_kind_top_fixture(tmp_path, preserve_vector_kind_top=0)

    results = strategy.search("authorization token", limit=2)

    assert [result.item.id for result in results] == ["summary-top", "summary-second"]


def test_hybrid_strategy_preserves_vector_kind_tops_through_pool_trim(tmp_path: Path) -> None:
    strategy = _vector_kind_top_fixture(tmp_path, preserve_vector_kind_top=1)

    results = strategy.search("authorization token", limit=2)

    assert [result.item.id for result in results] == ["summary-top", "manifest-gold"]


def test_hybrid_strategy_kind_top_guard_keeps_pool_untouched_when_tops_already_survive(
    tmp_path: Path,
) -> None:
    strategy = _vector_kind_top_fixture(tmp_path, preserve_vector_kind_top=1)

    results = strategy.search("authorization token", limit=3)

    assert [result.item.id for result in results] == ["summary-top", "summary-second", "manifest-gold"]


def test_hybrid_strategy_skips_graph_expansion_when_weight_is_zero(tmp_path: Path) -> None:
    seed_item = CodeItem(id="seed", path="src/seed.py", title="seed", content="seed content")
    neighbor_item = CodeItem(id="neighbor", path="src/neighbor.py", title="neighbor", content="neighbor content")
    graph_store = _graph_store(
        tmp_path,
        [seed_item, neighbor_item],
        [GraphEdge(source=seed_item.id, target=neighbor_item.id, kind="calls", weight=0.9)],
    )
    strategy = HybridRetrievalStrategy(
        FakeRetrievalStrategy([SearchResult(seed_item, 0.8)]),
        graph_store,
        HybridSearchConfig(
            candidate_limit=5,
            lexical_candidate_limit=5,
            vector_weight=1.0,
            lexical_weight=0.0,
            path_weight=0.0,
            symbol_weight=0.0,
            graph_weight=0.0,
        ),
    )
    call_count = _spy_on_graph_scores(strategy)

    strategy.search("seed", limit=2)

    assert call_count() == 0


def test_hybrid_strategy_skips_graph_expansion_at_zero_depth(tmp_path: Path) -> None:
    seed_item = CodeItem(id="seed", path="src/seed.py", title="seed", content="seed content")
    neighbor_item = CodeItem(id="neighbor", path="src/neighbor.py", title="neighbor", content="neighbor content")
    graph_store = _graph_store(
        tmp_path,
        [seed_item, neighbor_item],
        [GraphEdge(source=seed_item.id, target=neighbor_item.id, kind="calls", weight=0.9)],
    )
    strategy = HybridRetrievalStrategy(
        FakeRetrievalStrategy([SearchResult(seed_item, 0.8)]),
        graph_store,
        HybridSearchConfig(
            candidate_limit=5,
            lexical_candidate_limit=5,
            vector_weight=1.0,
            lexical_weight=0.0,
            path_weight=0.0,
            symbol_weight=0.0,
            graph_weight=1.0,
            graph_depth=0,
        ),
    )
    call_count = _spy_on_graph_scores(strategy)

    results = strategy.search("seed", limit=2)

    assert call_count() == 0
    assert [result.item.id for result in results] == [seed_item.id]


def test_hybrid_strategy_computes_graph_expansion_when_weight_is_positive(tmp_path: Path) -> None:
    seed_item = CodeItem(id="seed", path="src/seed.py", title="seed", content="seed content")
    neighbor_item = CodeItem(id="neighbor", path="src/neighbor.py", title="neighbor", content="neighbor content")
    graph_store = _graph_store(
        tmp_path,
        [seed_item, neighbor_item],
        [GraphEdge(source=seed_item.id, target=neighbor_item.id, kind="calls", weight=0.9)],
    )
    strategy = HybridRetrievalStrategy(
        FakeRetrievalStrategy([SearchResult(seed_item, 0.8)]),
        graph_store,
        HybridSearchConfig(
            candidate_limit=5,
            lexical_candidate_limit=5,
            vector_weight=0.5,
            lexical_weight=0.0,
            path_weight=0.0,
            symbol_weight=0.0,
            graph_weight=0.5,
            graph_depth=1,
            graph_neighbor_limit=5,
        ),
    )
    call_count = _spy_on_graph_scores(strategy)

    results = strategy.search("seed", limit=2)

    assert call_count() == 1
    assert "src/neighbor.py" in [result.item.path for result in results]


def test_hybrid_strategy_zero_graph_weight_ignores_graph_edges(tmp_path: Path) -> None:
    seed_item = CodeItem(id="seed", path="src/seed.py", title="seed", content="seed content")
    neighbor_item = CodeItem(id="neighbor", path="src/neighbor.py", title="neighbor", content="neighbor content")
    config = HybridSearchConfig(
        candidate_limit=5,
        lexical_candidate_limit=5,
        vector_weight=1.0,
        lexical_weight=0.0,
        path_weight=0.0,
        symbol_weight=0.0,
        graph_weight=0.0,
    )
    strategy_without_edges = HybridRetrievalStrategy(
        FakeRetrievalStrategy([SearchResult(seed_item, 0.8)]),
        _graph_store(tmp_path / "without-edges", [seed_item, neighbor_item], []),
        config,
    )
    strategy_with_edges = HybridRetrievalStrategy(
        FakeRetrievalStrategy([SearchResult(seed_item, 0.8)]),
        _graph_store(
            tmp_path / "with-edges",
            [seed_item, neighbor_item],
            [GraphEdge(source=seed_item.id, target=neighbor_item.id, kind="calls", weight=0.9)],
        ),
        config,
    )

    results_without_edges = strategy_without_edges.search("seed", limit=2)
    results_with_edges = strategy_with_edges.search("seed", limit=2)

    assert [(result.item.id, result.score) for result in results_without_edges] == [
        (result.item.id, result.score) for result in results_with_edges
    ]


def test_hybrid_strategy_family_penalty_breaks_sibling_tie_with_vector_signal(tmp_path: Path) -> None:
    # Four sibling files all share the same directory/symbol tokens for "rename refactoring",
    # so path/symbol scoring alone cannot distinguish them. Only the vector score (standing in
    # for semantic relevance) points at the correct sibling.
    siblings = [
        CodeItem(
            id=f"sibling-{index}",
            path=f"src/refactoring/rename/Rename{name}.py",
            title=f"Rename{name}",
            content="rename refactoring handler",
        )
        for index, name in enumerate(["Handler", "Model", "Dialog", "Processor"])
    ]
    correct = siblings[3]
    graph_store = _graph_store(tmp_path, siblings, [])
    config = HybridSearchConfig(
        candidate_limit=10,
        lexical_candidate_limit=10,
        vector_weight=0.4,
        lexical_weight=0.0,
        path_weight=0.3,
        symbol_weight=0.3,
        graph_weight=0.0,
        preserve_vector_top=False,
        family_penalty_enabled=True,
        family_penalty_min_family_size=3,
    )
    strategy = HybridRetrievalStrategy(
        FakeRetrievalStrategy(
            [
                SearchResult(siblings[0], 0.5),
                SearchResult(siblings[1], 0.5),
                SearchResult(siblings[2], 0.5),
                SearchResult(correct, 0.95),
            ]
        ),
        graph_store,
        config,
    )

    results = strategy.search("where is rename refactoring coordinated", limit=1)

    assert results[0].item.id == correct.id


def test_hybrid_strategy_family_penalty_leaves_small_families_untouched(tmp_path: Path) -> None:
    # Only two candidates share path/symbol coverage -- below family_penalty_min_family_size --
    # so the unique-match story used by mechanical queries must be unaffected.
    unique_match = CodeItem(
        id="unique",
        path="src/manifest/JavaManifestUtil.java",
        title="JavaManifestUtil",
        content="java manifest util implementation",
    )
    other = CodeItem(
        id="other",
        path="src/manifest/JavaManifestReader.java",
        title="JavaManifestReader",
        content="java manifest reader implementation",
    )
    graph_store = _graph_store(tmp_path, [unique_match, other], [])
    config = HybridSearchConfig(
        candidate_limit=10,
        lexical_candidate_limit=10,
        vector_weight=0.2,
        lexical_weight=0.2,
        path_weight=0.3,
        symbol_weight=0.3,
        graph_weight=0.0,
        preserve_vector_top=False,
        family_penalty_enabled=True,
        family_penalty_min_family_size=3,
    )
    strategy = HybridRetrievalStrategy(
        FakeRetrievalStrategy([SearchResult(unique_match, 0.6), SearchResult(other, 0.59)]),
        graph_store,
        config,
    )

    results = strategy.search("java manifest util", limit=2)

    assert results[0].item.id == unique_match.id


def test_hybrid_strategy_caps_candidates_per_path_when_configured(tmp_path: Path) -> None:
    # H-64: chunk-level indexing puts many points on one path. Without a cap the top-k is all
    # one file, and the file-level stage then dedups it down to a single useful result.
    chunks = [
        CodeItem(
            id=f"big-chunk-{index}",
            path="src/Big.kt",
            title=f"src/Big.kt::handle{index}",
            content=f"symbol: function Big.handle{index} authorization token",
            metadata={"index_kind": "symbol_chunk"},
        )
        for index in range(5)
    ]
    other = CodeItem(
        id="other",
        path="src/Other.kt",
        title="src/Other.kt",
        content="symbol: class Other authorization token",
        metadata={"index_kind": "symbol_chunk"},
    )
    graph_store = _graph_store(tmp_path, [*chunks, other], [])
    config = HybridSearchConfig(
        candidate_limit=10,
        lexical_candidate_limit=10,
        vector_weight=1.0,
        lexical_weight=0.0,
        path_weight=0.0,
        symbol_weight=0.0,
        graph_weight=0.0,
        preserve_vector_top=False,
        per_path_result_limit=2,
    )
    vector = FakeRetrievalStrategy(
        [*(SearchResult(chunk, 0.9 - index * 0.01) for index, chunk in enumerate(chunks)), SearchResult(other, 0.5)]
    )

    results = HybridRetrievalStrategy(vector, graph_store, config).search("authorization token", limit=4)

    assert [result.item.path for result in results].count("src/Big.kt") == 2
    assert "src/Other.kt" in [result.item.path for result in results]


def test_hybrid_strategy_keeps_every_candidate_when_per_path_cap_is_disabled(tmp_path: Path) -> None:
    chunks = [
        CodeItem(
            id=f"big-chunk-{index}",
            path="src/Big.kt",
            title=f"src/Big.kt::handle{index}",
            content=f"symbol: function Big.handle{index} authorization token",
        )
        for index in range(4)
    ]
    graph_store = _graph_store(tmp_path, chunks, [])
    config = HybridSearchConfig(
        candidate_limit=10,
        lexical_candidate_limit=10,
        vector_weight=1.0,
        lexical_weight=0.0,
        path_weight=0.0,
        symbol_weight=0.0,
        graph_weight=0.0,
        preserve_vector_top=False,
    )
    vector = FakeRetrievalStrategy(
        [SearchResult(chunk, 0.9 - index * 0.01) for index, chunk in enumerate(chunks)]
    )

    results = HybridRetrievalStrategy(vector, graph_store, config).search("authorization token", limit=4)

    assert len(results) == 4


def _spy_on_graph_scores(strategy: HybridRetrievalStrategy) -> Callable[[], int]:
    original = strategy._graph_scores
    calls = {"count": 0}

    def counting(*args: object, **kwargs: object) -> dict[str, float]:
        calls["count"] += 1
        return original(*args, **kwargs)

    strategy._graph_scores = counting  # type: ignore[method-assign]
    return lambda: calls["count"]


def _graph_store(tmp_path: Path, items: list[CodeItem], edges: list[GraphEdge]) -> CodeGraphStore:
    store = CodeGraphStore(tmp_path / "graph.json")
    store.save(CodeGraph(items={item.id: item for item in items}, edges=edges))
    return store
