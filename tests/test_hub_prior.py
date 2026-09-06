from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from code_diver.config import GraphFileSearchConfig
from code_diver.config.cross_encoder_rerank_config import CrossEncoderRerankConfig
from code_diver.config.hub_prior_config import HubPriorConfig
from code_diver.domain import CodeItem, SearchResult
from code_diver.graph import CodeGraph, CodeGraphStore, GraphEdge
from code_diver.reranking import HubPriorScorer, RerankScore
from code_diver.reranking.hub_prior_scorer import (
    HUB_ROLE_PRIOR,
    NEUTRAL_ROLE_PRIOR,
    NON_SOURCE_ROLE_PRIOR,
    PERIPHERAL_ROLE_PRIOR,
    TEST_PATH_ROLE_PRIOR,
)
from code_diver.strategies import GraphFileRetrievalStrategy, RetrievalStrategy
from code_diver.strategies.cross_encoder_rerank_retrieval_strategy import (
    CrossEncoderRerankRetrievalStrategy,
)
from code_diver.strategies.file_graph_catalog import FileGraphCatalog
from code_diver.strategies.file_graph_catalog_store import FileGraphCatalogStore

pytestmark = pytest.mark.unit


class FakeStrategy(RetrievalStrategy):
    def __init__(self, results: list[SearchResult]):
        self.results = results

    def search(self, query: str, limit: int) -> list[SearchResult]:
        return self.results[:limit]


class FakeRerankProvider:
    name = "fake_rerank"
    model = "fake-cross-encoder"

    def __init__(self, scores: list[RerankScore]):
        self.scores = scores
        self.calls: list[tuple[str, list[str], int]] = []

    def rerank(self, query: str, documents: list[str], top_n: int) -> list[RerankScore]:
        self.calls.append((query, documents, top_n))
        return list(self.scores)


# --- role prior -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("platform/refactoring/RenameProcessor.java", HUB_ROLE_PRIOR),
        ("platform/refactoring/RenameHandler.java", PERIPHERAL_ROLE_PRIOR),
        ("docs/extension-points.md", NON_SOURCE_ROLE_PRIOR),
        ("platform/lang/testSrc/com/intellij/RenameProcessor.java", TEST_PATH_ROLE_PRIOR),
        ("spellchecker/src/com/intellij/spellchecker/SpellCheckerManager.kt", HUB_ROLE_PRIOR),
        ("platform/find/FindManagerImpl.java", HUB_ROLE_PRIOR),
        ("platform/find/FindInProjectSettings.java", NEUTRAL_ROLE_PRIOR),
        ("platform/util/PsiTreeUtil.java", PERIPHERAL_ROLE_PRIOR),
        ("platform/refactoring/RenameProcessorTest.java", PERIPHERAL_ROLE_PRIOR),
        ("platform/vcs/Transaction.java", NEUTRAL_ROLE_PRIOR),
        ("plugins/foo/package.json", NON_SOURCE_ROLE_PRIOR),
        ("plugins/foo/resources/FooBundle.properties", NON_SOURCE_ROLE_PRIOR),
    ],
)
def test_role_prior_classifies_filename_roles(path: str, expected: float) -> None:
    assert HubPriorScorer().role_prior(path) == expected


def test_role_prior_stays_within_unit_interval_and_honours_vocabulary_overrides() -> None:
    scorer = HubPriorScorer(
        HubPriorConfig(
            hub_tokens=["Gateway"],
            peripheral_tokens=["Widget"],
            test_path_segments=["spec"],
            non_source_extensions=[".rst"],
        )
    )
    assert scorer.role_prior("a/PaymentGateway.java") == HUB_ROLE_PRIOR
    assert scorer.role_prior("a/PaymentWidget.java") == PERIPHERAL_ROLE_PRIOR
    assert scorer.role_prior("a/spec/PaymentGateway.java") == TEST_PATH_ROLE_PRIOR
    assert scorer.role_prior("a/index.rst") == NON_SOURCE_ROLE_PRIOR
    # Default vocabulary no longer applies once overridden.
    assert scorer.role_prior("a/PaymentManager.java") == NEUTRAL_ROLE_PRIOR
    for path in ("a/PaymentGateway.java", "a/PaymentWidget.java", "a/spec/X.java", "a/index.rst"):
        assert -1.0 <= scorer.role_prior(path) <= 1.0


# --- fan-in prior -----------------------------------------------------------------------


def test_fanin_prior_is_log_normalised_against_the_busiest_candidate() -> None:
    degrees = {"hub.java": 99, "mid.java": 9, "leaf.java": 0}
    scorer = HubPriorScorer(fan_in=lambda path: degrees.get(path, 0))
    paths = list(degrees)

    assert scorer.max_in_degree(paths) == 99
    assert scorer.fanin_prior("hub.java", 99) == pytest.approx(1.0)
    assert scorer.fanin_prior("mid.java", 99) == pytest.approx(math.log1p(9) / math.log1p(99))
    assert scorer.fanin_prior("leaf.java", 99) == 0.0
    assert scorer.fanin_prior("unknown.java", 99) == 0.0


def test_fanin_prior_is_zero_for_everyone_without_a_graph() -> None:
    no_graph = HubPriorScorer(fan_in=None)
    unavailable = HubPriorScorer(fan_in=lambda path: None)
    paths = ["a/Hub.java", "a/Leaf.java"]
    for scorer in (no_graph, unavailable):
        assert scorer.max_in_degree(paths) == 0
        assert all(scorer.fanin_prior(path, scorer.max_in_degree(paths)) == 0.0 for path in paths)


def test_combined_prior_weights_role_and_fanin() -> None:
    degrees = {"a/RenameProcessor.java": 20, "a/RenameHandler.java": 5}
    scorer = HubPriorScorer(fan_in=degrees.get)

    priors = scorer.priors(degrees, role_weight=0.04, fanin_weight=0.02)

    assert priors["a/RenameProcessor.java"] == pytest.approx(0.04 * HUB_ROLE_PRIOR + 0.02 * 1.0)
    assert priors["a/RenameHandler.java"] == pytest.approx(
        0.04 * PERIPHERAL_ROLE_PRIOR + 0.02 * math.log1p(5) / math.log1p(20)
    )


# --- cross-encoder stage ----------------------------------------------------------------


def _saturated_tie() -> tuple[list[SearchResult], list[RerankScore]]:
    # Hub sits just past the cut on an arbitrary-order plateau: WHERE-78 death stage 1.
    results = [
        _result("handler", "platform/refactoring/RenameHandler.java", 0.9),
        _result("dialog", "platform/refactoring/RenameDialog.java", 0.8),
        _result("plugin_xml", "platform/refactoring/resources/META-INF/plugin.xml", 0.7),
        _result("processor", "platform/refactoring/RenameProcessor.java", 0.6),
    ]
    scores = [
        RerankScore(index=0, score=0.9981),
        RerankScore(index=1, score=0.9980),
        RerankScore(index=2, score=0.9979),
        RerankScore(index=3, score=0.9978),
    ]
    return results, scores


def test_cross_encoder_hub_prior_disabled_keeps_ce_order_identical() -> None:
    results, scores = _saturated_tie()
    baseline = CrossEncoderRerankRetrievalStrategy(
        FakeStrategy(results), FakeRerankProvider(scores), CrossEncoderRerankConfig(candidate_limit=4)
    )
    disabled = CrossEncoderRerankRetrievalStrategy(
        FakeStrategy(results),
        FakeRerankProvider(scores),
        CrossEncoderRerankConfig(
            candidate_limit=4,
            hub_prior_enabled=False,
            hub_prior_role_weight=0.04,
            hub_prior_fanin_weight=0.04,
        ),
        hub_prior_scorer=HubPriorScorer(fan_in=lambda path: 50),
    )

    expected = [result.item.path for result in baseline.search("where is rename implemented", 3)]

    assert [result.item.path for result in disabled.search("where is rename implemented", 3)] == expected
    assert expected == [
        "platform/refactoring/RenameHandler.java",
        "platform/refactoring/RenameDialog.java",
        "platform/refactoring/resources/META-INF/plugin.xml",
    ]


def test_cross_encoder_hub_prior_additive_reorders_a_saturated_tie() -> None:
    results, scores = _saturated_tie()
    strategy = CrossEncoderRerankRetrievalStrategy(
        FakeStrategy(results),
        FakeRerankProvider(scores),
        CrossEncoderRerankConfig(
            candidate_limit=4,
            hub_prior_enabled=True,
            hub_prior_mode="additive",
            hub_prior_role_weight=0.04,
            hub_prior_fanin_weight=0.0,
        ),
    )

    reranked = strategy.search("where is rename implemented", 3)

    # +0.04 hub, -0.02 peripheral (Handler, Dialog), -0.04 non-source: the hub crosses the
    # cut, plugin.xml drops out, the two peripherals keep their CE order; base scores are
    # untouched.
    assert [result.item.path for result in reranked] == [
        "platform/refactoring/RenameProcessor.java",
        "platform/refactoring/RenameHandler.java",
        "platform/refactoring/RenameDialog.java",
    ]
    assert [result.score for result in reranked] == [0.6, 0.9, 0.8]


def test_cross_encoder_hub_prior_requests_scores_for_the_whole_window() -> None:
    results, scores = _saturated_tie()
    provider = FakeRerankProvider(scores)
    strategy = CrossEncoderRerankRetrievalStrategy(
        FakeStrategy(results),
        provider,
        CrossEncoderRerankConfig(candidate_limit=4, hub_prior_enabled=True, hub_prior_role_weight=0.04),
    )

    strategy.search("query", 2)

    assert provider.calls[0][2] == 4


def test_cross_encoder_hub_prior_band_mode_does_not_cross_a_wide_gap() -> None:
    results = [
        _result("handler", "platform/refactoring/RenameHandler.java", 0.9),
        _result("dialog", "platform/refactoring/RenameDialog.java", 0.8),
        _result("processor", "platform/refactoring/RenameProcessor.java", 0.7),
    ]
    # Handler wins clearly (gap 0.2 > band 0.03); dialog and processor are one band.
    scores = [
        RerankScore(index=0, score=0.95),
        RerankScore(index=1, score=0.75),
        RerankScore(index=2, score=0.74),
    ]
    band = CrossEncoderRerankRetrievalStrategy(
        FakeStrategy(results),
        FakeRerankProvider(scores),
        CrossEncoderRerankConfig(
            candidate_limit=3,
            hub_prior_enabled=True,
            hub_prior_mode="band",
            hub_prior_band_width=0.03,
            hub_prior_role_weight=0.5,
            hub_prior_fanin_weight=0.0,
        ),
    )
    additive = CrossEncoderRerankRetrievalStrategy(
        FakeStrategy(results),
        FakeRerankProvider(scores),
        CrossEncoderRerankConfig(
            candidate_limit=3,
            hub_prior_enabled=True,
            hub_prior_mode="additive",
            hub_prior_role_weight=0.5,
            hub_prior_fanin_weight=0.0,
        ),
    )

    assert [result.item.path for result in band.search("query", 3)] == [
        "platform/refactoring/RenameHandler.java",
        "platform/refactoring/RenameProcessor.java",
        "platform/refactoring/RenameDialog.java",
    ]
    # The same (deliberately huge) weight in additive mode does cross the gap.
    assert [result.item.path for result in additive.search("query", 3)][0] == (
        "platform/refactoring/RenameProcessor.java"
    )


def test_cross_encoder_hub_prior_rejects_unknown_mode() -> None:
    results, scores = _saturated_tie()
    strategy = CrossEncoderRerankRetrievalStrategy(
        FakeStrategy(results),
        FakeRerankProvider(scores),
        CrossEncoderRerankConfig(candidate_limit=4, hub_prior_enabled=True, hub_prior_mode="bogus"),
    )

    with pytest.raises(ValueError):
        strategy._hub_prior_adjusted("query", results, scores)


def test_cross_encoder_hub_prior_protect_top_pins_the_head() -> None:
    results = [
        _result("handler", "platform/refactoring/RenameHandler.java", 0.9),
        _result("dialog", "platform/refactoring/RenameDialog.java", 0.8),
        _result("processor", "platform/refactoring/RenameProcessor.java", 0.7),
    ]
    # In CE order: handler (0.95) > dialog (0.85) > processor (0.75)
    scores = [
        RerankScore(index=0, score=0.95),
        RerankScore(index=1, score=0.85),
        RerankScore(index=2, score=0.75),
    ]
    # Without protection, additive hub prior (0.5) will pull processor (0.75+0.5=1.25) to the top.
    # With protect_top=2, the first two (handler, dialog) are pinned, processor stays at 3.
    strategy = CrossEncoderRerankRetrievalStrategy(
        FakeStrategy(results),
        FakeRerankProvider(scores),
        CrossEncoderRerankConfig(
            candidate_limit=3,
            hub_prior_enabled=True,
            hub_prior_mode="additive",
            hub_prior_role_weight=0.5,
            hub_prior_protect_top=2,
        ),
    )

    reranked = strategy.search("query", 3)
    assert [result.item.path for result in reranked] == [
        "platform/refactoring/RenameHandler.java",
        "platform/refactoring/RenameDialog.java",
        "platform/refactoring/RenameProcessor.java",
    ]

    # protect_top=0 means current behavior: processor wins.
    strategy_off = CrossEncoderRerankRetrievalStrategy(
        FakeStrategy(results),
        FakeRerankProvider(scores),
        CrossEncoderRerankConfig(
            candidate_limit=3,
            hub_prior_enabled=True,
            hub_prior_mode="additive",
            hub_prior_role_weight=0.5,
            hub_prior_protect_top=0,
        ),
    )
    reranked_off = strategy_off.search("query", 3)
    assert reranked_off[0].item.path == "platform/refactoring/RenameProcessor.java"

    # protect_top >= len(candidates) is a no-op (everything pinned).
    strategy_all = CrossEncoderRerankRetrievalStrategy(
        FakeStrategy(results),
        FakeRerankProvider(scores),
        CrossEncoderRerankConfig(
            candidate_limit=3,
            hub_prior_enabled=True,
            hub_prior_mode="additive",
            hub_prior_role_weight=0.5,
            hub_prior_protect_top=10,
        ),
    )
    reranked_all = strategy_all.search("query", 3)
    assert [result.item.path for result in reranked_all] == [
        "platform/refactoring/RenameHandler.java",
        "platform/refactoring/RenameDialog.java",
        "platform/refactoring/RenameProcessor.java",
    ]


# --- graph-file stage -------------------------------------------------------------------


def test_file_graph_catalog_collects_directed_fan_in_and_round_trips() -> None:
    hub = _manifest("hub", "src/core/UserService.java")
    caller_a = _manifest("a", "src/api/UsersAction.java")
    caller_b = _manifest("b", "src/api/UsersDialog.java")
    edges = [
        GraphEdge(source=caller_a.id, target=hub.id, kind="imports", weight=0.8),
        GraphEdge(source=caller_b.id, target=hub.id, kind="imports", weight=0.8),
        # Duplicate edge from the same file must not double-count.
        GraphEdge(source=caller_b.id, target=hub.id, kind="references", weight=0.5),
        GraphEdge(source=hub.id, target=caller_a.id, kind="imports", weight=0.8),
    ]

    catalog = FileGraphCatalog.build([hub, caller_a, caller_b], edges)
    restored = FileGraphCatalog.from_json(catalog.to_json())

    assert catalog.fan_in is not None
    assert catalog.fan_in.degree(hub.path) == 2
    assert catalog.fan_in.degree(caller_a.path) == 1
    assert catalog.fan_in.degree(caller_b.path) == 0
    assert restored.fan_in is not None
    assert restored.fan_in.in_degree == catalog.fan_in.in_degree
    # Catalogs persisted before H-87 have no fan-in block: unavailable, not zero.
    legacy = FileGraphCatalog.from_json({"items": {}, "adjacency": {"adjacency": {}}})
    assert legacy.fan_in is None


def test_file_graph_catalog_store_rebuilds_on_version_mismatch_or_missing_fan_in(tmp_path: Path) -> None:
    from code_diver.strategies.file_graph_catalog_store import SCHEMA_VERSION

    artifact = tmp_path / "catalog.json"
    store = FileGraphCatalogStore(artifact)

    # 1. Version mismatch
    artifact.write_text(json.dumps({
        "schema_version": SCHEMA_VERSION - 1,
        "catalog": {"items": {}, "adjacency": {"adjacency": {}}}
    }))
    with pytest.raises(ValueError, match="Unsupported file graph catalog schema"):
        store.load()

    # 2. Missing fan_in (legacy schema but current version)
    artifact.write_text(json.dumps({
        "schema_version": SCHEMA_VERSION,
        "catalog": {"items": {}, "adjacency": {"adjacency": {}}}
    }))
    with pytest.raises(ValueError, match="missing fan_in index"):
        store.load()

    # 3. Healthy round-trip
    catalog = FileGraphCatalog(items_by_id={}, adjacency=FileGraphCatalog.build([], []).adjacency, fan_in=None)
    # Wait, if I pass fan_in=None, save() will omit it, then load() will fail.
    # The build() method ensures fan_in is not None.
    catalog = FileGraphCatalog.build([], [])
    store.save(catalog)
    loaded = store.load()
    assert loaded.fan_in is not None


def test_graph_file_hub_prior_seed_weight_zero_leaves_seed_totals_unchanged(tmp_path: Path) -> None:
    strategy, results = _graph_file_fixture(tmp_path, hub_prior_seed_weight=0.0)

    ranked = strategy.search("users", limit=3)

    assert [result.item.path for result in ranked] == [
        "src/api/UsersAction.java",
        "src/core/UserServiceImpl.java",
        "src/api/UsersDialog.java",
    ]
    assert [result.score for result in ranked] == pytest.approx([1.0, 0.5, 0.0])


def test_graph_file_hub_prior_seed_weight_lifts_the_hub_across_the_seed_order(tmp_path: Path) -> None:
    strategy, results = _graph_file_fixture(tmp_path, hub_prior_seed_weight=0.6)

    ranked = strategy.search("users", limit=3)

    # role: Impl +1.0 / Action -0.5 / Dialog -0.5; fan-in: hub 2 (max) -> 1.0, others 0.
    # 0.5 + 0.6 * (0.5 * 1.0 + 0.5 * 1.0) = 1.1 beats 1.0 + 0.6 * (0.5 * -0.5) = 0.85.
    assert [result.item.path for result in ranked] == [
        "src/core/UserServiceImpl.java",
        "src/api/UsersAction.java",
        "src/api/UsersDialog.java",
    ]
    assert ranked[0].score == pytest.approx(1.1)
    assert ranked[1].score == pytest.approx(0.85)
    assert strategy.fan_in_degree("src/core/UserServiceImpl.java") == 2
    assert strategy.fan_in_degree("src/api/UsersDialog.java") == 0


def _graph_file_fixture(
    tmp_path: Path, *, hub_prior_seed_weight: float
) -> tuple[GraphFileRetrievalStrategy, list[SearchResult]]:
    hub = _manifest("hub", "src/core/UserServiceImpl.java")
    action = _manifest("action", "src/api/UsersAction.java")
    dialog = _manifest("dialog", "src/api/UsersDialog.java")
    store = CodeGraphStore(tmp_path / "graph.json")
    store.save(
        CodeGraph(
            items={item.id: item for item in (hub, action, dialog)},
            edges=[
                GraphEdge(source=action.id, target=hub.id, kind="imports", weight=0.8),
                GraphEdge(source=dialog.id, target=hub.id, kind="imports", weight=0.8),
            ],
        )
    )
    results = [SearchResult(action, 0.9), SearchResult(hub, 0.6), SearchResult(dialog, 0.3)]
    strategy = GraphFileRetrievalStrategy(
        FakeStrategy(results),
        store,
        GraphFileSearchConfig(
            seed_limit=5,
            lexical_seed_limit=0,
            vector_weight=1.0,
            lexical_weight=0.0,
            path_weight=0.0,
            symbol_weight=0.0,
            graph_weight=0.0,
            depth=0,
            hub_prior_seed_weight=hub_prior_seed_weight,
            hub_prior_role_weight=0.5,
            hub_prior_fanin_weight=0.5,
        ),
    )
    return strategy, results


def _manifest(item_id: str, path: str) -> CodeItem:
    return CodeItem(
        id=item_id,
        path=path,
        title=f"{path}::file_manifest",
        content=f"file: {path}\nsymbols:\n- class {Path(path).stem}",
        metadata={"index_kind": "file_manifest"},
    )


def _result(item_id: str, path: str, score: float) -> SearchResult:
    return SearchResult(
        item=CodeItem(
            id=item_id,
            path=path,
            title=f"{path}::file_manifest",
            content=f"file: {path}\nsymbols:\n- class {Path(path).stem}",
            metadata={"index_kind": "file_manifest"},
        ),
        score=score,
    )
