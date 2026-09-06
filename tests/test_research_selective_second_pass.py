import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import research_selective_second_pass as r


def test_json_feature_parity_is_exact_without_numeric_tolerance():
    assert r.base.encoded({"features": (0.1, 0.2)}) == r.base.encoded({"features": [0.1, 0.2]})
    assert r.base.encoded({"features": (0.1, 0.2)}) != r.base.encoded({"features": [0.1, 0.20000000001]})


def test_evidence_boundaries():
    assert r.evidence(" " * 850 + "projectOpening", "project opening")
    assert not r.evidence("project " + " " * 850 + "project", "project")
    assert not r.evidence(" " * 849 + "project", "project")
    assert not r.evidence(" " * 2399 + "project", "project")
    assert r.evidence(" " * 2393 + "project", "project")
    assert not r.evidence(" " * 2400 + "project", "project")
    assert not r.evidence("project", "project")
    assert not r.evidence(" " * 850 + "project", "where is the")


def test_floor_cap_order():
    scores = [r.base.RerankScore(index=i, score=0.1) for i in reversed(range(25))]
    assert r.eligible(scores) == list(range(24))
    assert r.eligible(scores[:24]) == list(reversed(range(1, 25)))
    assert r.eligible([r.base.RerankScore(index=0, score=0.3)]) == []


def test_merge_mapping_max_and_stability():
    scores = [r.base.RerankScore(index=i, score=v) for i, v in ((2, .1), (0, .9), (1, .2))]
    saved = [{"index": 1, "score": .05}, {"index": 0, "score": .9}]
    assert [(s.index, s.score) for s in r.merge(scores, [2, 1], saved, [2, 1])] == [(2, .9), (0, .9), (1, .2)]
    assert r.merge(scores, [], [], []) is scores
    with pytest.raises(ValueError):
        r.merge(scores, [], [], [2])


def test_matched_control():
    indices = list(range(6))
    documents = ["a" * n for n in (260, 280, 300, 520, 600, 700)]
    chosen = r.control("case", indices, [0, 3, 4], documents)
    assert chosen == r.control("case", indices, [0, 3, 4], documents)
    assert len(chosen) == 3 and len(set(chosen)) == 3
    assert r.Counter(len(documents[i]) // 256 for i in chosen) == {1: 1, 2: 2}
    assert r.control("case", indices, [], documents) == []


def test_invalid_scores_and_network():
    call = {"documents": ["a"], "count": 1, "chars": 1, "top_n": 1, "scores": [{"index": 0, "score": .2}]}
    r.validate_calls([call])
    for scores in ([], [{"index": 1, "score": .2}], [{"index": 0, "score": float("nan")} ]):
        with pytest.raises(ValueError):
            r.validate_calls([{**call, "scores": scores}])
    with r.no_network(), pytest.raises(RuntimeError, match="forbids network"):
        r.socket.create_connection(("127.0.0.1", 8081))


@pytest.fixture(scope="module")
def retained():
    from replay_pool_recall import load_config
    manifest = r.json.loads((r.base.OUT / "manifest.json").read_text())
    state = r.json.loads((r.base.OUT / "checkpoint.json").read_text())
    pair = next(p for p in state["pairs"] if len(p["arms"]["A"]["calls"]) == 2)
    case = next(c for c in manifest["cases"] if c["id"] == pair["id"])
    return case, pair, load_config(r.base.CONFIG)


def test_retained_baseline_and_policy_recomputation(retained):
    case, pair, config = retained
    with r.no_network():
        baseline = r.replay(case, pair, config, "A", [])
        same = r.replay(case, pair, config, "S", r.decisions(case, pair)["indices"]["A"])
        for key in ("outputs", "features", "meta_predictions"):
            assert r.base.encoded(baseline[key]) == r.base.encoded(same[key])
        no_retry = r.replay(case, pair, config, "N", [])
    assert len(no_retry["meta_predictions"]) == len(no_retry["features"]) > 0
    assert no_retry["merged_scores"] == pair["arms"]["A"]["calls"][0]["scores"]


@pytest.mark.parametrize("field", ["outputs", "features", "meta_predictions", "retry_request"])
def test_parity_fails_closed(retained, field):
    import copy
    case, original, config = retained
    pair = copy.deepcopy(original)
    if field == "retry_request":
        pair["arms"]["A"]["calls"][1]["documents"][0] += "corrupt"
    else:
        pair["arms"]["A"][field] = []
    with r.no_network(), pytest.raises(ValueError):
        r.replay(case, pair, config, "A", [])


def test_policies_ignore_labels(retained):
    case, pair, _ = retained
    stripped = {k: case[k] for k in ("id", "query")}
    assert r.decisions(case, pair) == r.decisions(stripped, pair)


def test_live_schedule_label_free_balanced():
    manifest = r.json.loads((r.base.OUT / "manifest.json").read_text())
    state = r.json.loads((r.base.OUT / "checkpoint.json").read_text())
    source = {p["id"]: p for p in state["pairs"]}
    cases = [{k: c[k] for k in ("id", "query")} for c in manifest["cases"]]
    schedule = r.smoke_schedule(cases, source)
    assert len({c["id"] for c in schedule}) == 12
    assert schedule == r.smoke_schedule(manifest["cases"], source)
    recorded = r.json.loads((r.OUT / "live-smoke/manifest.json").read_text())["schedule"]
    assert r.base.encoded(r.json.loads(r.base.encoded(schedule))) == r.base.encoded(recorded)
    for position in range(3):
        assert r.Counter(c["order"][position] for c in schedule) == {"A": 4, "S": 4, "C": 4}
    with pytest.raises(ValueError):
        r.smoke_schedule([], {})


def test_live_adapter_retained_parity_and_subset(retained):
    case, pair, config = retained
    indices = r.decisions(case, pair)["indices"]["A"]
    scores = pair["arms"]["A"]["calls"][1]["scores"]
    result = r.fresh_replay(case, pair, config, indices, scores)
    for key in ("outputs", "features", "meta_predictions"):
        assert r.base.encoded(result[key]) == r.base.encoded(pair["arms"]["A"][key])
    selected = indices[:1]
    subset = [{"index": 0, "score": next(s["score"] for s in scores if s["index"] == 0)}]
    actual = r.fresh_replay(case, pair, config, selected, subset)
    assert actual == r.replay(case, pair, config, "S", selected)


def test_live_protocol_rejects_remote():
    with pytest.raises(ValueError, match="localhost"):
        r.smoke_json("https://example.com/v1/rerank", 1)


def test_timestamp_only_metadata_accepted_without_mutation():
    import copy
    recorded = {"object": "list", "data": [{"id": "model", "created": 1, "meta": {"size": 10}},
                                            {"id": "other", "created": 2}]}
    fresh = copy.deepcopy(recorded)
    fresh["data"][0]["created"] = 3
    fresh["data"][1]["created"] = 4
    originals = copy.deepcopy((recorded, fresh))
    changes = r.validate_model_metadata(recorded, fresh)
    assert changes == [{"field": "data[0].created", "recorded": 1, "fresh": 3},
                       {"field": "data[1].created", "recorded": 2, "fresh": 4}]
    assert (recorded, fresh) == originals
    assert r.validate_model_metadata(recorded, recorded) == []


@pytest.mark.parametrize("change", ["id", "other", "nested_created", "missing_created", "extra", "type"])
def test_non_timestamp_metadata_change_rejected(change):
    import copy
    recorded = {"object": "list", "data": [{"id": "model", "created": 1, "meta": {"created": 10}}]}
    fresh = copy.deepcopy(recorded)
    fresh["data"][0]["created"] = 2
    if change == "id":
        fresh["data"][0]["id"] = "different"
    elif change == "other":
        fresh["object"] = "other"
    elif change == "nested_created":
        fresh["data"][0]["meta"]["created"] = 11
    elif change == "missing_created":
        del fresh["data"][0]["created"]
    elif change == "extra":
        fresh["data"][0]["extra"] = True
    else:
        fresh["data"][0]["created"] = "2"
    with pytest.raises(ValueError, match="metadata drift"):
        r.validate_model_metadata(recorded, fresh)


@pytest.mark.parametrize("field", ["gguf", "config", "model", "resolved_config_equal", "source_manifest_equal", "source_checkpoint_equal"])
def test_live_preflight_drift_rejected(field):
    preflight = {"hashes": {n: {"expected": "same", "actual": "same"} for n in ("gguf", "config", "model")},
                 "resolved_config_equal": True, "source_manifest_equal": True, "source_checkpoint_equal": True}
    r.validate_live_preflight(preflight)
    if field in preflight["hashes"]:
        preflight["hashes"][field]["actual"] = "changed"
    else:
        preflight[field] = False
    with pytest.raises(ValueError, match="source/model/config drift"):
        r.validate_live_preflight(preflight)


def test_whole_baseline_matches_actual_production(retained):
    case, pair, config = retained
    provider = r.base.RecordedProvider(r.SimpleNamespace(name=config.cross_encoder_rerank.provider,
        model=config.cross_encoder_rerank.model), replay=pair["arms"]["A"]["calls"])
    with r.no_network():
        result = r.whole_execute(case, pair, config, "A", provider)
        assert result["complete"]
        for key in ("outputs", "features", "meta_predictions"):
            assert r.base.encoded(result[key]) == r.base.encoded(pair["arms"]["A"][key])
        assert r.production_parity(case, pair, config, result)["passed"]
    assert result["rerank_seconds"] > 0 and result["setup_seconds"] > 0


@pytest.mark.parametrize("first_score,expected", [(.1, [0]), (.3, []), (.9, [])])
def test_whole_selective_uses_current_first_scores_and_production_downstream(retained, first_score, expected):
    import copy
    case, original, config = retained
    pair = copy.deepcopy(original)
    case = {"id": case["id"], "query": "uniqueterm"}
    for item in pair["pool"]:
        item["item"]["content"] = "other"
    pair["pool"][0]["item"]["content"] = " " * 850 + "uniqueterm"

    class FixtureProvider:
        name, model = config.cross_encoder_rerank.provider, config.cross_encoder_rerank.model

        def __init__(self):
            self.calls = 0

        def rerank(self, query, documents, top_n):
            self.calls += 1
            return [r.base.RerankScore(index=i, score=(first_score if i == 0 else .9) if self.calls == 1 else .8)
                    for i in range(len(documents))]

    provider = r.base.RecordedProvider(FixtureProvider())
    with r.no_network():
        result = r.whole_execute(case, pair, config, "S", provider)
    assert result["complete"]
    assert result["selection"]["selected"] == expected
    assert result["selection"]["eligible"] == expected
    assert len(provider.calls) == 1 + bool(expected)
    assert len(result["features"]) == len(result["meta_predictions"]) == len(pair["pool"])
    assert len(result["outputs"]) == 10


def test_fresh_provider_protocol_and_timeouts(retained, monkeypatch):
    _, _, config = retained
    requests = []

    def response(url, timeout, payload):
        requests.append((url, timeout, payload))
        return '{"results": [{"index": 0, "relevance_score": 0.2}]}'

    monkeypatch.setattr(r, "smoke_json", response)
    provider = r.FreshProvider(config.cross_encoder_rerank, r.time.monotonic() + 100)
    recorded = r.base.RecordedProvider(provider)
    recorded.rerank("query", ["first"], 1)
    recorded.rerank("query", ["expanded"], 1)
    assert [row[1] for row in requests] == [60, 30]
    assert requests[0][2]["documents"] == ["first"]
    assert len(provider.raw) == 2
    provider.deadline = r.time.monotonic()
    with pytest.raises(TimeoutError):
        recorded.rerank("query", ["first"], 1)
    assert len(requests) == 2


def test_large_summary_incomplete_denominator():
    manifest = r.json.loads((r.base.OUT / "manifest.json").read_text())
    report = r.large_summary(manifest["cases"], [])
    assert report["denominator"] == 192 and report["complete_pairs"] == 0
    assert report["slices"]["all192"]["denominator"] == 192
    assert report["slices"]["guards40"]["denominator"] == 40
    assert "ineligible" in report["gates"]