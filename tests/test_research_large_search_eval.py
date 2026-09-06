import importlib.util
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/research_large_search_eval.py"
spec = importlib.util.spec_from_file_location("research_large_search_eval", SCRIPT)
r = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = r
spec.loader.exec_module(r)


def candidate(path="a.java", content="indexed " * 200):
    return r.SearchResult(r.CodeItem("a", path, "title", content, metadata={"nested": [1]}), 0.8)


def test_selection_frozen_and_overlaps():
    audit = json.loads(r.AUDIT.read_text())
    audit = audit.get("audit", audit)
    novel = audit["datasets"]["intellij_eval_1000.answer_sets"]["slices"]["query_and_answer_novel"]
    data = {k: r.rows(p) for k, p in r.DATA.items()}
    a = r.select(data, novel)
    assert a == r.select(data, novel)
    assert len(a["cases"]) == 192
    assert a["counts"] == {"where": 78, "novel": 95, "overlap": 15, "guards": 40, "mech": 118}
    assert sum(c["order"] == "AB" for c in a["cases"]) == 96
    for where in (False, True):
        for novel_member in (False, True):
            group = [c for c in a["cases"] if ("where" in c["labels"]) == where and c["novel"] == novel_member]
            assert abs(sum(c["order"] == "AB" for c in group) - sum(c["order"] == "BA" for c in group)) <= 1
    assert sum(c["added_guard"] for c in a["cases"]) == 34
    assert a["label_conflicts"]
    with pytest.raises(ValueError, match="arithmetic"):
        r.select(data, novel[:-1])
    conflict = next(iter(data["where"]))
    data["where"][conflict]["query"] = "different"
    with pytest.raises(ValueError, match="query conflict"):
        r.select(data, novel)


def test_pool_deep_isolation():
    c = candidate()
    pool = r.FrozenPool([c])
    a, b = pool.search("q", 34), pool.search("q", 34)
    a[0].item.metadata["nested"].append(2)
    a[0].item.content = "changed"
    assert asdict(b[0]) == asdict(c)
    assert asdict(pool.search("q", 34)[0]) == asdict(c)


def test_fragments_budget_envelope_safe_fallback(tmp_path):
    from code_diver.config.cross_encoder_rerank_config import CrossEncoderRerankConfig
    from code_diver.reranking.cross_encoder_document_builder import build_cross_encoder_document
    config = CrossEncoderRerankConfig(max_document_chars=850)
    c = candidate()
    source = "unrelated\n" * 150 + "targetNeedle " * 90
    (tmp_path / "a.java").write_text(source)
    baseline = build_cross_encoder_document(c, config, tmp_path)
    doc, evidence = r.fragment_document(c, config, tmp_path, "target needle")
    assert doc.split("content:\n")[0] == baseline.split("content:\n")[0]
    assert len(doc.split("content:\n")[1]) <= 850
    assert evidence["offset"] > 0 and evidence["fallback"] is None
    assert c.item.content.startswith("indexed")
    assert r.fragment("abc\ndef", "unknown")[1] == 0
    for path in ("missing", "../escape"):
        c.item.path = path
        actual, evidence = r.fragment_document(c, config, tmp_path, "query")
        assert actual == build_cross_encoder_document(c, config, tmp_path)
        assert evidence["fallback"]
    with pytest.raises(ValueError):
        r.fragment(source, "query", 0)


class Provider:
    name, model = "fixture", "fixture"

    def __init__(self, values):
        self.values = values

    def rerank(self, query, documents, top_n):
        return self.values


@pytest.mark.parametrize("scores", [[r.RerankScore(0, 0.1)],
                                    [r.RerankScore(0, 0.1), r.RerankScore(0, 0.2)],
                                    [r.RerankScore(0, 0.1), r.RerankScore(2, 0.2)],
                                    [r.RerankScore(0, 0.1), r.RerankScore(1, float("nan"))]])
def test_invalid_provider_scores(scores):
    provider = r.RecordedProvider(Provider(scores))
    with pytest.raises(ValueError):
        provider.rerank("query", ["a", "b"], 2)
    assert "error" in provider.calls[0]


def test_exact_metrics_and_missing_denominator():
    assert r.exact(["a", "glob:x", "b/", "*.kt"]) == {"a"}
    assert r.score(["x", "a"], ["a", "b"])["recall10"] == 0.5
    assert r.score(["x", "a"], ["a"])["mrr10"] == 0.5
    stats = r.paired_summary([(0, 1)], 192)
    assert stats["planned"] == 192 and stats["complete"] == 1
    assert stats["missing_delta_bounds"] == [-190 / 192, 1]
    assert r.paired_summary([(0, 1)], 192) == stats


def test_atomic_and_deadline(tmp_path):
    path = tmp_path / "checkpoint.json"
    r.atomic(path, {"a": 1})
    r.atomic(path, {"a": 2})
    assert json.loads(path.read_text()) == {"a": 2}
    assert not path.with_suffix(".json.tmp").exists()
    with pytest.raises(r.DeadlineExpired):
        r.expired()
    assert not issubclass(r.DeadlineExpired, Exception)


def test_production_parity_secondpass_meta_preservation_and_isolated_models(tmp_path):
    from code_diver.config import ConfigLoader
    config = ConfigLoader().load(r.CONFIG)
    ce = config.cross_encoder_rerank
    pool = [candidate(f"p{i}.java") for i in range(4)]
    for i, c in enumerate(pool):
        c.item.id = str(i)
        c.score = 1.0 - i * 0.2
    values = [r.RerankScore(i, 0.1 + i * 0.01) for i in range(4)]
    production = r.CrossEncoderRerankRetrievalStrategy(r.FrozenPool(pool), Provider(values), ce,
                                                       hub_prior_scorer=r.HubPriorScorer())
    actual = production.search("query", 3)
    a = r.ResearchArm(pool, r.RecordedProvider(Provider(values)), ce, tmp_path, config.hub_prior, {}, "query")
    b = r.ResearchArm(pool, r.RecordedProvider(Provider(values)), ce, tmp_path, config.hub_prior, {}, "query", True)
    assert [asdict(x) for x in a.search("query", 3)] == [asdict(x) for x in actual]
    assert len(a.rerank_provider.calls) == 2
    assert a._ce_meta_ranker.booster is not b._ce_meta_ranker.booster
    assert a.ce_meta_feature_extractor is not b.ce_meta_feature_extractor
    b.search("query", 3)
    assert a.rerank_provider.calls[1]["documents"] == b.rerank_provider.calls[1]["documents"]
    assert a.search("query", 3)[0].item.id == "0"


def test_no_retry_and_failure_explicit(tmp_path):
    from code_diver.config import ConfigLoader
    config = ConfigLoader().load(r.CONFIG)
    pool = [candidate("a"), candidate("b")]
    pool[1].item.id = "b"
    good = Provider([r.RerankScore(0, 0.9), r.RerankScore(1, 0.8)])
    a = r.ResearchArm(pool, r.RecordedProvider(good), config.cross_encoder_rerank,
                      tmp_path, config.hub_prior, {}, "query")
    assert r.execute_arm(a, "query")["complete"]
    assert len(a.rerank_provider.calls) == 1
    bad = r.ResearchArm(pool, r.RecordedProvider(Provider([])), config.cross_encoder_rerank,
                        tmp_path, config.hub_prior, {}, "query")
    result = r.execute_arm(bad, "query")
    assert not result["complete"] and result["failure_count"] == 1
    assert result["ranked"] == ["a", "b"]


def test_config_rejects_external_and_changed_budgets():
    from code_diver.config import ConfigLoader
    config = ConfigLoader().load(r.CONFIG)
    r.validate_config(config)
    for change in ({"url": "https://paid.example/v1/rerank"}, {"candidate_limit": 35},
                   {"use_llm_purpose_document": True}, {"second_pass_enabled": False}):
        with pytest.raises(ValueError):
            r.validate_config(replace(config, cross_encoder_rerank=replace(config.cross_encoder_rerank, **change)))


def test_retry_failure_and_deadline_preserve_partial(tmp_path):
    from code_diver.config import ConfigLoader
    config = ConfigLoader().load(r.CONFIG)
    pool = [candidate("a"), candidate("b")]
    pool[1].item.id = "b"

    class FailingSecond(Provider):
        def __init__(self, error):
            self.count, self.error = 0, error

        def rerank(self, query, documents, top_n):
            self.count += 1
            if self.count == 2:
                raise self.error
            return [r.RerankScore(0, 0.1), r.RerankScore(1, 0.2)]

    for error in (TimeoutError("HTTP timeout"), r.DeadlineExpired("deadline")):
        a = r.ResearchArm(pool, r.RecordedProvider(FailingSecond(error)), config.cross_encoder_rerank,
                          tmp_path, config.hub_prior, {}, "query")
        if isinstance(error, r.DeadlineExpired):
            with pytest.raises(r.DeadlineExpired):
                r.execute_arm(a, "query")
            result = a.interrupted_result
        else:
            result = r.execute_arm(a, "query")
        assert not result["complete"]
        assert "error" in result["calls"][1]


def test_parity_replay_document_mismatch():
    provider = r.RecordedProvider(Provider([]), replay=[{"documents": ["a"], "top_n": 1, "scores": []}])
    with pytest.raises(ValueError, match="parity"):
        provider.rerank("q", ["b"], 1)