"""Independent warm production full-search A/S campaign; no production edits."""
from __future__ import annotations

import json
import random
import subprocess
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import numpy as np

import research_large_search_eval as base
import research_selective_second_pass as selective

OUT = Path("artifacts/research/2026-09-05/full-e2e1065-selective-second-pass")
ERROR_BODY_BYTES = 4096
SAFE_HEADERS = ("content-type", "content-length", "date", "server", "retry-after",
                "x-request-id", "x-correlation-id", "traceparent")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def error_diagnostic(exc):
    from urllib.error import HTTPError
    result = {"error": repr(exc), "utc": utc_now(),
              "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))}
    try:
        current, seen = exc, set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            response = getattr(current, "response", None)
            if isinstance(current, HTTPError):
                result["status"] = current.code
                result["headers"] = {k: current.headers[k][:512] for k in SAFE_HEADERS if k in current.headers}
                content = current.read(ERROR_BODY_BYTES + 1)
                result["body"] = content[:ERROR_BODY_BYTES].decode("utf-8", errors="ignore")
                result["body_truncated"] = len(content) > ERROR_BODY_BYTES
                break
            if response is not None:
                result["status"] = response.status_code
                result["headers"] = {k: response.headers[k][:512] for k in SAFE_HEADERS if k in response.headers}
                content = response.content
                result["body"] = content[:ERROR_BODY_BYTES].decode("utf-8", errors="ignore")
                result["body_truncated"] = len(content) > ERROR_BODY_BYTES
                break
            current = current.__cause__ or current.__context__
    except Exception as diagnostic_error:
        result["diagnostic_error"] = repr(diagnostic_error)
    return result


class DiagnosticProvider(base.RecordedProvider):
    def rerank(self, query, documents, top_n):
        started, correlation = utc_now(), str(uuid.uuid4())
        index = len(self.calls)
        try:
            return super().rerank(query, documents, top_n)
        except BaseException as exc:
            if len(self.calls) > index:
                self.calls[index]["diagnostic"] = error_diagnostic(exc)
            raise
        finally:
            if len(self.calls) > index:
                self.calls[index].update(started_utc=started, finished_utc=utc_now(),
                                         correlation_id=correlation)


def select_attempt(name, resume=False):
    import re
    global ATTEMPT
    if not re.fullmatch(r"attempt-\d{2,}", name) or int(name.split("-")[1]) < 4:
        raise ValueError("new attempt-04 or higher required; historical attempts are read-only")
    path = OUT / name
    if resume:
        if not (path / "manifest.json").is_file() or not (path / "checkpoint.json").is_file():
            raise ValueError("resume requires existing manifest and checkpoint")
    else:
        path.mkdir(parents=True, exist_ok=False)
    ATTEMPT = path


def schedule(rows):
    if len(rows) != 1065:
        raise ValueError("fixed denominator must be 1065")
    ids = sorted(rows)
    random.Random(42).shuffle(ids)
    return [dict(rows[i], order="AS" if j % 2 == 0 else "SA") for j, i in enumerate(ids)]


def verify_hashes(hashes):
    actual = {}
    for name, expected in hashes.items():
        if not Path(name).is_file():
            raise ValueError(f"missing dependency: {name}")
        actual[name] = base.digest(name)
        if actual[name] != expected:
            raise ValueError(f"dependency drift: {name}")
    return actual


def validate_state(state, manifest_hash, cases):
    if state["manifest_sha256"] != manifest_hash:
        raise ValueError("manifest drift")
    pairs = state["pairs"]
    if "started_at" not in state:
        raise ValueError("missing checkpoint started_at")
    started_at = state["started_at"]
    if started_at is None:
        if pairs:
            raise ValueError("main pairs require started_at")
    elif type(started_at) not in (int, float) or not 0 < started_at <= time.time():
        raise ValueError("invalid checkpoint started_at: expected finite positive non-future timestamp")
    if len(pairs) > len(cases):
        raise ValueError("too many pairs")
    for pair, case in zip(pairs, cases):
        if (pair["id"], pair["order"]) != (case["id"], case["order"]) or not pair["complete"]:
            raise ValueError("non-prefix, changed order or incomplete checkpoint")


def selection(query, candidates, scores):
    return [i for i in selective.eligible(scores) if selective.evidence(candidates[i].item.content, query)]


def quality(values, planned):
    if planned <= 0 or len(values) > planned:
        raise ValueError("invalid denominator")
    missing = planned - len(values)
    a = sum(v[0] for v in values)
    s = sum(v[1] for v in values)
    result = {"planned": planned, "complete": len(values), "missing": missing,
              "A_bounds": [a / planned, (a + missing) / planned],
              "S_bounds": [s / planned, (s + missing) / planned],
              "delta_bounds": [(s - a - missing) / planned, (s - a + missing) / planned]}
    if values:
        data = np.asarray(values)
        rng = np.random.default_rng(42)
        means = np.empty(10000)
        for i in range(10000):
            sample = data[rng.integers(0, len(data), len(data))]
            means[i] = np.mean(sample[:, 1] - sample[:, 0])
        result.update(A=float(np.mean(data[:, 0])), S=float(np.mean(data[:, 1])),
                      delta=float(np.mean(data[:, 1] - data[:, 0])),
                      ci95=np.percentile(means, [2.5, 97.5]).tolist())
    return result


def differences(old, new, prefix=""):
    if isinstance(old, dict) and isinstance(new, dict):
        return [row for key in sorted(old.keys() | new.keys())
                for row in differences(old.get(key), new.get(key), f"{prefix}.{key}")]
    if isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
        return [row for i, (a, b) in enumerate(zip(old, new))
                for row in differences(a, b, f"{prefix}[{i}]")]
    return [] if old == new else [{"field": prefix, "frozen": old, "current": new}]


def validate_model_metadata(recorded, fresh, embedding=False):
    import re
    changes = []

    def compare(old, new, path):
        if type(old) is not type(new):
            raise ValueError(f"served model metadata drift: type {path}")
        if isinstance(old, dict):
            if old.keys() != new.keys():
                raise ValueError(f"served model metadata drift: keys {path}")
            for key in old:
                compare(old[key], new[key], f"{path}.{key}" if path else key)
        elif isinstance(old, list):
            if len(old) != len(new):
                raise ValueError(f"served model metadata drift: length {path}")
            for i, (a, b) in enumerate(zip(old, new)):
                compare(a, b, f"{path}[{i}]")
        else:
            timestamp = re.fullmatch(r"data\[\d+\]\.created", path)
            permission = embedding and re.fullmatch(r"data\[\d+\]\.permission\[\d+\]\.(id|created)", path)
            if timestamp or permission:
                required = str if path.endswith(".id") else int
                if type(old) is not required:
                    raise ValueError(f"served model metadata drift: exempt field type {path}")
            if old != new:
                if not (timestamp or permission):
                    raise ValueError(f"served model metadata drift: {path}")
                changes.append({"field": path, "frozen": old, "current": new})

    if not isinstance(recorded, dict) or not isinstance(recorded.get("data"), list):
        raise ValueError("served model metadata drift: invalid inventory")
    compare(recorded, fresh, "")
    return changes


def preflight():
    started = time.monotonic()
    output = OUT / "attempt-02" / "preflight.json"
    if output.exists():
        raise ValueError("refusing to overwrite retained preflight")
    manifest_path = base.OUT / "manifest.json"
    checkpoint_path = base.OUT / "checkpoint.json"
    manifest = json.loads(manifest_path.read_text())
    checkpoint = json.loads(checkpoint_path.read_text())
    report = {"status": "blocked", "planned": 1065, "attempted_pairs": 0, "complete_pairs": 0,
              "smoke_pairs": 0, "inference_requests": 0, "errors": [],
              "command": "PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/research_full_e2e1065_selective_second_pass.py",
              "source_manifest_sha256": base.digest(manifest_path),
              "source_checkpoint_sha256": base.digest(checkpoint_path),
              "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
              "git_status": subprocess.check_output(["git", "status", "--short"], text=True),
              "baseline_claim": "actual dirty checkout compared to previously frozen H91a; not clean champion",
              "runner_sha256": base.digest(__file__),
              "tests_sha256": base.digest("tests/test_research_full_e2e1065_selective_second_pass.py"),
              "python": sys.version}
    try:
        if checkpoint["manifest_sha256"] != report["source_manifest_sha256"]:
            raise ValueError("frozen checkpoint/manifest mismatch")
        report["actual_hashes"] = verify_hashes(manifest["hashes"])
        report["versions"] = {k: version(k) for k in manifest["versions"]}
        if report["versions"] != manifest["versions"]:
            raise ValueError("dependency version drift")
        old = checkpoint["services_before"]
        current = base.service_metadata()
        report.update(frozen_services=old, current_services=current, model_metadata_differences={})
        for url in current:
            if url.endswith("/models"):
                report["model_metadata_differences"][url] = differences(old[url], current[url])
                try:
                    validate_model_metadata(old[url], current[url], embedding=":8001/" in url)
                except ValueError as exc:
                    report["errors"].append(f"{url}: {exc}; only parent-authorized instance fields exempt")
        if report["errors"]:
            raise ValueError("served baseline metadata drift; stop before implementation/measurement")
        q = "http://localhost:6333/collections/intellij_h66b_budget_qwen"
        for key in ("config", "points_count", "indexed_vectors_count"):
            if base.encoded(old[q]["result"][key]) != base.encoded(current[q]["result"][key]):
                raise ValueError(f"Qdrant drift: {key}")
        if base.encoded(old["http://localhost:6333/aliases"]["result"]) != base.encoded(current["http://localhost:6333/aliases"]["result"]):
            raise ValueError("Qdrant alias drift")
        report["status"] = "passed"
        report["loaded_weights_equivalence_proven"] = False
        report["metadata_rule"] = "data[*].created int; embedding only permission[*].id str and .created int; all other fields/types/structure strict"
    except Exception as exc:
        report["errors"].append(str(exc))
    finally:
        report["runtime_seconds"] = time.monotonic() - started
        base.atomic(output, report)
    print(json.dumps({k: report[k] for k in ("status", "planned", "attempted_pairs", "errors", "runtime_seconds")}))
    return 0 if report["status"] == "passed" else 2


PREFLIGHT = OUT / "attempt-02" / "preflight.json"
ATTEMPT = OUT / "attempt-03"
HARD_SECONDS = 7 * 3600
SEGMENT_SECONDS = 3300
PAIR_RESERVE = 240
SMOKE_QUERIES = (
    "Where is project opening implemented?",
    "How is editor document synchronization implemented?",
    "Where are module dependencies resolved?",
    "How are virtual file changes propagated?",
)


class RetrievalRecorder:
    def __init__(self, strategy):
        self.strategy = strategy
        self.pool = []
        self.seconds = 0.0
        self.caches = {name: {} for name in ("_SHARED_GRAPHS", "_SHARED_LEXICAL_INDEXES",
            "_SHARED_NEIGHBOR_INDEXES", "_SHARED_FILE_GRAPH_EXPANDERS", "_SHARED_FILE_GRAPH_CATALOGS")}

    def search(self, query, limit):
        import code_diver.strategies.hybrid_retrieval_strategy as hybrid
        previous = {name: getattr(hybrid, name) for name in self.caches}
        for name, cache in self.caches.items():
            setattr(hybrid, name, cache)
        tick = time.perf_counter()
        try:
            self.pool = self.strategy.search(query, limit)
            return self.pool
        finally:
            self.seconds = time.perf_counter() - tick
            for name, cache in previous.items():
                setattr(hybrid, name, cache)


def frozen_cases():
    datasets = {k: base.rows(p) for k, p in base.DATA.items()}
    if tuple(len(datasets[k]) for k in ("full", "where", "mech")) != (1065, 78, 229):
        raise ValueError("dataset sizes drift")
    full = datasets["full"]
    for data in datasets.values():
        if not data.keys() <= full.keys():
            raise ValueError("slice IDs outside full set")
        if any(c["query"] != full[i]["query"] for i, c in data.items()):
            raise ValueError("slice query conflict")
    return schedule({i: {"id": i, "query": c["query"],
                        "labels": {k: d[i]["expected"] for k, d in datasets.items() if i in d}}
                     for i, c in full.items()})


FROZEN_CE_ORIGIN = "http://127.0.0.1:8081"
CE_OVERRIDE_URLS = ("http://localhost:18081/v1/rerank", "http://127.0.0.1:18081/v1/rerank")
CE_SERVER_PARAMETERS = {"batch": 2048, "ubatch": 2048, "ctx": 8192}


def runtime_config(config, rerank_url=None):
    import copy
    effective = copy.deepcopy(config)
    if rerank_url is not None:
        if config.cross_encoder_rerank.url != FROZEN_CE_ORIGIN + "/v1/rerank" or rerank_url not in CE_OVERRIDE_URLS:
            raise ValueError("only frozen CE8081 to localhost CE18081 endpoint override permitted")
        effective.cross_encoder_rerank.url = rerank_url
    return effective


def service_metadata(config):
    from urllib.parse import urlsplit
    from urllib.request import urlopen
    parsed = urlsplit(config.cross_encoder_rerank.url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    urls = [origin + "/health", origin + "/v1/models",
            "http://127.0.0.1:8001/v1/models", "http://localhost:6333/aliases",
            "http://localhost:6333/collections/intellij_h66b_budget_qwen"]
    result = {}
    for url in urls:
        with urlopen(url, timeout=5) as response:
            result[url] = json.load(response)
    return result


def check_services(old, fresh, rerank_url=None):
    if rerank_url is not None:
        if rerank_url not in CE_OVERRIDE_URLS:
            raise ValueError("unapproved endpoint")
        origin = rerank_url.removesuffix("/v1/rerank")
        mapping = {FROZEN_CE_ORIGIN + suffix: origin + suffix for suffix in ("/health", "/v1/models")}
        old = {mapping.get(url, url): value for url, value in old.items()}
    if old.keys() != fresh.keys():
        raise ValueError("service inventory drift")
    for url in old:
        if url.endswith("/models"):
            validate_model_metadata(old[url], fresh[url], embedding=":8001/" in url)
        elif "/collections/" in url:
            for key in ("config", "points_count", "indexed_vectors_count"):
                if base.encoded(old[url]["result"][key]) != base.encoded(fresh[url]["result"][key]):
                    raise ValueError(f"Qdrant drift: {key}")
            if fresh[url]["result"]["status"] != "green":
                raise ValueError("Qdrant unhealthy")
        elif url.endswith("/aliases"):
            if base.encoded(old[url]["result"]) != base.encoded(fresh[url]["result"]):
                raise ValueError("aliases drift")
        elif base.encoded(old[url]) != base.encoded(fresh[url]):
            raise ValueError("health drift")


def freeze(config, rerank_url=None, parent_attempt=None, budget_seconds=10800):
    from dataclasses import asdict
    source = json.loads((base.OUT / "manifest.json").read_text())
    pre = json.loads(PREFLIGHT.read_text())
    if pre["status"] != "passed":
        raise ValueError("approved preflight required")
    verify_hashes(source["hashes"])
    if {k: version(k) for k in source["versions"]} != source["versions"]:
        raise ValueError("package drift")
    base.validate_config(config)
    if json.loads(base.encoded(asdict(config))) != source["resolved_config"]:
        raise ValueError("resolved configuration drift")
    effective = runtime_config(config, rerank_url)
    delta = {} if rerank_url is None else {
        "rerank_url": {"frozen": config.cross_encoder_rerank.url, "effective": rerank_url},
        "common_arms": ["A", "S"], "required_server_parameters": CE_SERVER_PARAMETERS}
    graph = Path(".code-diver/intellij-h37-jvm-graph.json")
    caches = [graph.with_suffix(".lexical-index.pickle"),
              graph.with_name(graph.stem + ".file-graph-catalog.json")]
    cache_hashes = {str(p): base.digest(p) for p in caches if p.exists()}
    manifest = dict(cases=frozen_cases(), hashes=source["hashes"], versions=source["versions"],
                    resolved_config=source["resolved_config"], policies=selective.POLICIES,
                    effective_resolved_config=json.loads(base.encoded(asdict(effective))),
                    effective_runtime_delta=delta,
                    cache_hashes=cache_hashes, selective_runner_sha256=base.digest(selective.__file__),
                    runner_sha256=base.digest(__file__), tests_sha256=base.digest(
                        "tests/test_research_full_e2e1065_selective_second_pass.py"),
                    source_manifest_sha256=base.digest(base.OUT / "manifest.json"),
                    preflight_sha256=base.digest(PREFLIGHT),
                    deadline_seconds=HARD_SECONDS, frozen_at=time.time(), smoke_queries=SMOKE_QUERIES,
                    baseline="actual dirty checkout; not clean champion; loaded weights equivalence unproven",
                    endpoint="wall actual search(query,10), independent retrieval and rerank per arm",
                    independence="not certified; overlapping slices are not additive",
                    git_status=subprocess.check_output(["git", "status", "--short"], text=True))
    if parent_attempt is not None:
        extension_budget(budget_seconds)
        if parent_attempt != "attempt-04" or rerank_url not in CE_OVERRIDE_URLS:
            raise ValueError("extension requires attempt-04 and CE18081")
        parent, state, pins, _ = parent_evidence(OUT / parent_attempt)
        for key in ("cases", "hashes", "versions", "resolved_config", "policies", "cache_hashes",
                    "selective_runner_sha256", "source_manifest_sha256", "preflight_sha256",
                    "effective_resolved_config"):
            if base.encoded(parent[key]) != base.encoded(manifest[key]):
                raise ValueError(f"parent dependency drift: {key}")
        source_state = json.loads((base.OUT / "checkpoint.json").read_text())
        if (source_state["manifest_sha256"] != manifest["source_manifest_sha256"] or
                base.digest(base.OUT / "checkpoint.json") != pre["source_checkpoint_sha256"]):
            raise ValueError("source checkpoint linkage drift")
        manifest.update(parent_attempt=parent_attempt, parent_pins=pins,
                        parent_runner_sha256=parent["runner_sha256"],
                        parent_tests_sha256=parent["tests_sha256"],
                        source_checkpoint_sha256=base.digest(base.OUT / "checkpoint.json"),
                        deadline_seconds=budget_seconds,
                        parent_deviation="parent required ctx8192; reported actual ctx40960; continuity unknown",
                        cases=manifest["cases"][PARENT_PAIRS:])
        manifest["effective_runtime_delta"]["required_server_parameters"] = EXTENSION_PARAMETERS
    manifest = json.loads(base.encoded(manifest))
    path = ATTEMPT / "manifest.json"
    if path.exists():
        old = json.loads(path.read_text())
        for key in ("cases", "hashes", "versions", "resolved_config", "policies", "runner_sha256",
                    "tests_sha256", "source_manifest_sha256", "preflight_sha256", "deadline_seconds",
                    "cache_hashes", "selective_runner_sha256", "effective_resolved_config", "effective_runtime_delta"):
            if key not in old or base.encoded(old[key]) != base.encoded(manifest[key]):
                raise ValueError(f"resume drift: {key}")
        for key in ("parent_attempt", "parent_pins", "parent_runner_sha256", "parent_tests_sha256",
                    "source_checkpoint_sha256", "parent_deviation"):
            if old.get(key) != manifest.get(key):
                raise ValueError(f"resume drift: {key}")
        return old
    base.atomic(path, manifest)
    return manifest


def build_arms(config):
    import copy
    from types import MethodType
    arms, stores = {}, []
    for policy in "AS":
        arm, store = base.build_production(copy.deepcopy(config))
        stores.append(store)
        arm.base_strategy = RetrievalRecorder(arm.base_strategy)
        arm.trace_logger = base.Trace()
        arm.ce_meta_feature_extractor = base.FeatureRecorder(arm.ce_meta_feature_extractor)
        arm._ce_meta_ranker = base.PredictionRecorder(arm._ce_meta_ranker)
        arm.rerank_provider = DiagnosticProvider(arm.rerank_provider)
        arm.policy = policy
        if policy == "S":
            arm._with_second_pass = MethodType(selective.WholeRerankArm._with_second_pass, arm)
        arms[policy] = arm
    for name in ("base_strategy", "rerank_provider", "ce_meta_feature_extractor", "hub_prior_scorer"):
        if getattr(arms["A"], name) is getattr(arms["S"], name):
            raise ValueError(f"shared arm state: {name}")
    if arms["A"]._ce_meta_ranker.booster is arms["S"]._ce_meta_ranker.booster:
        raise ValueError("shared meta booster")
    return arms, stores


def execute(arm, query):
    from dataclasses import asdict
    arm.rerank_provider.calls = []
    arm.trace_logger.events = []
    arm.rerank_failure_count = 0
    arm.selection = None
    arm.ce_meta_feature_extractor.rows = []
    arm.ce_meta_feature_extractor.seconds = 0
    arm._ce_meta_ranker.values = []
    arm._ce_meta_ranker.seconds = 0
    arm._ce_meta_ranker.error = None
    arm.base_strategy.pool = []
    arm.base_strategy.seconds = 0
    result = {"complete": False, "started_utc": utc_now()}
    tick = time.perf_counter()
    try:
        ranked = arm.search(query, 10)
        result["e2e_seconds"] = time.perf_counter() - tick
        result.update(ranked=[r.item.path for r in ranked], outputs=[asdict(r) for r in ranked])
    except (Exception, base.DeadlineExpired) as exc:
        result.update(error=repr(exc), diagnostic=error_diagnostic(exc), e2e_seconds=time.perf_counter() - tick)
    result["finished_utc"] = utc_now()
    result.update(calls=arm.rerank_provider.calls, events=arm.trace_logger.events,
                  features=arm.ce_meta_feature_extractor.rows, meta_predictions=arm._ce_meta_ranker.values,
                  meta_error=arm._ce_meta_ranker.error, failure_count=arm.rerank_failure_count,
                  selection=arm.selection, retrieval_seconds=arm.base_strategy.seconds,
                  pool=[asdict(c) for c in arm.base_strategy.pool])
    result["rerank_seconds"] = result["e2e_seconds"] - result["retrieval_seconds"]
    result["complete"] = ("error" not in result and not result["meta_error"] and not result["failure_count"]
                          and not any("error" in c for c in result["calls"])
                          and any(e["name"] == "cross_encoder_ce_meta_ranker" for e in result["events"]))
    return result


def pair(arms, case, config, parity=False):
    row = {"id": case["id"], "order": case["order"], "arms": {}, "complete": False,
           "started_utc": utc_now()}
    tick = time.perf_counter()
    for policy in case["order"]:
        result = execute(arms[policy], case["query"])
        row["arms"][policy] = result
        if not result["complete"]:
            row["error"] = f"critical full search failure: {policy}"
            break
        try:
            selective.validate_calls(result["calls"])
        except ValueError as exc:
            row["error"] = repr(exc)
            break
    row["seconds"] = time.perf_counter() - tick
    row["finished_utc"] = utc_now()
    if "error" not in row and parity:
        saved = row["arms"]["A"]
        fanin = {r["item"]["path"]: arms["A"].hub_prior_scorer.fan_in_degree(r["item"]["path"])
                 for r in saved["pool"]}
        try:
            row["parity"] = selective.production_parity(case, {"pool": saved["pool"], "fanin": fanin}, config, saved)
        except Exception as exc:
            row["error"] = repr(exc)
    row["complete"] = len(row["arms"]) == 2 and "error" not in row
    return row


def summary(manifest, state):
    complete = {p["id"]: p for p in state["pairs"] if p["complete"]}
    report = {"denominator": len(manifest["cases"]), "attempted": len(state["pairs"]), "complete": len(complete),
              "status": state["status"], "errors": state["errors"], "slices": {}, "latency": {},
              "elapsed_seconds": time.time() - state["started_at"] if state.get("started_at") else 0,
              "bootstrap": "10000 paired percentile draws seed42; independence not certified",
              "promotion": False}
    for name, label in (("full1065", "full"), ("where78", "where"), ("mech229", "mech")):
        group = [c for c in manifest["cases"] if label in c["labels"]]
        metrics = {}
        for metric in ("hit10", "mrr10", "recall10"):
            valid = [c for c in group if metric != "recall10" or base.exact(c["labels"][label])]
            values = [[base.score(complete[c["id"]]["arms"][a]["ranked"], c["labels"][label])[metric]
                       for a in "AS"] for c in valid if c["id"] in complete]
            metrics[metric] = quality(values, len(valid)) if valid else {"planned": 0}
        report["slices"][name] = {"denominator": len(group), "metrics": metrics}
    for a in "AS":
        values = [p["arms"][a] for p in complete.values()]
        report["latency"][a] = {k: base.distribution([v[k] for v in values])
                                  for k in ("e2e_seconds", "rerank_seconds", "retrieval_seconds")}
        report["latency"][a].update(
            retry_documents=sum(c["count"] for v in values for c in v["calls"][1:]),
            retry_chars=sum(c["chars"] for v in values for c in v["calls"][1:]),
            by_order={o: base.distribution([p["arms"][a]["e2e_seconds"] for p in complete.values()
                                           if p["order"] == o]) for o in ("AS", "SA")})
    if complete:
        times = np.array([[p["arms"][a]["e2e_seconds"] for a in "AS"] for p in complete.values()])
        rng = np.random.default_rng(42)
        deltas = [np.diff(np.percentile(times[rng.integers(0, len(times), len(times))], 95, axis=0))[0]
                  for _ in range(10000)]
        report["p95_delta_ci95"] = np.percentile(deltas, [2.5, 97.5]).tolist()
    report["decision"] = "ineligible: incomplete or failed campaign; no equivalence claim"
    if len(complete) == 1065 and state["status"] == "completed":
        report["observed_gate"] = (report["latency"]["S"]["e2e_seconds"]["p95"] < report["latency"]["A"]["e2e_seconds"]["p95"]
            and all(m["delta"] >= 0 for s in report["slices"].values() for m in s["metrics"].values()))
        report["decision"] = "observed gate only; uncertainty remains, equality is not equivalence; independent QA required"
    return report


PARENT_PAIRS = 782
EXTENSION_PARAMETERS = {"batch": 2048, "ubatch": 2048, "ctx": 40960}


def extension_budget(value):
    if type(value) not in (int, float) or not 0 < value <= 10800:
        raise ValueError("extension budget must be finite, positive and <=10800")
    return value


def extension_deadline(manifest, state):
    if state.get("budget_started_at") != manifest["frozen_at"]:
        raise ValueError("extension deadline anchor drift")
    return manifest["frozen_at"] + extension_budget(manifest["deadline_seconds"])


def validate_runtime_properties(props):
    for key, expected in EXTENSION_PARAMETERS.items():
        if type(props.get("n_" + key)) is not int or props["n_" + key] != expected:
            raise ValueError(f"runtime parameter missing or drift: n_{key}")


def runtime_command_properties(command):
    import shlex
    args = shlex.split(command)
    if not args or Path(args[0]).name != "llama-server":
        raise ValueError("runtime listener is not llama-server")
    flags = {"--ctx-size": "n_ctx", "-c": "n_ctx", "--batch-size": "n_batch",
             "-b": "n_batch", "--ubatch-size": "n_ubatch", "-ub": "n_ubatch", "--port": "port"}
    props = {}
    for i, arg in enumerate(args[1:], 1):
        flag, _, inline = arg.partition("=")
        if flag in flags:
            key = flags[flag]
            if key in props:
                raise ValueError("runtime duplicate parameter")
            try:
                props[key] = int(inline if "=" in arg else args[i + 1])
            except (ValueError, IndexError) as exc:
                raise ValueError("runtime invalid parameter") from exc
    if props.get("port") != 18081:
        raise ValueError("runtime port drift")
    validate_runtime_properties(props)
    return props


def runtime_properties(rerank_url):
    if rerank_url not in CE_OVERRIDE_URLS:
        raise ValueError("runtime endpoint drift")
    listeners = subprocess.check_output(
        ["lsof", "-nP", "-iTCP:18081", "-sTCP:LISTEN", "-t"], text=True, timeout=5).split()
    pids = set(listeners)
    if len(pids) != 1 or not all(p.isdigit() for p in pids):
        raise ValueError("runtime requires one identifiable local listener")
    pid = next(iter(pids))
    command = subprocess.check_output(["ps", "-ww", "-p", pid, "-o", "command="], text=True, timeout=5).strip()
    props = runtime_command_properties(command)
    return dict(props, pid=int(pid), command=command, observed_utc=utc_now(),
                caveat="listener argv verified; loaded weights/runtime continuity not proven")


def evidence_rows(root, state, cases):
    validate_state(state, base.digest(root / "manifest.json"), cases)
    rows, seen = [], set()
    for p in state["pairs"]:
        path = root / p["file"]
        if not path.resolve().is_relative_to(root.resolve()) or base.digest(path) != p["sha256"]:
            raise ValueError("pair evidence drift")
        row = json.loads(path.read_text())
        if row["id"] in seen or any(row[k] != p[k] for k in ("id", "order", "complete", "seconds")):
            raise ValueError("duplicate or inconsistent pair evidence")
        if row.get("error") or set(row["arms"]) != set("AS"):
            raise ValueError("invalid pair evidence")
        for arm in row["arms"].values():
            if not arm["complete"] or arm.get("error") or arm.get("failure_count") or arm.get("meta_error"):
                raise ValueError("invalid arm evidence")
        seen.add(row["id"])
        rows.append(row)
    return rows


def parent_evidence(root, expected=None):
    manifest = json.loads((root / "manifest.json").read_text())
    state = json.loads((root / "checkpoint.json").read_text())
    pins = {str(root / name): base.digest(root / name) for name in ("manifest.json", "checkpoint.json")}
    if state["status"] != "hard_cap" or state["errors"] or len(state["pairs"]) != PARENT_PAIRS:
        raise ValueError("parent must contain 782 error-free hard-cap pairs")
    if manifest["cases"] != frozen_cases():
        raise ValueError("parent schedule drift")
    rows = evidence_rows(root, state, manifest["cases"])
    pins.update({str(root / p["file"]): p["sha256"] for p in state["pairs"]})
    if expected is not None and pins != expected:
        raise ValueError("parent pins drift")
    return manifest, state, pins, rows


def extension_summary(manifest, state):
    verify_hashes({str(ATTEMPT / "manifest.json"): state["manifest_sha256"]})
    parent, parent_state, _, parent_rows = parent_evidence(OUT / manifest["parent_attempt"], manifest["parent_pins"])
    extension_deadline(manifest, state)
    rows = evidence_rows(ATTEMPT, state, manifest["cases"])
    if set(p["id"] for p in parent_rows) & set(p["id"] for p in rows):
        raise ValueError("overlapping parent/segment IDs")
    report = summary(parent, dict(state, pairs=parent_rows + rows))
    report["parent"] = summary(dict(parent, cases=parent["cases"][:PARENT_PAIRS]), dict(parent_state, pairs=parent_rows))
    report["parent"]["elapsed_seconds"] = None
    report["parent"]["recorded_pair_seconds"] = sum(p["seconds"] for p in parent_rows)
    report["segment"] = summary(manifest, dict(state, pairs=rows))
    report["runtime_continuity"] = "unknown; parent ctx8192 manifest versus reported ctx40960; descriptive only; not independent holdout"
    report["elapsed_seconds"] = time.time() - manifest["frozen_at"]
    report["decision"] = "descriptive combined paired metrics only; no promotion or equivalence"
    return report


def validate_extension_smoke(state):
    if len(state["smoke"]) != len(SMOKE_QUERIES):
        raise ValueError("extension requires complete smoke4")
    for i, p in enumerate(state["smoke"]):
        path = ATTEMPT / "smoke" / f"{i}.json"
        if p.get("sha256") != base.digest(path):
            raise ValueError("smoke evidence drift")
        row = json.loads(path.read_text())
        if (p["id"] != f"smoke-{i}" or not p["complete"] or not row["complete"] or
                row["id"] != p["id"] or row["order"] != ("AS" if i % 2 == 0 else "SA")):
            raise ValueError("invalid smoke evidence")


def campaign(max_pairs, rerank_url=None, parent_attempt=None, budget_seconds=10800):
    import signal
    import os
    import tempfile
    from replay_pool_recall import load_config, close_vector_store
    command_started = time.time()
    config = load_config(base.CONFIG)
    manifest = (freeze(config, rerank_url, parent_attempt, budget_seconds) if parent_attempt
                else freeze(config, rerank_url))
    extension = "parent_attempt" in manifest
    hard_seconds = manifest.get("deadline_seconds", HARD_SECONDS)
    config = runtime_config(config, rerank_url)
    forbidden_writes = []
    allowed_root = ATTEMPT.absolute()
    temp_root = allowed_root / "tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(temp_root)

    def audit(event, args):
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            flags = args[2]
            if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                path = Path(os.fsdecode(args[0])).absolute()
                if path != Path(os.devnull) and not path.is_relative_to(allowed_root):
                    forbidden_writes.append(str(path))
                    raise PermissionError(f"write outside exclusive scope: {path}")

    sys.addaudithook(audit)
    checkpoint = ATTEMPT / "checkpoint.json"
    if checkpoint.exists():
        state = json.loads(checkpoint.read_text())
        validate_state(state, base.digest(ATTEMPT / "manifest.json"), manifest["cases"])
        if state["status"] != "segment_boundary":
            raise ValueError("resume allowed only at intentional segment boundary")
        for p in state["pairs"]:
            if base.digest(ATTEMPT / p["file"]) != p["sha256"]:
                raise ValueError("pair evidence drift")
        if extension:
            evidence_rows(ATTEMPT, state, manifest["cases"])
            validate_extension_smoke(state)
    else:
        state = {"manifest_sha256": base.digest(ATTEMPT / "manifest.json"), "pairs": [], "smoke": [],
                 "errors": [], "segments": [], "status": "starting", "started_at": None}
        if extension:
            state["budget_started_at"] = manifest["frozen_at"]
    absolute_deadline = (extension_deadline(manifest, state) if extension else
                         state["started_at"] + hard_seconds if state["started_at"] else float("inf"))
    stores, all_rows = [], []
    segment_deadline = min(command_started + SEGMENT_SECONDS - PAIR_RESERVE if extension
                           else time.time() + SEGMENT_SECONDS, absolute_deadline)
    signal.signal(signal.SIGALRM, base.expired)
    signal.setitimer(signal.ITIMER_REAL, max(.001, segment_deadline - time.time()))
    try:
        if segment_deadline <= time.time():
            raise ValueError("campaign deadline expired")
        if extension:
            base.atomic(ATTEMPT / f"runtime-before-{len(state['segments']):02d}.json", runtime_properties(rerank_url))
        old = json.loads(PREFLIGHT.read_text())["current_services"]
        before = service_metadata(config)
        base.atomic(ATTEMPT / f"services-before-{len(state['segments']):02d}.json", before)
        check_services(old, before, rerank_url)
        tick = time.perf_counter()
        arms, stores = build_arms(config)
        state["segments"].append({"setup_seconds": time.perf_counter() - tick, "started_at": time.time()})
        if not state["smoke"]:
            for i, query in enumerate(SMOKE_QUERIES):
                c = {"id": f"smoke-{i}", "query": query, "order": "AS" if i % 2 == 0 else "SA"}
                row = pair(arms, c, config, parity=True)
                if forbidden_writes:
                    row.update(complete=False, error=f"forbidden cache writes: {forbidden_writes}")
                base.atomic(ATTEMPT / "smoke" / f"{i}.json", row)
                state["smoke"].append({"id": c["id"], "complete": row["complete"]})
                if extension:
                    state["smoke"][-1]["sha256"] = base.digest(ATTEMPT / "smoke" / f"{i}.json")
                base.atomic(checkpoint, state)
                if not row["complete"]:
                    raise ValueError("smoke failed")
            print("Balanced smoke4 and exact production replay parity passed", flush=True)
        else:
            tick = time.perf_counter()
            for arm in arms.values():
                warm = execute(arm, SMOKE_QUERIES[0])
                if not warm["complete"]:
                    raise ValueError("segment warmup failed")
            state["segments"][-1]["warmup_seconds"] = time.perf_counter() - tick
        if state["started_at"] is None and max_pairs:
            state["started_at"] = time.time()
        deadline = min(segment_deadline, absolute_deadline if extension else
                       state["started_at"] + hard_seconds if state["started_at"] else segment_deadline)
        signal.setitimer(signal.ITIMER_REAL, max(.001, deadline - time.time()))
        state["status"] = "running"
        base.atomic(checkpoint, state)
        start_n = len(state["pairs"])
        for case in manifest["cases"][start_n:]:
            if len(state["pairs"]) - start_n >= max_pairs or deadline - time.time() < PAIR_RESERVE:
                state["status"] = "hard_cap" if (absolute_deadline if extension else state["started_at"] + hard_seconds if state["started_at"] else float("inf")) - time.time() < PAIR_RESERVE else "segment_boundary"
                break
            row = pair(arms, case, config)
            if forbidden_writes:
                row.update(complete=False, error=f"forbidden cache writes: {forbidden_writes}")
            relative = f"pairs/{len(state['pairs']) + 1:04d}.json"
            base.atomic(ATTEMPT / relative, row)
            state["pairs"].append({k: row[k] for k in ("id", "order", "complete", "seconds")})
            state["pairs"][-1].update(file=relative, sha256=base.digest(ATTEMPT / relative))
            base.atomic(checkpoint, state)
            if not row["complete"]:
                raise ValueError(row["error"])
            n = len(state["pairs"])
            if n >= 32 and n % 32 == 0:
                elapsed = time.time() - state["started_at"]
                projected = elapsed + (len(manifest["cases"]) - n) * sum(p["seconds"] for p in state["pairs"]) / n
                state.setdefault("eta_checks", []).append({"n": n, "projected_seconds": projected})
                print("E2E checkpoint", n, "projected seconds", round(projected), flush=True)
                if not extension and projected > hard_seconds:
                    state["status"] = "eta_exceeds_hard_cap"
                    break
        if len(state["pairs"]) == len(manifest["cases"]):
            state["status"] = "completed"
        after = service_metadata(config)
        base.atomic(ATTEMPT / f"services-after-{len(state['segments']) - 1:02d}.json", after)
        check_services(old, after, rerank_url)
        verify_hashes(manifest["hashes"])
        verify_hashes(manifest["cache_hashes"])
        if extension:
            parent_evidence(OUT / parent_attempt, manifest["parent_pins"])
            validate_extension_smoke(state)
            verify_hashes({str(base.OUT / "checkpoint.json"): manifest["source_checkpoint_sha256"],
                           "tests/test_research_full_e2e1065_selective_second_pass.py": manifest["tests_sha256"],
                           str(selective.__file__): manifest["selective_runner_sha256"],
                           str(base.OUT / "manifest.json"): manifest["source_manifest_sha256"],
                           str(PREFLIGHT): manifest["preflight_sha256"]})
            base.atomic(ATTEMPT / f"runtime-after-{len(state['segments']) - 1:02d}.json", runtime_properties(rerank_url))
        if base.digest(__file__) != manifest["runner_sha256"]:
            raise ValueError("runner changed during measurement")
    except (Exception, base.DeadlineExpired) as exc:
        state["status"] = "blocked"
        state["errors"].append(repr(exc))
        state.setdefault("diagnostics", []).append(error_diagnostic(exc))
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        if extension:
            base.atomic(checkpoint, state)
            signal.setitimer(signal.ITIMER_REAL, max(.001, command_started + SEGMENT_SECONDS - time.time()))
        for store in stores:
            close_vector_store(store)
        base.atomic(checkpoint, state)
        all_rows = [json.loads((ATTEMPT / p["file"]).read_text()) for p in state["pairs"]]
        report = extension_summary(manifest, state) if extension else summary(manifest, dict(state, pairs=all_rows))
        base.atomic(ATTEMPT / "summary.json", report)
        print(json.dumps({k: report[k] for k in ("status", "attempted", "complete", "elapsed_seconds", "errors")}), flush=True)
        if extension:
            signal.setitimer(signal.ITIMER_REAL, 0)
    return 0 if state["status"] in ("completed", "segment_boundary") else 2


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "smoke", "run", "summary"), nargs="?", default="preflight")
    parser.add_argument("--parent-attempt", choices=("attempt-04",))
    parser.add_argument("--budget-seconds", type=int, default=10800)
    parser.add_argument("--attempt")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--rerank-url", choices=CE_OVERRIDE_URLS,
                        help="explicit same-model CE18081 override for both arms; repeat on every resume")
    parser.add_argument("--max-pairs", type=int, default=128)
    args = parser.parse_args()
    if args.max_pairs < 1:
        parser.error("positive max-pairs required")
    if args.action == "preflight":
        if args.parent_attempt:
            parser.error("extension uses retained preflight; initialize with smoke")
        if args.rerank_url:
            parser.error("endpoint override is only for fresh smoke/run; retained preflight is immutable")
        raise SystemExit(preflight())
    if not args.attempt:
        parser.error("explicit --attempt required")
    if args.parent_attempt:
        extension_budget(args.budget_seconds)
        if args.attempt != "extension-repair-01":
            parser.error("extension output must be extension-repair-01")
        ATTEMPT = OUT / args.attempt
        if args.action == "summary":
            manifest = json.loads((ATTEMPT / "manifest.json").read_text())
            state = json.loads((ATTEMPT / "checkpoint.json").read_text())
            print(json.dumps(extension_summary(manifest, state)))
            raise SystemExit(0)
        if args.rerank_url is None:
            parser.error("extension requires explicit CE18081 --rerank-url")
        if args.resume:
            if not (ATTEMPT / "checkpoint.json").is_file():
                parser.error("resume requires checkpoint")
        else:
            if args.action != "smoke":
                parser.error("initialize extension with smoke before run")
            if ATTEMPT.exists() and any(p.name != "validation.json" for p in ATTEMPT.iterdir()):
                parser.error("extension already initialized; use --resume, never reset")
            ATTEMPT.mkdir(parents=True, exist_ok=True)
    else:
        if args.action == "summary":
            parser.error("summary requires parent-linked extension")
        select_attempt(args.attempt, args.resume)
    raise SystemExit(campaign(0 if args.action == "smoke" else args.max_pairs, args.rerank_url,
                             args.parent_attempt, args.budget_seconds))