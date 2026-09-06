"""R1 frozen-score screening, bounded retry smoke, and authorized fixed-pool LIVE192."""
from __future__ import annotations

import argparse
import json
import math
import re
import signal
import socket
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import research_large_search_eval as base
from code_diver.reranking.cross_encoder_document_builder import build_cross_encoder_document

OUT = Path("artifacts/research/2026-09-05/selective-second-pass")
POLICIES = {"floor": 0.3, "cap": 24, "first_chars": 850, "second_chars": 2400,
            "seed": 42, "char_bin": 256, "mismatch_fraction": 0.05,
            "bootstrap_resamples": 10000, "stop": sorted(base.STOP),
            "tokens": "ASCII alphanumeric; split lowercase-to-uppercase; full-content spans",
            "arms": ["A", "N", "S", "C"]}


@contextmanager
def no_network():
    original = socket.socket.connect, socket.socket.connect_ex, socket.create_connection

    def denied(*args, **kwargs):
        raise RuntimeError("offline screening forbids network access")

    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = denied
    try:
        yield
    finally:
        socket.socket.connect, socket.socket.connect_ex, socket.create_connection = original


def token_spans(text):
    for word in re.finditer(r"[A-Za-z0-9]+", text):
        cuts = [0] + [m.start() + 1 for m in re.finditer(r"[a-z][A-Z]", word.group())] + [len(word.group())]
        for start, end in zip(cuts, cuts[1:]):
            yield word.group()[start:end].lower(), word.start() + start, word.start() + end


def evidence(content, query):
    if len(content) <= POLICIES["first_chars"]:
        return []
    spans = list(token_spans(content))
    first = {term for term, start, end in spans if start < 850}
    wanted = base.terms(query) - first
    return [{"term": term, "start": start, "end": end} for term, start, end in spans
            if term in wanted and start >= 850 and end <= 2400]


def eligible(scores):
    retry = [s.index for s in scores if s.score < POLICIES["floor"]]
    return sorted(retry)[:POLICIES["cap"]] if len(retry) > POLICIES["cap"] else retry


def control(case_id, indices, selected, documents):
    bins = {i: len(doc) // POLICIES["char_bin"] for i, doc in zip(indices, documents)}
    quotas = Counter(bins[i] for i in selected)
    chosen = set()
    for bucket, count in sorted(quotas.items()):
        candidates = [i for i in indices if bins[i] == bucket]
        candidates.sort(key=lambda i: base.sha([POLICIES["seed"], case_id, i]))
        chosen.update(candidates[:count])
    return [i for i in indices if i in chosen]


def merge(scores, indices, saved, selected):
    if not selected:
        return scores
    values = {indices[s["index"]]: s["score"] for s in saved}
    if not set(selected) <= values.keys():
        raise ValueError("missing expanded scores")
    result = [base.RerankScore(index=s.index, score=max(s.score, values[s.index]))
              if s.index in selected else s for s in scores]
    return sorted(result, key=lambda s: s.score, reverse=True)


def validate_calls(calls):
    if len(calls) not in (1, 2):
        raise ValueError("unexpected recorded call count")
    for call in calls:
        scores = call["scores"]
        n = len(call["documents"])
        if (call["count"] != n or call["top_n"] != n or call["chars"] != sum(map(len, call["documents"]))
                or len(scores) != n or {s["index"] for s in scores} != set(range(n))
                or any(not math.isfinite(s["score"]) for s in scores)):
            raise ValueError("invalid recorded score/request coverage")


class OfflineArm(base.ResearchArm):
    def _with_second_pass(self, query, candidates, scores):
        if self.policy == "A":
            return super()._with_second_pass(query, candidates, scores)
        indices = eligible(scores)
        documents = [build_cross_encoder_document(candidates[i], replace(self.config, max_document_chars=2400),
                                                 self.repository_root) for i in indices]
        calls = self.saved["calls"]
        if indices and (len(calls) != 2 or documents != calls[1]["documents"]):
            raise ValueError("expanded document parity failed")
        selected = self.selection
        result = merge(scores, indices, calls[1]["scores"] if indices else [], selected)
        self.merged = [asdict(s) for s in result]
        return result


def replay(case, pair, config, policy, selected):
    saved = pair["arms"]["A"]
    provider = base.RecordedProvider(SimpleNamespace(name=config.cross_encoder_rerank.provider,
                                                     model=config.cross_encoder_rerank.model), replay=saved["calls"])
    pool = [base.SearchResult(base.CodeItem(**r["item"]), r["score"]) for r in pair["pool"]]
    arm = OfflineArm(pool, provider, config.cross_encoder_rerank, config.root, config.hub_prior,
                     pair["fanin"], case["query"])
    arm.policy, arm.selection, arm.saved = policy, selected, saved
    result = base.execute_arm(arm, case["query"])
    expected_calls = len(saved["calls"]) if policy == "A" else 1
    if not result["complete"] or len(provider.calls) != expected_calls:
        raise ValueError(f"replay fallback/failure {case['id']} {policy}: {result.get('error')}")
    kept = {k: result[k] for k in ("outputs", "ranked", "features", "meta_predictions")}
    if policy == "A":
        for key in kept:
            if base.encoded(kept[key]) != base.encoded(saved[key]):
                raise ValueError(f"exact baseline parity failed: {case['id']} {key}")
    else:
        kept["merged_scores"] = arm.merged
    return kept


def decisions(case, pair):
    calls = pair["arms"]["A"]["calls"]
    indices = eligible([base.RerankScore(**s) for s in calls[0]["scores"]])
    if bool(indices) != (len(calls) == 2):
        raise ValueError("retry eligibility mismatch")
    documents = calls[1]["documents"] if indices else []
    reasons = {i: evidence(pair["pool"][i]["item"]["content"], case["query"]) for i in indices}
    selected = [i for i in indices if reasons[i]]
    random = control(case["id"], indices, selected, documents)
    lengths = dict(zip(indices, map(len, documents)))
    sc, cc = sum(lengths[i] for i in selected), sum(lengths[i] for i in random)
    return {"indices": {"A": indices, "N": [], "S": selected, "C": random}, "evidence": reasons,
            "expanded_document_hashes": {i: base.sha(doc) for i, doc in zip(indices, documents)},
            "retry_chars": {"A": sum(lengths.values()), "N": 0, "S": sc, "C": cc},
            "char_gap": cc - sc, "unmatched": abs(cc - sc) > 0.05 * sc,
            "overlap": len(set(selected) & set(random)), "identical_control": selected == random,
            "conditional_subset": {a: bool(v) and v != indices for a, v in (("S", selected), ("C", random))}}


def slices(cases, pairs):
    result = {"all192": (cases, "full"),
              "where78": ([c for c in cases if "where" in c["labels"]], "where"),
              "novel95": ([c for c in cases if c["novel"]], "full"),
              "guards40": ([c for c in cases if "mech" in c["labels"] and "where" not in c["labels"]], "mech"),
              "mechanical118": ([c for c in cases if "mech" in c["labels"]], "mech")}
    seen = set()
    dedup = []
    for case in cases:
        query = " ".join(case["query"].lower().split())
        if query not in seen:
            dedup.append(case)
            seen.add(query)
    result["dedup191"] = dedup, "full"
    result["no_glob190"] = [c for c in cases if len(base.exact(c["labels"]["full"])) == len(set(c["labels"]["full"]))], "full"
    for name, low, high in (("retry0", 0, 0), ("retry1_8", 1, 8), ("retry9_16", 9, 16), ("retry17_24", 17, 24)):
        result[name] = [c for c in cases if low <= len(pairs[c["id"]]["decision"]["indices"]["A"]) <= high], "full"
    return result


def summarize(cases, pairs, source):
    report = {"slices": {}, "budgets": {}, "gates": {}, "latency": "Not measured or simulated; no speed/E2E claim",
              "bootstrap": {"seed": 42, "resamples": 10000, "method": "paired percentile", "independent": False}}
    for name, (group, label) in slices(cases, pairs).items():
        results = {}
        for arm in "NSC":
            rows = [(c, [base.score(pairs[c["id"]]["arms"][a]["ranked"], c["labels"][label]) for a in ("A", arm)]) for c in group]
            metrics = {m: base.paired_summary([(r[0][m], r[1][m]) for _, r in rows if r[0][m] is not None],
                                             sum(r[0][m] is not None for _, r in rows)) for m in ("hit10", "mrr10", "recall10")}
            metrics["hit_ids"] = {k: [c["id"] for c, r in rows if (r[1]["hit10"] - r[0]["hit10"]) * sign > 0]
                                  for k, sign in (("wins", 1), ("losses", -1))}
            gold = np.array([r[0]["gold"] for _, r in rows])
            found = np.array([[r[0]["found"], r[1]["found"]] for _, r in rows])
            if len(rows) and gold.sum():
                indices = np.random.default_rng(42).integers(0, len(rows), (10000, len(rows)))
                den = gold[indices].sum(axis=1)
                delta = (found[:, 1] - found[:, 0])[indices].sum(axis=1) / np.maximum(den, 1)
                metrics["micro_recall10"] = {"A": float(found[:, 0].sum() / gold.sum()), "B": float(found[:, 1].sum() / gold.sum()),
                                             "delta": float((found[:, 1] - found[:, 0]).sum() / gold.sum()), "ci95": np.percentile(delta, [2.5, 97.5]).tolist()}
            metrics["pool_gold_present"] = sum(bool(base.exact(c["labels"][label]) & {r["item"]["path"] for r in source[c["id"]]["pool"]}) for c in group)
            results[arm] = metrics
        budgets = {arm: {"retry_documents": sum(len(pairs[c["id"]]["decision"]["indices"][arm]) for c in group),
                         "retry_chars": sum(pairs[c["id"]]["decision"]["retry_chars"][arm] for c in group),
                         "retry_requests": sum(bool(pairs[c["id"]]["decision"]["indices"][arm]) for c in group)} for arm in "ANSC"}
        report["slices"][name] = {"n": len(group), "arms": results, "budgets": budgets}
    for arm in "ANSC":
        ds = [p["decision"] for p in pairs.values()]
        report["budgets"][arm] = {"first_documents": sum(p["arms"]["A"]["calls"][0]["count"] for p in source.values()), "first_chars": sum(p["arms"]["A"]["calls"][0]["chars"] for p in source.values()),
                                   "retry_documents": sum(len(d["indices"][arm]) for d in ds),
                                   "retry_requests": sum(bool(d["indices"][arm]) for d in ds),
                                   "retry_chars": sum(d["retry_chars"][arm] for d in ds)}
    report["control"] = {"unmatched_ids": [i for i, p in pairs.items() if p["decision"]["unmatched"]],
                         "contrasting_cases": sum(not p["decision"]["identical_control"] for p in pairs.values()),
                         "overlap_documents": sum(p["decision"]["overlap"] for p in pairs.values())}
    report["selective_minus_control"] = {metric: base.paired_summary([
        (base.score(pairs[c["id"]]["arms"]["C"]["ranked"], c["labels"]["full"])[metric],
         base.score(pairs[c["id"]]["arms"]["S"]["ranked"], c["labels"]["full"])[metric]) for c in cases], len(cases))
        for metric in ("hit10", "mrr10", "recall10")}
    report["cluster_sensitivity"] = cluster_sensitivity(cases, pairs)
    for arm in "NSC":
        main = report["slices"]["all192"]["arms"][arm]
        guard = report["slices"]["guards40"]["arms"][arm]
        report["gates"][arm] = {"net_hit": main["hit10"]["wins"] - main["hit10"]["losses"] >= -1,
                                "mrr_ci": main["mrr10"]["ci95"][0] >= -0.01,
                                "guard_hit": guard["hit10"]["wins"] >= guard["hit10"]["losses"],
                                "guard_mrr": guard["mrr10"]["delta"] >= -0.01}
    return report


def cluster_sensitivity(cases, pairs):
    parent = list(range(len(cases)))

    def root(i):
        while parent[i] != i:
            i = parent[i]
        return i

    for i, case in enumerate(cases):
        for j in range(i):
            same_query = " ".join(case["query"].lower().split()) == " ".join(cases[j]["query"].lower().split())
            shared_gold = base.exact(case["labels"]["full"]) & base.exact(cases[j]["labels"]["full"])
            if same_query or shared_gold:
                parent[root(i)] = root(j)
    groups = {}
    for i in range(len(cases)):
        groups.setdefault(root(i), []).append(i)
    clusters = list(groups.values())
    draws = np.random.default_rng(42).integers(0, len(clusters), (10000, len(clusters)))
    counts = np.array([len(g) for g in clusters])[draws].sum(axis=1)
    result = {"unit": "connected normalized-query/shared exact full-label answer components; descriptive sensitivity only",
              "n_components": len(clusters), "members": [[cases[i]["id"] for i in g] for g in clusters], "arms": {}}
    for arm in "NSC":
        metrics = {}
        for metric in ("hit10", "mrr10", "recall10"):
            delta = np.array([base.score(pairs[c["id"]]["arms"][arm]["ranked"], c["labels"]["full"])[metric]
                              - base.score(pairs[c["id"]]["arms"]["A"]["ranked"], c["labels"]["full"])[metric] for c in cases])
            sums = np.array([delta[g].sum() for g in clusters])
            metrics[metric] = {"delta": float(delta.mean()), "ci95": np.percentile(sums[draws].sum(axis=1) / counts, [2.5, 97.5]).tolist()}
        result["arms"][arm] = metrics
    return result


def run():
    started = time.monotonic()
    signal.signal(signal.SIGALRM, base.expired)
    signal.alarm(590)
    if (OUT / "manifest.json").exists():
        raise ValueError("refusing to overwrite frozen screening")
    from replay_pool_recall import load_config
    manifest = json.loads((base.OUT / "manifest.json").read_text())
    state = json.loads((base.OUT / "checkpoint.json").read_text())
    if state["manifest_sha256"] != base.digest(base.OUT / "manifest.json"):
        raise ValueError("source manifest hash mismatch")
    checked = {}
    for name, expected in manifest["hashes"].items():
        if name.startswith("src/") or name in (str(base.CONFIG), str(Path(base.__file__).relative_to(Path.cwd())), "artifacts/ce_meta_ranker/ranker.json", "artifacts/ce_meta_ranker/ce_meta_ranker.lgb.txt"):
            checked[name] = base.digest(name)
            if checked[name] != expected:
                raise ValueError(f"source/model drift: {name}")
    config = load_config(base.CONFIG)
    base.validate_config(config)
    if json.loads(base.encoded(asdict(config))) != manifest["resolved_config"]:
        raise ValueError("resolved configuration drift")
    cases = manifest["cases"]
    source = {p["id"]: p for p in state["pairs"]}
    if len(source) != 192 or len(cases) != 192 or {c["id"] for c in cases} != source.keys():
        raise ValueError("192 complete unique pairs required")
    for pair in source.values():
        if not pair["complete"] or not pair["arms"]["A"]["complete"] or base.sha(pair["pool"]) != pair["pool_sha256"]:
            raise ValueError("incomplete/corrupt baseline")
        validate_calls(pair["arms"]["A"]["calls"])
    base.atomic(OUT / "manifest.json", {"policies": POLICIES, "source_manifest_sha256": base.digest(base.OUT / "manifest.json"),
                                        "source_checkpoint_sha256": base.digest(base.OUT / "checkpoint.json"), "verified_hashes": checked,
                                        "runner_sha256": base.digest(__file__), "tests_sha256": base.digest("tests/test_research_selective_second_pass.py"),
                                        "gates": "net paired hits >= -1/192; lower percentile95CI MRR >= -.01; guards40 net hits >=0, MRR >=-.01 exploratory",
                                        "latency_endpoint_future": "rerank walltime, same shared retrieval; no E2E claim"})
    results = {}
    with no_network():
        for case in cases:
            pair = source[case["id"]]
            results[case["id"]] = {"id": case["id"], "decision": decisions(case, pair),
                                    "arms": {"A": replay(case, pair, config, "A", [])}}
        base.atomic(OUT / "parity.json", {"passed": True, "n": len(results), "exact": ["requests", "outputs", "features", "meta_predictions"],
                                        "excluded": "wall-clock trace fields"})
        print("Exact baseline parity PASS 192/192", flush=True)
        for case in cases:
            row = results[case["id"]]
            for arm in "NSC":
                row["arms"][arm] = replay(case, source[case["id"]], config, arm, row["decision"]["indices"][arm])
            base.atomic(OUT / "pairs" / f"{case['id']}.json", row)
            base.atomic(OUT / "checkpoint.json", {"complete_ids": [i for i, r in results.items() if len(r["arms"]) == 4],
                                                 "manifest_sha256": base.digest(OUT / "manifest.json")})
    report = summarize(cases, results, source)
    report["offline_runtime_seconds"] = time.monotonic() - started
    base.atomic(OUT / "summary.json", report)
    hashes = {str(p.relative_to(OUT)): base.digest(p) for p in sorted(OUT.rglob("*.json"))}
    base.atomic(OUT / "hashes.json", hashes)
    signal.alarm(0)
    print(json.dumps({"gates": report["gates"], "budgets": report["budgets"], "seconds": report["offline_runtime_seconds"]}), flush=True)


def smoke_schedule(cases, source):
    orders = ("ASC", "SCA", "CAS", "ACS", "CSA", "SAC")
    selected = []
    for case in cases:
        decision = decisions({k: case[k] for k in ("id", "query")}, source[case["id"]])
        if decision["conditional_subset"]["S"]:
            selected.append({"id": case["id"], "order": orders[len(selected) % 6], "decision": decision})
        if len(selected) == 12:
            break
    if len(selected) != 12:
        raise ValueError("12 eligible smoke cases required")
    return selected


def fresh_replay(case, pair, config, indices, scores):
    import copy
    changed = copy.deepcopy(pair)
    baseline_indices = decisions(case, pair)["indices"]["A"]
    mapped = {indices[s["index"]]: s["score"] for s in scores}
    changed["arms"]["A"]["calls"][1]["scores"] = [
        {"index": j, "score": mapped.get(i, s["score"])}
        for j, i in enumerate(baseline_indices)
        for s in pair["arms"]["A"]["calls"][1]["scores"] if s["index"] == j]
    with no_network():
        return replay(case, changed, config, "S", indices)


def smoke_json(url, timeout, payload=None):
    import urllib.request
    from urllib.parse import urlparse
    if urlparse(url).hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("localhost only")
    request = urllib.request.Request(url, data=None if payload is None else json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": "Bearer local"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        return response.read().decode()


def validate_model_metadata(recorded, fresh):
    import copy
    normalized = copy.deepcopy(fresh)
    changes = []
    if not isinstance(recorded.get("data"), list) or not isinstance(fresh.get("data"), list) or len(recorded["data"]) != len(fresh["data"]):
        raise ValueError("served model metadata drift")
    for i, (old, new) in enumerate(zip(recorded["data"], normalized["data"])):
        if "created" in old and "created" in new:
            if type(old["created"]) is not int or type(new["created"]) is not int:
                raise ValueError("served model metadata drift")
            if old["created"] != new["created"]:
                changes.append({"field": f"data[{i}].created", "recorded": old["created"], "fresh": new["created"]})
            new["created"] = old["created"]
    if base.encoded(normalized) != base.encoded(recorded):
        raise ValueError("served model metadata drift")
    return changes


def validate_live_preflight(preflight):
    if any(v["actual"] != v["expected"] for v in preflight["hashes"].values()) or not all(preflight[k] for k in preflight if k != "hashes"):
        raise ValueError("source/model/config drift")


def live_smoke(attempt="live-smoke"):
    from replay_pool_recall import load_config
    from code_diver.reranking.llama_cpp_rerank_provider import LlamaCppRerankProvider
    from urllib.parse import urlsplit
    started = time.monotonic()
    deadline = started + 590
    signal.signal(signal.SIGALRM, base.expired)
    signal.alarm(590)
    if Path(attempt).name != attempt or attempt in (".", ".."):
        raise ValueError("attempt must be a directory name")
    out = OUT / attempt
    if out.exists():
        raise ValueError("refusing to overwrite live smoke")
    report = {"status": "blocked", "denominator": 12, "rows": [], "errors": [],
              "latency_endpoint": "CE retry HTTP walltime only; no whole rerank/E2E speed claim"}
    try:
        manifest = json.loads((base.OUT / "manifest.json").read_text())
        state = json.loads((base.OUT / "checkpoint.json").read_text())
        verified = json.loads((OUT / "verified/manifest.json").read_text())
        checks = {n: {"expected": h, "actual": base.digest(n)} for n, h in manifest["hashes"].items()}
        config = load_config(base.CONFIG)
        preflight = {"hashes": checks, "resolved_config_equal": json.loads(base.encoded(asdict(config))) == manifest["resolved_config"],
                     "source_manifest_equal": state["manifest_sha256"] == base.digest(base.OUT / "manifest.json"),
                     "source_checkpoint_equal": verified["source_checkpoint_sha256"] == base.digest(base.OUT / "checkpoint.json")}
        base.atomic(out / "preflight.json", preflight)
        validate_live_preflight(preflight)
        base.validate_config(config)
        source = {p["id"]: p for p in state["pairs"]}
        cases = {c["id"]: c for c in manifest["cases"]}
        schedule = smoke_schedule(manifest["cases"], source)
        previous = OUT / "live-smoke/manifest.json"
        if attempt != "live-smoke" and base.encoded(json.loads(base.encoded(schedule))) != base.encoded(json.loads(previous.read_text())["schedule"]):
            raise ValueError("frozen smoke schedule drift")
        base.atomic(out / "manifest.json", {"schedule": schedule, "policies": POLICIES, "deadline_seconds": 600,
                    "previous_attempt_manifest_sha256": base.digest(previous) if attempt != "live-smoke" else None,
                    "request_timeout_seconds": 30, "runner_sha256": base.digest(__file__),
                    "tests_sha256": base.digest("tests/test_research_selective_second_pass.py"),
                    "source_manifest_sha256": base.digest(base.OUT / "manifest.json"),
                    "source_checkpoint_sha256": base.digest(base.OUT / "checkpoint.json")})
        for entry in schedule:
            replay(cases[entry["id"]], source[entry["id"]], config, "A", [])
        base.atomic(out / "parity.json", {"passed": True, "n": 12})
        ce = config.cross_encoder_rerank
        parsed = urlsplit(ce.url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        metadata = {path: json.loads(smoke_json(origin + path, 5)) for path in ("/health", "/v1/models")}
        base.atomic(out / "service.json", metadata)
        recorded_service = state["services_before"]
        base.atomic(out / "recorded-service.json", recorded_service)
        changes = validate_model_metadata(recorded_service[origin + "/v1/models"], metadata["/v1/models"])
        base.atomic(out / "metadata-comparison.json", {"runtime_instance_drift": changes,
                    "other_fields_strictly_equal": True, "model_equivalence_proven": False,
                    "limitation": "Local GGUF hashes do not prove loaded model mapping; timestamp-only runtime drift explicitly authorized."})
        parser = LlamaCppRerankProvider(ce.model, ce.url)
        for entry in schedule:
            case, pair = cases[entry["id"]], source[entry["id"]]
            decision = entry["decision"]
            docs = dict(zip(decision["indices"]["A"], pair["arms"]["A"]["calls"][1]["documents"]))
            row = {"id": case["id"], "arms": {}, "decision": decision}
            report["rows"].append(row)
            for arm in entry["order"]:
                indices = decision["indices"][arm]
                documents = [docs[i] for i in indices]
                call = {"documents": documents, "count": len(documents), "chars": sum(map(len, documents)), "top_n": len(documents)}
                row["arms"][arm] = {"call": call}
                base.atomic(out / "checkpoint.json", report)
                tick = time.monotonic()
                try:
                    remaining = deadline - tick
                    if remaining <= 1:
                        raise TimeoutError("total deadline exhausted")
                    call["raw"] = smoke_json(ce.url, min(30, remaining), {"model": ce.model, "query": case["query"], "documents": documents, "top_n": len(documents)})
                    call["seconds"] = time.monotonic() - tick
                    call["scores"] = [asdict(s) for s in parser._parse_scores(json.loads(call["raw"]))]
                    validate_calls([call])
                    row["arms"][arm]["result"] = fresh_replay(case, pair, config, indices, call["scores"])
                except Exception as exc:
                    call.setdefault("seconds", time.monotonic() - tick)
                    call["error"] = repr(exc)
                finally:
                    base.atomic(out / "checkpoint.json", report)
            base.atomic(out / "pairs" / f"{case['id']}.json", row)
        report["status"] = "completed"
        report["comparisons"] = {}
        for variant in ("recorded", "S", "C"):
            pairs = []
            drift = []
            for row in report["rows"]:
                if "result" not in row["arms"].get("A", {}):
                    continue
                case = cases[row["id"]]
                a = row["arms"]["A"]
                b = {"result": source[row["id"]]["arms"]["A"], "call": source[row["id"]]["arms"]["A"]["calls"][1]} if variant == "recorded" else row["arms"][variant]
                if "result" not in b:
                    continue
                pairs.append((base.score(a["result"]["ranked"], case["labels"]["full"]), base.score(b["result"]["ranked"], case["labels"]["full"])))
                ai = row["decision"]["indices"]["A"]
                bi = ai if variant == "recorded" else row["decision"]["indices"][variant]
                av = {ai[s["index"]]: s["score"] for s in a["call"]["scores"]}
                drift.extend(s["score"] - av[bi[s["index"]]] for s in b["call"]["scores"])
            report["comparisons"][variant] = {"completed_pairs": len(pairs), "denominator": 12,
                "quality_variant_minus_live_A": {m: base.paired_summary([(a[m], b[m]) for a, b in pairs], len(pairs)) for m in ("hit10", "mrr10", "recall10")} if pairs else {},
                "common_doc_drift": {"n": len(drift), "mean_abs": float(np.mean(np.abs(drift))), "max_abs": max(map(abs, drift)), "nonzero": sum(d != 0 for d in drift)} if drift else {}}
        report["latency"] = {}
        for arm in "ASC":
            calls = [r["arms"][arm]["call"] for r in report["rows"] if arm in r["arms"]]
            times = [c["seconds"] for c in calls if "error" not in c]
            report["latency"][arm] = {"denominator": 12, "successes": len(times), "errors": sum("error" in c for c in calls),
                "count": sum(c["count"] for c in calls), "chars": sum(c["chars"] for c in calls),
                "p50_p95_seconds": np.percentile(times, [50, 95]).tolist() if times else []}
    except (Exception, base.DeadlineExpired) as exc:
        report["errors"].append(repr(exc))
    finally:
        signal.alarm(0)
        report["runtime_seconds"] = time.monotonic() - started
        report["complete_cases"] = sum(all("result" in row["arms"].get(a, {}) for a in "ASC") for row in report["rows"])
        base.atomic(out / "summary.json", report)
        base.atomic(out / "hashes.json", {str(p.relative_to(out)): base.digest(p) for p in sorted(out.rglob("*.json"))})
        print(json.dumps({k: v for k, v in report.items() if k != "rows"}), flush=True)


class WholeRerankArm(base.ResearchArm):
    def search(self, query, limit):
        started = time.perf_counter()
        try:
            return super().search(query, limit)
        finally:
            self.rerank_seconds = time.perf_counter() - started

    def _with_second_pass(self, query, candidates, scores):
        if self.policy == "A":
            return super()._with_second_pass(query, candidates, scores)
        indices = eligible(scores)
        selected = [i for i in indices if evidence(candidates[i].item.content, query)]
        self.selection = {"eligible": indices, "selected": selected}
        if not selected:
            return scores
        documents = [build_cross_encoder_document(candidates[i], replace(self.config, max_document_chars=2400),
                                                 self.repository_root) for i in selected]
        second = self.rerank_provider.rerank(query, documents, len(documents))
        return merge(scores, selected, [asdict(s) for s in second], selected)


class FreshProvider:
    def __init__(self, config, deadline):
        from code_diver.reranking.llama_cpp_rerank_provider import LlamaCppRerankProvider
        self.name, self.model, self.url = config.provider, config.model, config.url
        self.parser = LlamaCppRerankProvider(config.model, config.url)
        self.deadline, self.raw = deadline, []

    def rerank(self, query, documents, top_n):
        remaining = self.deadline - time.monotonic()
        if remaining <= 1:
            raise TimeoutError("campaign deadline exhausted")
        timeout = min(60 if not self.raw else 30, remaining)
        response = smoke_json(self.url, timeout, {"model": self.model, "query": query,
                                                "documents": documents, "top_n": top_n})
        self.raw.append({"response": response, "timeout_seconds": timeout})
        return self.parser._parse_scores(json.loads(response))


def whole_arm(case, pair, config, policy, provider):
    if policy not in ("A", "S"):
        raise ValueError("whole rerank supports only frozen A/S policies")
    started = time.perf_counter()
    pool = [base.SearchResult(base.CodeItem(**r["item"]), r["score"]) for r in pair["pool"]]
    arm = WholeRerankArm(pool, provider, config.cross_encoder_rerank, config.root, config.hub_prior,
                        pair["fanin"], case["query"])
    arm.policy = policy
    arm.selection = None
    return arm, time.perf_counter() - started


def whole_execute(case, pair, config, policy, provider):
    arm, setup = whole_arm(case, pair, config, policy, provider)
    try:
        result = base.execute_arm(arm, case["query"])
    except base.DeadlineExpired:
        result = arm.interrupted_result
    result.update(setup_seconds=setup, rerank_seconds=arm.rerank_seconds, selection=arm.selection)
    return result


def production_parity(case, pair, config, saved):
    provider = base.RecordedProvider(SimpleNamespace(name=config.cross_encoder_rerank.provider,
                                                     model=config.cross_encoder_rerank.model), replay=saved["calls"])
    pool = [base.SearchResult(base.CodeItem(**r["item"]), r["score"]) for r in pair["pool"]]
    production = base.CrossEncoderRerankRetrievalStrategy(base.FrozenPool(pool), provider,
        config.cross_encoder_rerank, base.Trace(), config.root,
        base.HubPriorScorer(config.hub_prior, pair["fanin"].get))
    production._ce_meta_ranker_load()
    if production._ce_meta_ranker is None:
        raise ValueError("production meta model unavailable")
    production._ce_meta_ranker = base.PredictionRecorder(production._ce_meta_ranker)
    production.ce_meta_feature_extractor = base.FeatureRecorder(production.ce_meta_feature_extractor)
    production.sources = []
    with no_network():
        actual = base.execute_arm(production, case["query"])
    if not actual["complete"] or len(provider.calls) != len(saved["calls"]):
        raise ValueError("production replay fallback or request mismatch")
    for key in ("outputs", "ranked", "features", "meta_predictions"):
        if base.encoded(actual[key]) != base.encoded(saved[key]):
            raise ValueError(f"production exact parity failed: {case['id']} {key}")
    return {"passed": True, "id": case["id"], "calls": len(provider.calls)}


def large_summary(cases, rows):
    complete = {r["id"]: r for r in rows if r["complete"]}
    report = {"denominator": 192, "complete_pairs": len(complete), "attempted_pairs": len(rows),
              "failed_pairs": len(rows) - len(complete), "not_started": 192 - len(rows), "slices": {}, "latency": {},
              "bootstrap": {"seed": 42, "resamples": 10000, "method": "paired percentile", "independent": False}}
    proxy = {c["id"]: {"decision": {"indices": {"A": list(range(len(complete[c["id"]]["arms"]["A"]["calls"][1]["documents"])))
                  if c["id"] in complete and len(complete[c["id"]]["arms"]["A"]["calls"]) == 2 else []}}} for c in cases}
    for name, (group, label) in slices(cases, proxy).items():
        observed = [c for c in group if c["id"] in complete]
        metrics = {}
        for metric in ("hit10", "mrr10", "recall10"):
            values = [(c["id"], [base.score(complete[c["id"]]["arms"][a]["ranked"], c["labels"][label])[metric]
                                  for a in "AS"]) for c in observed]
            valid = [(i, a, b) for i, (a, b) in values if a is not None and b is not None]
            metrics[metric] = base.paired_summary([(a, b) for _, a, b in valid], len(group)) if valid else {}
            metrics[metric].update(winning_ids=[i for i, a, b in valid if b > a], losing_ids=[i for i, a, b in valid if b < a])
        report["slices"][name] = {"denominator": len(group), "complete": len(observed), "metrics": metrics}
    for arm in "AS":
        values = [r["arms"][arm] for r in complete.values()]
        report["latency"][arm] = {"endpoint": "whole production search on fixed pool; excludes setup and result serialization",
            "p50_p95_seconds": np.percentile([v["rerank_seconds"] for v in values], [50, 95]).tolist() if values else [],
            "setup_p50_p95_seconds": np.percentile([v["setup_seconds"] for v in values], [50, 95]).tolist() if values else [],
            "first_documents": sum(v["calls"][0]["count"] for v in values),
            "first_chars": sum(v["calls"][0]["chars"] for v in values),
            "retry_documents": sum(v["calls"][1]["count"] for v in values if len(v["calls"]) == 2),
            "retry_chars": sum(v["calls"][1]["chars"] for v in values if len(v["calls"]) == 2),
            "retry_requests": sum(len(v["calls"]) == 2 for v in values),
            "by_order": {order: base.distribution([r["arms"][arm]["rerank_seconds"] for r in complete.values() if r["order"] == order])
                         for order in ("AS", "SA")}}
    report["latency"]["paired_seconds"] = base.paired_summary([
        (r["arms"]["A"]["rerank_seconds"], r["arms"]["S"]["rerank_seconds"]) for r in complete.values()], 192)
    report["order_counts"] = dict(Counter(r["order"] for r in rows))
    if len(complete) == 192:
        main, guard = (report["slices"][k]["metrics"] for k in ("all192", "guards40"))
        speedup = 1 - report["latency"]["S"]["p50_p95_seconds"][1] / report["latency"]["A"]["p50_p95_seconds"][1]
        report.update(p95_speedup=speedup, gates={"net_hit": main["hit10"]["wins"] - main["hit10"]["losses"] >= -1,
            "mrr_ci": main["mrr10"]["ci95"][0] >= -.01, "guard_hit": guard["hit10"]["wins"] >= guard["hit10"]["losses"],
            "guard_mrr": guard["mrr10"]["delta"] >= -.01, "p95_speedup": speedup >= .15})
    else:
        report["gates"] = "ineligible: incomplete 192 denominator; no missing-case imputation"
    return report


def recorded_drift(cases, rows, source):
    by_id = {c["id"]: c for c in cases}
    deltas = []
    quality = []
    retry_eligibility_changed = []
    for row in rows:
        fresh = row["arms"].get("A")
        if not fresh or not fresh["complete"]:
            continue
        case = by_id[row["id"]]
        old = source[row["id"]]["arms"]["A"]
        old_first = {s["index"]: s["score"] for s in old["calls"][0]["scores"]}
        deltas.extend(s["score"] - old_first[s["index"]] for s in fresh["calls"][0]["scores"])
        if eligible([base.RerankScore(**s) for s in fresh["calls"][0]["scores"]]) != eligible([base.RerankScore(**s) for s in old["calls"][0]["scores"]]):
            retry_eligibility_changed.append(row["id"])
        quality.append([base.score(a["ranked"], case["labels"]["full"]) for a in (old, fresh)])
    return {"direction": "fresh A minus recorded A", "denominator": 192, "completed": len(quality),
        "first_score_drift": {"n": len(deltas), "nonzero": sum(d != 0 for d in deltas),
            "mean_abs": float(np.mean(np.abs(deltas))), "max_abs": max(map(abs, deltas))} if deltas else {},
        "retry_eligibility_changed_ids": retry_eligibility_changed,
        "quality": {m: base.paired_summary([(a[m], b[m]) for a, b in quality], 192) for m in ("hit10", "mrr10", "recall10")}}


def live192(attempt):
    from replay_pool_recall import load_config
    from urllib.parse import urlsplit
    import tarfile
    if Path(attempt).name != attempt or attempt in (".", "..", "live-smoke"):
        raise ValueError("new attempt directory required")
    out = OUT / attempt
    archive = OUT / (attempt + ".tar.gz")
    if out.exists() or archive.exists():
        raise ValueError("refusing to overwrite retained evidence")
    started = time.monotonic()
    deadline = started + 4170
    signal.signal(signal.SIGALRM, base.expired)
    signal.alarm(4170)
    state = {"status": "blocked", "denominator": 192, "pairs": [], "errors": [], "eta_checks": []}
    cases, source = [], {}
    try:
        manifest = json.loads((base.OUT / "manifest.json").read_text())
        old = json.loads((base.OUT / "checkpoint.json").read_text())
        verified = json.loads((OUT / "verified/manifest.json").read_text())
        config = load_config(base.CONFIG)
        preflight = {"hashes": {n: {"expected": h, "actual": base.digest(n)} for n, h in manifest["hashes"].items()},
            "resolved_config_equal": json.loads(base.encoded(asdict(config))) == manifest["resolved_config"],
            "source_manifest_equal": old["manifest_sha256"] == base.digest(base.OUT / "manifest.json"),
            "source_checkpoint_equal": verified["source_checkpoint_sha256"] == base.digest(base.OUT / "checkpoint.json"),
            "policy_equal": verified["policies"] == POLICIES}
        base.atomic(out / "preflight.json", preflight)
        validate_live_preflight(preflight)
        base.validate_config(config)
        cases = manifest["cases"]
        source = {p["id"]: p for p in old["pairs"]}
        if len(cases) != 192 or len(source) != 192 or {c["id"] for c in cases} != source.keys():
            raise ValueError("frozen192 coverage mismatch")
        for p in source.values():
            if not p["complete"] or base.sha(p["pool"]) != p["pool_sha256"]:
                raise ValueError("incomplete/corrupt frozen pool")
            validate_calls(p["arms"]["A"]["calls"])
        frozen = {"cases": cases, "schedule": [{"id": c["id"], "order": c["order"].replace("B", "S")} for c in cases],
            "policies": POLICIES, "policy_sha256": base.sha(POLICIES), "runner_sha256": base.digest(__file__),
            "tests_sha256": base.digest("tests/test_research_selective_second_pass.py"),
            "source_manifest_sha256": base.digest(base.OUT / "manifest.json"),
            "source_checkpoint_sha256": base.digest(base.OUT / "checkpoint.json"),
            "deadline_seconds": 4200, "inference_cutoff_seconds": 4170, "request_timeouts": [60, 30],
            "endpoint": "fixed-pool full rerank; fresh independent first pass per arm; no retrieval/E2E claim",
            "gates": {"net_hits": -1, "mrr_ci_lower": -.01, "guard_net_hits": 0, "guard_mrr_delta": -.01, "p95_speedup": .15}}
        base.atomic(out / "manifest.json", frozen)
        state["manifest_sha256"] = base.digest(out / "manifest.json")
        with no_network():
            for c in cases:
                p = source[c["id"]]
                provider = base.RecordedProvider(SimpleNamespace(name=config.cross_encoder_rerank.provider,
                    model=config.cross_encoder_rerank.model), replay=p["arms"]["A"]["calls"])
                result = whole_execute(c, p, config, "A", provider)
                if not result["complete"]:
                    raise ValueError("baseline adapter fallback")
                for key in ("outputs", "ranked", "features", "meta_predictions"):
                    if base.encoded(result[key]) != base.encoded(p["arms"]["A"][key]):
                        raise ValueError(f"baseline adapter parity: {c['id']} {key}")
                production_parity(c, p, config, result)
        base.atomic(out / "parity.json", {"passed": True, "n": 192, "actual_production_class": True})
        ce = config.cross_encoder_rerank
        parsed = urlsplit(ce.url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        metadata = {p: json.loads(smoke_json(origin + p, 5)) for p in ("/health", "/v1/models")}
        base.atomic(out / "service-before.json", metadata)
        base.atomic(out / "recorded-service.json", old["services_before"])
        changes = validate_model_metadata(old["services_before"][origin + "/v1/models"], metadata["/v1/models"])
        base.atomic(out / "metadata-comparison.json", {"runtime_instance_drift": changes, "other_fields_strictly_equal": True,
            "model_equivalence_proven": False, "limitation": "Local GGUF hash does not prove loaded model mapping"})
        print("LIVE192 preflight and production parity PASS 192/192", flush=True)
        state["status"] = "running"
        for position, case in enumerate(cases):
            if deadline - time.monotonic() < 200:
                raise TimeoutError("insufficient bounded-pair deadline reserve")
            pair = source[case["id"]]
            row = {"id": case["id"], "order": frozen["schedule"][position]["order"], "arms": {}, "complete": False}
            tick = time.monotonic()
            state["pairs"].append(row)
            try:
                for policy in row["order"]:
                    setup_tick = time.perf_counter()
                    fresh = FreshProvider(ce, deadline)
                    provider = base.RecordedProvider(fresh)
                    provider_setup = time.perf_counter() - setup_tick
                    result = whole_execute(case, pair, config, policy, provider)
                    result["setup_seconds"] += provider_setup
                    result["raw_http"] = fresh.raw
                    row["arms"][policy] = result
                    base.atomic(out / "pairs" / f"{position + 1:03d}.json", row)
                    if not result["complete"]:
                        raise ValueError(f"rerank failed {case['id']} {policy}")
                    validate_calls(result["calls"])
                    if result["calls"][0]["documents"] != pair["arms"]["A"]["calls"][0]["documents"]:
                        raise ValueError("first-pass document drift")
                row["fresh_baseline_parity"] = production_parity(case, pair, config, row["arms"]["A"])
                row["complete"] = True
            finally:
                row["seconds"] = time.monotonic() - tick
                base.atomic(out / "pairs" / f"{position + 1:03d}.json", row)
                base.atomic(out / "checkpoint.json", state)
            if position == 1:
                base.atomic(out / "smoke-first2.json", {"passed": True, "ids": [r["id"] for r in state["pairs"]],
                    "fresh_production_parity": True, "continues_without_repeating_pairs": True})
                print("Fresh whole-rerank smoke PASS first2; continuing frozen schedule", flush=True)
            if (position + 1) % 12 == 0:
                elapsed = time.monotonic() - started
                projected = elapsed + (191 - position) * sum(r["seconds"] for r in state["pairs"]) / (position + 1)
                state["eta_checks"].append({"pairs": position + 1, "elapsed": elapsed, "projected_seconds": projected})
                base.atomic(out / "checkpoint.json", state)
                print("LIVE192 checkpoint", position + 1, "ETA total", round(projected), flush=True)
                if projected > 4170:
                    raise TimeoutError("ETA exceeds campaign deadline")
        after = {p: json.loads(smoke_json(origin + p, 5)) for p in ("/health", "/v1/models")}
        base.atomic(out / "service-after.json", after)
        validate_model_metadata(metadata["/v1/models"], after["/v1/models"])
        postflight = {"hashes": {n: {"expected": h, "actual": base.digest(n)} for n, h in manifest["hashes"].items()}}
        base.atomic(out / "postflight.json", postflight)
        validate_live_preflight(postflight)
        if base.digest(__file__) != frozen["runner_sha256"] or base.sha(POLICIES) != frozen["policy_sha256"]:
            raise ValueError("runner/policy changed during campaign")
        state["status"] = "completed"
    except (Exception, base.DeadlineExpired) as exc:
        state["errors"].append(repr(exc))
        state["status"] = "blocked" if not state["pairs"] else "stopped"
    finally:
        signal.alarm(0)
        state["runtime_seconds"] = time.monotonic() - started
        base.atomic(out / "checkpoint.json", state)
        summary = large_summary(cases, state["pairs"]) if cases else {"denominator": 192, "complete_pairs": 0}
        summary.update(status=state["status"], errors=state["errors"], runtime_seconds=state["runtime_seconds"])
        summary["recorded_baseline_comparison"] = recorded_drift(cases, state["pairs"], source)
        summary["claim_eligible"] = state["status"] == "completed" and summary["complete_pairs"] == 192
        base.atomic(out / "summary.json", summary)
        base.atomic(out / "hashes.json", {str(p.relative_to(out)): base.digest(p) for p in sorted(out.rglob("*.json"))})
        with tarfile.open(archive, "w:gz") as stream:
            stream.add(out, arcname=out.name)
        base.atomic(OUT / (attempt + "-archive.json"), {"archive": str(archive), "sha256": base.digest(archive),
            "hash_index_sha256": base.digest(out / "hashes.json"), "total_seconds_including_archive": time.monotonic() - started})
        print(json.dumps({k: summary[k] for k in ("status", "errors", "complete_pairs", "runtime_seconds")}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--live-smoke", action="store_true")
    parser.add_argument("--live192", action="store_true")
    parser.add_argument("--live-attempt", default="live-smoke")
    args = parser.parse_args()
    OUT = args.output
    if args.live192 and args.live_smoke:
        parser.error("choose only one live protocol")
    if args.live192:
        live192(args.live_attempt)
    else:
        live_smoke(args.live_attempt) if args.live_smoke else run()