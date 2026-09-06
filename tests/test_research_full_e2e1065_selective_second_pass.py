import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import research_full_e2e1065_selective_second_pass as run


@pytest.mark.parametrize("budget", [0, -1, True, 10801, float("nan"), float("inf"), "10800"])
def test_extension_invalid_budget(budget):
    with pytest.raises(ValueError, match="budget"):
        run.extension_budget(budget)


def test_extension_deadline_cannot_reset():
    manifest = {"frozen_at": 100., "deadline_seconds": 10800}
    state = {"budget_started_at": 101.}
    with pytest.raises(ValueError, match="deadline"):
        run.extension_deadline(manifest, state)
    state["budget_started_at"] = 100.
    assert run.extension_deadline(manifest, state) == 10900


@pytest.mark.parametrize("key", ["n_ctx", "n_batch", "n_ubatch"])
def test_extension_runtime_drift(key):
    props = {"n_ctx": 40960, "n_batch": 2048, "n_ubatch": 2048}
    run.validate_runtime_properties(props)
    props[key] += 1
    with pytest.raises(ValueError, match="runtime"):
        run.validate_runtime_properties(props)


def test_extension_runtime_missing():
    with pytest.raises(ValueError, match="runtime"):
        run.validate_runtime_properties({})


@pytest.mark.parametrize("args, message", [
    (["run", "--attempt", "extension-repair-01", "--rerank-url", run.CE_OVERRIDE_URLS[0]], "initialize extension with smoke"),
    (["smoke", "--attempt", "attempt-05"], "extension output"),
    (["preflight"], "retained preflight"),
    (["smoke", "--attempt", "extension-repair-01"], "explicit CE18081")])
def test_extension_cli_fail_closed(args, message):
    import subprocess
    result = subprocess.run([sys.executable, run.__file__, *args, "--parent-attempt", "attempt-04"],
                            text=True, capture_output=True, timeout=10)
    assert result.returncode == 2
    assert message in result.stderr


@pytest.mark.parametrize("args", ["--ctx-size 40960 --batch-size 2048 --ubatch-size 2048",
                                  "-c 40960 -b 2048 -ub 2048",
                                  "--ctx-size=40960 --batch-size=2048 --ubatch-size=2048"])
def test_extension_runtime_listener_command(args):
    props = run.runtime_command_properties("/opt/bin/llama-server --port 18081 " + args)
    assert props == {"port": 18081, "n_ctx": 40960, "n_batch": 2048, "n_ubatch": 2048}


@pytest.mark.parametrize("command", ["other --port 18081 -c 40960 -b 2048 -ub 2048",
    "llama-server --port 18081 -c 8192 -b 2048 -ub 2048",
    "llama-server --port 8081 -c 40960 -b 2048 -ub 2048",
    "llama-server --port 18081 -c 40960 -b 2048",
    "llama-server --port 18081 -c 40960 -b 2048 -ub 2048 -c 8192"])
def test_extension_runtime_listener_rejects_drift(command):
    with pytest.raises(ValueError, match="runtime"):
        run.runtime_command_properties(command)


@pytest.fixture
def extension_parent(tmp_path, monkeypatch):
    tmp_path = tmp_path / "attempt-04"
    cases = [{"id": i, "order": "AS" if i % 2 == 0 else "SA", "query": "q",
              "labels": {"full": ["x"]}} for i in range(1065)]
    monkeypatch.setattr(run, "frozen_cases", lambda: cases)
    run.base.atomic(tmp_path / "manifest.json", {"cases": cases})
    pairs = []
    for case in cases[:782]:
        row = dict(case, complete=True, seconds=1., arms={a: {"complete": True,
            "ranked": ["x"], "e2e_seconds": 1., "rerank_seconds": .5,
            "retrieval_seconds": .5, "calls": []} for a in "AS"})
        file = f"pairs/{case['id']}.json"
        run.base.atomic(tmp_path / file, row)
        pairs.append(dict(case, complete=True, seconds=1., file=file, sha256=run.base.digest(tmp_path / file)))
    state = {"manifest_sha256": run.base.digest(tmp_path / "manifest.json"), "started_at": 1.,
             "status": "hard_cap", "errors": [], "pairs": pairs}
    run.base.atomic(tmp_path / "checkpoint.json", state)
    return tmp_path, state


@pytest.mark.parametrize("corruption", ["pair", "manifest", "checkpoint", "duplicate", "order", "prefix", "time"])
def test_extension_parent_corruption(extension_parent, corruption):
    root, state = extension_parent
    _, _, pins, rows = run.parent_evidence(root)
    assert len(rows) == 782
    if corruption == "pair":
        (root / state["pairs"][0]["file"]).write_text("{}")
    elif corruption == "manifest":
        (root / "manifest.json").write_text('{"cases": []}')
    else:
        if corruption == "duplicate":
            state["pairs"][1] = state["pairs"][0]
        elif corruption == "order":
            state["pairs"][0]["order"] = "SA"
        elif corruption == "prefix":
            state["pairs"][0]["id"] = 1000
        elif corruption == "time":
            state["started_at"] = None
        else:
            state["started_at"] = 2.
        run.base.atomic(root / "checkpoint.json", state)
    with pytest.raises(ValueError):
        run.parent_evidence(root, pins)


def test_extension_smoke_not_main_and_no_reset(tmp_path):
    run.base.atomic(tmp_path / "manifest.json", {})
    state = {"manifest_sha256": run.base.digest(tmp_path / "manifest.json"), "pairs": [],
             "smoke": [{"id": f"smoke-{i}", "complete": True} for i in range(4)],
             "started_at": None, "budget_started_at": 10.}
    assert run.evidence_rows(tmp_path, state, []) == []
    assert run.extension_deadline({"frozen_at": 10., "deadline_seconds": 10800}, state) == 10810
    state["started_at"] = 100.
    assert run.extension_deadline({"frozen_at": 10., "deadline_seconds": 10800}, state) == 10810


def test_extension_real_parent_freeze_new_hashes_and_resume(tmp_path, monkeypatch):
    from replay_pool_recall import load_config
    monkeypatch.setattr(run, "ATTEMPT", tmp_path)
    config = load_config(run.base.CONFIG)
    manifest = run.freeze(config, run.CE_OVERRIDE_URLS[0], "attempt-04", 10800)
    assert len(manifest["cases"]) == 283
    assert len(manifest["parent_pins"]) == 784
    assert len(manifest["hashes"]) == 357
    assert manifest["parent_runner_sha256"] != manifest["runner_sha256"]
    assert manifest["parent_tests_sha256"] != manifest["tests_sha256"]
    assert manifest["runner_sha256"] == run.base.digest(run.__file__)
    assert manifest["effective_runtime_delta"]["required_server_parameters"] == run.EXTENSION_PARAMETERS
    assert run.freeze(config, run.CE_OVERRIDE_URLS[0], "attempt-04", 10800) == manifest
    with pytest.raises(ValueError, match="resume drift"):
        run.freeze(config, run.CE_OVERRIDE_URLS[0], "attempt-04", 10000)


def test_extension_smoke_hash_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "ATTEMPT", tmp_path)
    state = {"smoke": []}
    with pytest.raises(ValueError, match="smoke4"):
        run.validate_extension_smoke(state)
    for i in range(4):
        path = tmp_path / "smoke" / f"{i}.json"
        run.base.atomic(path, {"id": f"smoke-{i}", "order": "AS" if i % 2 == 0 else "SA", "complete": True})
        state["smoke"].append({"id": f"smoke-{i}", "complete": True, "sha256": run.base.digest(path)})
    run.validate_extension_smoke(state)
    path.write_text("{}")
    with pytest.raises(ValueError, match="smoke evidence drift"):
        run.validate_extension_smoke(state)


def test_extension_campaign_smoke_run_resume_summary(extension_parent, monkeypatch):
    import json
    import signal
    import tempfile
    root, _ = extension_parent
    monkeypatch.setattr(run, "OUT", root.parent)
    monkeypatch.setattr(run, "ATTEMPT", root.parent / "extension-repair-01")
    parent, _, pins, parent_rows = run.parent_evidence(root)
    manifest = dict(parent, cases=parent["cases"][782:], parent_attempt="attempt-04", parent_pins=pins,
        frozen_at=run.time.time(), deadline_seconds=10800, hashes={}, cache_hashes={},
        runner_sha256=run.base.digest(run.__file__),
        tests_sha256=run.base.digest(__file__), selective_runner_sha256=run.base.digest(run.selective.__file__),
        source_manifest_sha256=run.base.digest(run.base.OUT / "manifest.json"),
        source_checkpoint_sha256=run.base.digest(run.base.OUT / "checkpoint.json"),
        preflight_sha256=run.base.digest(run.PREFLIGHT))
    run.base.atomic(run.ATTEMPT / "manifest.json", manifest)
    monkeypatch.setattr(run, "freeze", lambda *args: manifest)
    monkeypatch.setattr(run, "runtime_properties", lambda url: dict(run.EXTENSION_PARAMETERS))
    old = json.loads(run.PREFLIGHT.read_text())["current_services"]
    monkeypatch.setattr(run, "service_metadata", lambda config: {
        k.replace(run.FROZEN_CE_ORIGIN, "http://localhost:18081"): v for k, v in old.items()})
    monkeypatch.setattr(run, "build_arms", lambda config: ({}, []))
    monkeypatch.setattr(sys, "addaudithook", lambda hook: None)
    monkeypatch.setattr(signal, "signal", lambda *args: None)
    monkeypatch.setattr(signal, "setitimer", lambda *args: None)
    monkeypatch.setattr(tempfile, "tempdir", tempfile.tempdir)
    seen = []
    def pair(arms, case, config, parity=False):
        seen.append((case["id"], parity))
        return dict(parent_rows[0], id=case["id"], order=case["order"])
    monkeypatch.setattr(run, "pair", pair)
    for limit, expected in ((0, 0), (1, 1), (1, 2)):
        assert run.campaign(limit, run.CE_OVERRIDE_URLS[0], "attempt-04") == 0
        state = json.loads((run.ATTEMPT / "checkpoint.json").read_text())
        assert len(state["pairs"]) == expected
        assert (state["started_at"] is None) == (expected == 0)
        assert state["budget_started_at"] == manifest["frozen_at"]
    assert seen == [(f"smoke-{i}", True) for i in range(4)] + [(782, False), (783, False)]
    report = run.extension_summary(manifest, state)
    assert report["complete"] == 784
    assert report["denominator"] == 1065
    assert report["parent"]["complete"] == report["parent"]["denominator"] == 782
    assert report["segment"]["complete"] == 2
    assert report["segment"]["denominator"] == 283
    assert report["promotion"] is False
    monkeypatch.setattr(run.time, "time", lambda: manifest["frozen_at"] + 10801)
    assert run.campaign(1, run.CE_OVERRIDE_URLS[0], "attempt-04") == 2
    assert len(seen) == 6


def test_endpoint_effective_config_is_copy():
    from dataclasses import asdict
    from replay_pool_recall import load_config
    config = load_config(run.base.CONFIG)
    before = asdict(config)
    effective = run.runtime_config(config, "http://localhost:18081/v1/rerank")
    assert effective is not config
    assert effective.cross_encoder_rerank is not config.cross_encoder_rerank
    assert asdict(config) == before
    assert run.differences(before, asdict(effective)) == [{
        "field": ".cross_encoder_rerank.url", "frozen": config.cross_encoder_rerank.url,
        "current": "http://localhost:18081/v1/rerank"}]


@pytest.mark.parametrize("url", ["http://localhost:8081/rerank", "http://remote:18081/rerank",
    "https://localhost:18081/v1/rerank", "http://localhost:18081/rerank",
    "http://localhost:18081/rerank?x=1", "http://user@localhost:18081/rerank"])
def test_endpoint_rejects_unapproved_override(url):
    from replay_pool_recall import load_config
    with pytest.raises(ValueError, match="endpoint"):
        run.runtime_config(load_config(run.base.CONFIG), url)


def test_endpoint_metadata_uses_actual_url_and_strict_checks(monkeypatch):
    import io
    import json
    from replay_pool_recall import load_config
    config = run.runtime_config(load_config(run.base.CONFIG), "http://localhost:18081/v1/rerank")
    seen = []
    def fetch(url, timeout):
        seen.append(url)
        return io.StringIO(json.dumps({"data": [{"id": "same-model", "created": 1}]}))
    monkeypatch.setattr("urllib.request.urlopen", fetch)
    fresh = run.service_metadata(config)
    assert seen[:2] == ["http://localhost:18081/health", "http://localhost:18081/v1/models"]
    assert not any(":8081/" in url for url in seen)
    old = {"http://127.0.0.1:8081/health": {"status": "ok"},
           "http://127.0.0.1:8081/v1/models": fresh[seen[1]]}
    current = {seen[0]: {"status": "ok"}, seen[1]: fresh[seen[1]]}
    run.check_services(old, current, config.cross_encoder_rerank.url)
    current[seen[1]] = {"data": [{"id": "other-model", "created": 1}]}
    with pytest.raises(ValueError, match="metadata drift"):
        run.check_services(old, current, config.cross_encoder_rerank.url)
    with pytest.raises(ValueError, match="inventory drift"):
        run.check_services(old, {}, config.cross_encoder_rerank.url)


def test_endpoint_freeze_preserves_baseline_and_rejects_resume_change(tmp_path, monkeypatch):
    import json
    from dataclasses import asdict
    from replay_pool_recall import load_config
    monkeypatch.setattr(run, "ATTEMPT", tmp_path)
    config = load_config(run.base.CONFIG)
    preflight = run.PREFLIGHT.read_bytes()
    manifest = run.freeze(config, "http://localhost:18081/v1/rerank")
    assert manifest["resolved_config"] == json.loads(run.base.encoded(asdict(config)))
    assert manifest["effective_resolved_config"]["cross_encoder_rerank"]["url"] == "http://localhost:18081/v1/rerank"
    assert manifest["effective_runtime_delta"] == {
        "rerank_url": {"frozen": config.cross_encoder_rerank.url, "effective": "http://localhost:18081/v1/rerank"},
        "common_arms": ["A", "S"], "required_server_parameters": {"batch": 2048, "ubatch": 2048, "ctx": 8192}}
    assert run.freeze(config, "http://localhost:18081/v1/rerank") == json.loads((tmp_path / "manifest.json").read_text())
    for override in (None, "http://127.0.0.1:18081/v1/rerank"):
        with pytest.raises(ValueError, match="resume drift"):
            run.freeze(config, override)
    assert run.PREFLIGHT.read_bytes() == preflight


def test_http_error_diagnostics_preserve_original_and_bound_body():
    import httpx
    from datetime import datetime
    request = httpx.Request("POST", "http://localhost:8002/rerank")
    response = httpx.Response(500, request=request, content=b"failure" * 2000,
                              headers={"x-request-id": "server-123", "set-cookie": "secret",
                                       "authorization": "secret", "content-type": "text/plain"})
    error = httpx.HTTPStatusError("server error", request=request, response=response)
    class Provider:
        name, model = "test", "test"
        def rerank(self, *args):
            raise error
    recorder = run.DiagnosticProvider(Provider())
    with pytest.raises(httpx.HTTPStatusError) as caught:
        recorder.rerank("q", ["doc"], 1)
    assert caught.value is error
    call = recorder.calls[0]
    diagnostic = call["diagnostic"]
    assert diagnostic["status"] == 500
    assert diagnostic["body_truncated"] is True
    assert len(diagnostic["body"].encode()) <= run.ERROR_BODY_BYTES
    assert diagnostic["headers"] == {"x-request-id": "server-123", "content-type": "text/plain",
                                      "content-length": "14000"}
    assert "HTTPStatusError" in diagnostic["traceback"]
    assert datetime.fromisoformat(call["started_utc"]).utcoffset().total_seconds() == 0
    assert call["finished_utc"] >= call["started_utc"]
    assert call["correlation_id"]
    assert "error" in call


def test_diagnostic_failure_does_not_mask_http_error():
    import httpx
    request = httpx.Request("POST", "http://localhost/rerank")
    response = httpx.Response(500, request=request, stream=httpx.ByteStream(b"unread"))
    error = httpx.HTTPStatusError("original", request=request, response=response)
    class Provider:
        name, model = "test", "test"
        def rerank(self, *args):
            raise error
    recorder = run.DiagnosticProvider(Provider())
    with pytest.raises(httpx.HTTPStatusError) as caught:
        recorder.rerank("q", ["doc"], 1)
    assert caught.value is error
    assert recorder.calls[0]["diagnostic"]["status"] == 500
    assert "diagnostic_error" in recorder.calls[0]["diagnostic"]


def test_production_urllib_http500_body(monkeypatch):
    import io
    from email.message import Message
    from urllib.error import HTTPError
    from code_diver.reranking.llama_cpp_rerank_provider import LlamaCppRerankProvider
    headers = Message()
    headers["X-Request-ID"] = "request-500"
    headers["Set-Cookie"] = "secret"
    body = io.BytesIO(b"server failure" * 1000)
    error = HTTPError("http://localhost/rerank", 500, "Internal Server Error", headers, body)
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr("urllib.request.urlopen", fail)
    recorder = run.DiagnosticProvider(LlamaCppRerankProvider("test", "http://localhost/rerank"))
    with pytest.raises(HTTPError) as caught:
        recorder.rerank("q", ["doc"], 1)
    assert caught.value is error
    diagnostic = recorder.calls[0]["diagnostic"]
    assert diagnostic["status"] == 500
    assert diagnostic["headers"] == {"x-request-id": "request-500"}
    assert diagnostic["body"].startswith("server failure")
    assert diagnostic["body_truncated"]
    assert body.tell() == run.ERROR_BODY_BYTES + 1


def test_non_http_and_wrapped_errors():
    import httpx
    request = httpx.Request("POST", "http://localhost/rerank")
    response = httpx.Response(503, request=request, content=b"unavailable")
    cause = httpx.HTTPStatusError("original", request=request, response=response)
    wrapper = RuntimeError("wrapped")
    wrapper.__cause__ = cause
    assert run.error_diagnostic(wrapper)["status"] == 503
    assert "status" not in run.error_diagnostic(TimeoutError("timeout"))


def test_fresh_attempt_never_overwrites_and_resume_requires_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "OUT", tmp_path)
    monkeypatch.setattr(run, "ATTEMPT", run.ATTEMPT)
    for name in ("attempt-03", "../attempt-04", "attempt-x"):
        with pytest.raises(ValueError):
            run.select_attempt(name)
    run.select_attempt("attempt-04")
    with pytest.raises(FileExistsError):
        run.select_attempt("attempt-04")
    with pytest.raises(ValueError):
        run.select_attempt("attempt-04", resume=True)
    for name in ("manifest.json", "checkpoint.json"):
        (run.ATTEMPT / name).write_text("{}")
    run.select_attempt("attempt-04", resume=True)


def test_swallowed_provider_failure_still_fails_closed():
    from types import SimpleNamespace
    class Provider:
        name, model = "test", "test"
        def rerank(self, *args):
            raise RuntimeError("failed")
    arm = SimpleNamespace(rerank_provider=run.DiagnosticProvider(Provider()),
                          trace_logger=SimpleNamespace(events=[]),
                          ce_meta_feature_extractor=SimpleNamespace(rows=[], seconds=0),
                          _ce_meta_ranker=SimpleNamespace(values=[], seconds=0, error=None),
                          base_strategy=SimpleNamespace(pool=[], seconds=0))
    def search(query, limit):
        try:
            arm.rerank_provider.rerank(query, ["doc"], 1)
        except RuntimeError:
            pass
        arm.trace_logger.events.append({"name": "cross_encoder_ce_meta_ranker"})
        return []
    arm.search = search
    result = run.execute(arm, "q")
    assert not result["complete"]
    assert result["calls"][0]["diagnostic"]["error"] == "RuntimeError('failed')"


@pytest.mark.parametrize("max_pairs", [0, 1])
@pytest.mark.parametrize("rerank_url", [None, "http://localhost:18081/v1/rerank"])
def test_campaign_smoke_only_and_bounded_run(tmp_path, monkeypatch, max_pairs, rerank_url):
    import json
    import signal
    import tempfile
    import replay_pool_recall
    monkeypatch.setattr(run, "ATTEMPT", tmp_path)
    monkeypatch.setattr(run, "PREFLIGHT", tmp_path / "preflight.json")
    run.PREFLIGHT.write_text(json.dumps({"current_services": {}}))
    manifest = {"cases": [{"id": i, "order": "AS"} for i in range(1065)],
                "hashes": {}, "cache_hashes": {}, "runner_sha256": run.base.digest(run.__file__)}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    baseline = replay_pool_recall.load_config(run.base.CONFIG)
    expected_url = rerank_url or baseline.cross_encoder_rerank.url
    def freeze(config, override):
        assert config is baseline
        assert override == rerank_url
        return manifest
    monkeypatch.setattr(run, "freeze", freeze)
    monkeypatch.setattr(replay_pool_recall, "load_config", lambda path: baseline)
    metadata_calls = []
    def metadata(config):
        assert config.cross_encoder_rerank.url == expected_url
        metadata_calls.append(config)
        return {}
    monkeypatch.setattr(run, "service_metadata", metadata)
    def build(config):
        assert config is not baseline
        assert config.cross_encoder_rerank.url == expected_url
        return {}, []
    monkeypatch.setattr(run, "build_arms", build)
    monkeypatch.setattr(sys, "addaudithook", lambda hook: None)
    monkeypatch.setattr(signal, "signal", lambda *args: None)
    monkeypatch.setattr(signal, "setitimer", lambda *args: None)
    monkeypatch.setattr(tempfile, "tempdir", tempfile.tempdir)
    seen = []
    def pair(arms, case, config, parity=False):
        assert config.cross_encoder_rerank.url == expected_url
        seen.append((case["id"], parity))
        return dict(case, complete=True, seconds=1)
    monkeypatch.setattr(run, "pair", pair)
    monkeypatch.setattr(run, "summary", lambda manifest, state: {
        "status": state["status"], "attempted": len(state["pairs"]),
        "complete": len(state["pairs"]), "elapsed_seconds": 0, "errors": state["errors"]})
    assert run.campaign(max_pairs, rerank_url) == 0
    assert len(metadata_calls) == 2
    state = json.loads((tmp_path / "checkpoint.json").read_text())
    assert state["status"] == "segment_boundary"
    assert len(state["pairs"]) == max_pairs
    assert (state["started_at"] is None) == (max_pairs == 0)
    assert seen[:4] == [(f"smoke-{i}", True) for i in range(4)]
    assert len(seen) == 4 + max_pairs
    assert len(state["smoke"]) == 4


def test_schedule_balanced_and_deterministic():
    rows = {i: {"id": i, "query": str(i), "expected": ["a"]} for i in range(1065)}
    a = run.schedule(rows)
    assert a == run.schedule(dict(reversed(list(rows.items()))))
    assert len({r["id"] for r in a}) == 1065
    assert sum(r["order"] == "AS" for r in a) == 533
    assert sum(r["order"] == "SA" for r in a) == 532


def test_schedule_rejects_reduced_denominator():
    with pytest.raises(ValueError):
        run.schedule({})


def test_hash_drift_and_missing_fail_closed(tmp_path):
    p = tmp_path / "dependency"
    p.write_text("frozen")
    hashes = {str(p): run.base.digest(p)}
    run.verify_hashes(hashes)
    p.write_text("drift")
    with pytest.raises(ValueError, match="drift"):
        run.verify_hashes(hashes)
    p.unlink()
    with pytest.raises(ValueError):
        run.verify_hashes(hashes)


def test_resume_rejects_manifest_and_pair_drift():
    state = {"manifest_sha256": "old", "pairs": []}
    with pytest.raises(ValueError):
        run.validate_state(state, "new", [])
    state = {"manifest_sha256": "new", "started_at": 1,
             "pairs": [{"id": 1, "order": "SA", "complete": True}]}
    with pytest.raises(ValueError, match="non-prefix, changed order"):
        run.validate_state(state, "new", [{"id": 1, "order": "AS"}])


@pytest.mark.parametrize("started_at", [None, "missing", "123", True, False, 0, -1,
                                       float("nan"), float("inf"), -float("inf"), [], {}, 2000])
def test_resume_rejects_invalid_main_started_at(monkeypatch, started_at):
    monkeypatch.setattr(run.time, "time", lambda: 1000)
    case = {"id": 1, "order": "AS"}
    state = {"manifest_sha256": "frozen", "pairs": [dict(case, complete=True)]}
    if started_at != "missing":
        state["started_at"] = started_at
    with pytest.raises(ValueError, match="started_at"):
        run.validate_state(state, "frozen", [case])


@pytest.mark.parametrize("started_at", [1, 999.5, 1000])
def test_resume_preserves_valid_main_started_at(monkeypatch, started_at):
    monkeypatch.setattr(run.time, "time", lambda: 1000)
    case = {"id": 1, "order": "AS"}
    state = {"manifest_sha256": "frozen", "pairs": [dict(case, complete=True)],
             "started_at": started_at}
    run.validate_state(state, "frozen", [case])
    assert state["started_at"] == started_at


def test_resume_accepts_smoke_only_without_main_deadline():
    state = {"manifest_sha256": "frozen", "pairs": [], "started_at": None,
             "smoke": [{"id": f"smoke-{i}", "complete": True} for i in range(4)]}
    run.validate_state(state, "frozen", [])
    assert state["started_at"] is None


def test_selective_has_no_refill_or_labels():
    from types import SimpleNamespace
    scores = [run.base.RerankScore(index=i, score=.1) for i in range(25)]
    candidates = [SimpleNamespace(item=SimpleNamespace(content="x" * 851)) for _ in scores]
    candidates[24].item.content = "x" * 850 + " needle "
    assert run.selection("needle", candidates, scores) == []
    candidates[0].item.content = "x" * 850 + " needle "
    assert run.selection("needle", candidates, scores) == [0]
    scores[0] = run.base.RerankScore(index=0, score=.3)
    assert run.selection("needle", candidates, scores) == [24]


def test_missing_bounds_keep_planned_denominator():
    result = run.quality([(1., 1.)], 1065)
    assert result["planned"] == 1065
    assert result["missing"] == 1064
    assert result["A_bounds"] == [1 / 1065, 1.]
    assert result["delta_bounds"] == [-1064 / 1065, 1064 / 1065]


def test_embedding_permission_rotation_authorized_only_for_embedding():
    import copy
    old = {"data": [{"id": "embedding", "created": 1,
                     "permission": [{"id": "modelperm-old", "created": 1}]}]}
    new = copy.deepcopy(old)
    new["data"][0]["created"] = 2
    assert run.validate_model_metadata(old, new, embedding=True)
    new["data"][0]["permission"][0]["id"] = "modelperm-new"
    new["data"][0]["permission"][0]["created"] = 2
    assert len(run.validate_model_metadata(old, new, embedding=True)) == 3
    with pytest.raises(ValueError, match="metadata drift"):
        run.validate_model_metadata(old, new, embedding=False)


@pytest.mark.parametrize("change", ["model", "flag", "nested", "type", "missing", "length"])
def test_metadata_rejects_other_drift(change):
    import copy
    old = {"data": [{"id": "embedding", "created": 1, "permission": [
        {"id": "perm", "created": 1, "allow_sampling": True, "nested": {"x": 1}}]}]}
    new = copy.deepcopy(old)
    p = new["data"][0]["permission"][0]
    if change == "model":
        new["data"][0]["id"] = "other"
    elif change == "flag":
        p["allow_sampling"] = False
    elif change == "nested":
        p["nested"]["x"] = True
    elif change == "type":
        p["created"] = True
    elif change == "missing":
        del p["id"]
    else:
        new["data"][0]["permission"].append(copy.deepcopy(p))
    with pytest.raises(ValueError, match="metadata drift"):
        run.validate_model_metadata(old, new, embedding=True)


def test_frozen_full_dataset_and_slices():
    cases = run.frozen_cases()
    assert len(cases) == 1065
    assert sum("where" in c["labels"] for c in cases) == 78
    assert sum("mech" in c["labels"] for c in cases) == 229


def test_retrieval_caches_isolated_and_restored_on_error():
    import code_diver.strategies.hybrid_retrieval_strategy as hybrid
    class Strategy:
        def search(self, query, limit):
            hybrid._SHARED_GRAPHS[query] = limit
            if query == "error":
                raise RuntimeError("retrieval failed")
            return [query]
    original = hybrid._SHARED_GRAPHS
    a, s = run.RetrievalRecorder(Strategy()), run.RetrievalRecorder(Strategy())
    assert a.search("a", 34) == ["a"]
    assert not s.caches["_SHARED_GRAPHS"]
    assert hybrid._SHARED_GRAPHS is original
    with pytest.raises(RuntimeError):
        s.search("error", 34)
    assert "error" not in a.caches["_SHARED_GRAPHS"]
    assert hybrid._SHARED_GRAPHS is original


def test_selective_override_uses_current_scores_and_max_merge():
    from types import SimpleNamespace
    from replay_pool_recall import load_config
    from code_diver.domain import CodeItem, SearchResult
    config = load_config(run.base.CONFIG)
    candidates = [SearchResult(CodeItem(id="a", path="a.java", content="x" * 850 + " needle ",
                                       title="a", start_line=1, end_line=1), .5)]
    class Provider:
        def __init__(self):
            self.calls = []
        def rerank(self, query, docs, top_n):
            self.calls.append((query, docs, top_n))
            return [run.base.RerankScore(index=0, score=.01)]
    provider = Provider()
    arm = SimpleNamespace(policy="S", config=config.cross_encoder_rerank,
                          repository_root=config.root, rerank_provider=provider)
    scores = [run.base.RerankScore(index=0, score=.1)]
    actual = run.selective.WholeRerankArm._with_second_pass(arm, "needle", candidates, scores)
    assert actual[0].score == .1
    assert arm.selection == {"eligible": [0], "selected": [0]}
    assert len(provider.calls) == 1
    actual = run.selective.WholeRerankArm._with_second_pass(
        arm, "needle", candidates, [run.base.RerankScore(index=0, score=.4)])
    assert actual[0].score == .4
    assert len(provider.calls) == 1