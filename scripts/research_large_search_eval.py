"""Frozen, sequential R2 research against the production H91a pipeline."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import random
import re
import signal
import subprocess
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse
from urllib.request import urlopen

from code_diver.domain import CodeItem, SearchResult
from code_diver.ranking import CeMetaFeatureExtractor
from code_diver.reranking import HubPriorScorer, RerankProviderFactory, RerankScore
from code_diver.strategies.cross_encoder_rerank_retrieval_strategy import CrossEncoderRerankRetrievalStrategy

OUT = Path("artifacts/research/2026-09-05/large-search-eval")
CONFIG = Path("configs/intellij/intellij-h91a-champion.yml")
DATA = {"full": Path("datasets/intellij_eval_1000.answer_sets.jsonl"),
        "where": Path("datasets/intellij_eval_where_only.jsonl"),
        "mech": Path("datasets/intellij_eval_mech150.jsonl")}
AUDIT = Path("artifacts/research/2026-09-05/latency-independence/audit.json")
SEED, N, BUDGET, DEADLINE = 42, 192, 850, 4200
STOP = frozenset("where is are does the a an of for and in to implemented managed handled".split())


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, default=str).encode()


def sha(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(encoded(value))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def journal(path, value):
    with path.open("ab") as stream:
        stream.write(encoded(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def rows(path):
    result = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if len({r["id"] for r in result}) != len(result):
        raise ValueError(f"duplicate case IDs: {path}")
    return {r["id"]: r for r in result}


def exact(expected):
    return {p for p in expected if not p.startswith("glob:") and not p.endswith("/")
            and not any(c in p for c in "*?[")}


def select(datasets, novel):
    full, where, mech = (datasets[k] for k in ("full", "where", "mech"))
    novel = set(novel)
    if (len(full), len(where), len(mech), len(novel), len(novel & where.keys())) != (1065, 78, 229, 95, 15):
        raise ValueError("dataset arithmetic differs; do not resize the study")
    chosen = set(where) | novel
    buckets = defaultdict(list)
    for case_id in sorted(set(mech) - chosen):
        gold = sorted(exact(mech[case_id]["expected"]))
        path = Path(gold[0]) if gold else Path("unknown")
        buckets[(path.suffix.lower(), path.parts[0])].append(case_id)
    rng = random.Random(SEED)
    quotas = {}
    total = sum(map(len, buckets.values()))
    for key, ids in sorted(buckets.items()):
        rng.shuffle(ids)
        quotas[key] = 34 * len(ids) // total
    remainder = sorted(buckets, key=lambda k: (-(34 * len(buckets[k]) % total), k))
    for key in remainder[:34 - sum(quotas.values())]:
        quotas[key] += 1
    guards = {i for key, ids in buckets.items() for i in ids[:quotas[key]]}
    chosen |= guards
    if len(chosen) != N or len(guards) != 34 or not chosen <= full.keys():
        raise ValueError("selection cardinality/containment mismatch")
    groups = defaultdict(list)
    for case_id in sorted(chosen):
        for dataset in datasets.values():
            if case_id in dataset and dataset[case_id]["query"] != full[case_id]["query"]:
                raise ValueError(f"query conflict for ID {case_id}")
        groups[(case_id in where, case_id in novel)].append(case_id)
    for ids in groups.values():
        rng.shuffle(ids)
    orders = {}
    order_index = 0
    for key in sorted(groups):
        for case_id in groups[key]:
            orders[case_id] = "AB" if order_index % 2 == 0 else "BA"
            order_index += 1
    schedule = []
    while any(groups.values()):
        for key in sorted(groups):
            if groups[key]:
                schedule.append(groups[key].pop())
    cases = []
    for case_id in schedule:
        labels = {k: v[case_id]["expected"] for k, v in datasets.items() if case_id in v}
        cases.append({"id": case_id, "query": full[case_id]["query"], "labels": labels,
                      "novel": case_id in novel, "added_guard": case_id in guards,
                      "order": orders[case_id]})
    return {"n": N, "seed": SEED, "cases": cases,
            "quotas": {"|".join(k): {"available": len(buckets[k]), "selected": v} for k, v in quotas.items()},
            "counts": {"where": len(where), "novel": len(novel), "overlap": len(novel & where.keys()),
                       "guards": len((chosen & mech.keys()) - where.keys()), "mech": len(chosen & mech.keys())},
            "label_conflicts": [c["id"] for c in cases if len({sha(x) for x in c["labels"].values()}) > 1],
            "independence": "novel95 reconstructed, NOT an independent historical-model holdout"}


def provenance():
    paths = [*DATA.values(), AUDIT, CONFIG, Path(__file__), Path("tests/test_research_large_search_eval.py"),
             Path("uv.lock"), Path("artifacts/ce_meta_ranker/ranker.json"),
             Path("artifacts/ce_meta_ranker/ce_meta_ranker.lgb.txt"),
             Path(".code-diver/intellij-h37-jvm-graph.json"),
             Path(".code-diver/models/rerankers/qwen3-reranker-0.6b/Qwen3-Reranker-0.6B-Q4_K_M.gguf")]
    paths.extend(sorted(Path("src/code_diver").rglob("*.py")))
    return {str(p): digest(p) for p in paths}


def terms(text):
    return set(re.findall(r"[a-z0-9]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", text).lower())) - STOP


def fragment(source, query, budget=BUDGET):
    if budget <= 0:
        raise ValueError("positive content ceiling required")
    offsets = [0] + [m.end() for m in re.finditer("\n", source)]
    query_terms = terms(query)
    start = max(offsets, key=lambda pos: len(query_terms & terms(source[pos:pos + budget])))
    return source[start:start + budget], start


def fragment_document(candidate, config, root, query):
    from code_diver.reranking.cross_encoder_document_builder import build_cross_encoder_document
    baseline = build_cross_encoder_document(candidate, config, root)
    try:
        path = (root / candidate.item.path).resolve()
        path.relative_to(root.resolve())
        raw = path.read_bytes()
        source = raw.decode("utf-8", errors="replace")
        if not source:
            raise ValueError("empty source")
        text, offset = fragment(source, query, config.max_document_chars)
        altered = copy.deepcopy(candidate)
        altered.item.content = text
        rendered = build_cross_encoder_document(altered, config, root)
        return rendered, {"path": candidate.item.path, "offset": offset, "content_chars": len(text),
                          "sha256": hashlib.sha256(raw).hexdigest(), "fallback": None}
    except (OSError, ValueError) as exc:
        return baseline, {"path": candidate.item.path, "fallback": repr(exc), "offset": None}


class DeadlineExpired(BaseException):
    pass


def expired(*_):
    raise DeadlineExpired("campaign deadline exhausted")


class FrozenPool:
    def __init__(self, candidates):
        self.snapshot = encoded([asdict(c) for c in candidates])

    def search(self, query, limit):
        return [SearchResult(CodeItem(**row["item"]), row["score"])
                for row in json.loads(self.snapshot)[:limit]]


class Trace:
    def __init__(self):
        self.config = SimpleNamespace(enabled=True, include_prompts=False)
        self.events = []

    def write(self, name, payload):
        self.events.append({"name": name, "payload": copy.deepcopy(payload)})


class RecordedProvider:
    def __init__(self, provider, event_path=None, context=None, replay=None):
        self.provider = provider
        self.name, self.model = provider.name, provider.model
        self.calls = []
        self.event_path, self.context, self.replay = event_path, context, replay

    def rerank(self, query, documents, top_n):
        call = {"documents": list(documents), "top_n": top_n, "chars": sum(map(len, documents)),
                "count": len(documents), "tokens": None, "token_reason": "served tokenizer unavailable"}
        self.calls.append(call)
        start = time.perf_counter()
        try:
            if self.replay is None:
                scores = self.provider.rerank(query, documents, top_n)
            else:
                saved = self.replay[len(self.calls) - 1]
                if saved["documents"] != documents or saved["top_n"] != top_n:
                    raise ValueError("parity document/request mismatch")
                scores = [RerankScore(**s) for s in saved["scores"]]
            indices = [s.index for s in scores]
            if len(indices) != len(documents) or set(indices) != set(range(len(documents))):
                raise ValueError("missing/duplicate/out-of-range CE scores")
            if any(not math.isfinite(s.score) for s in scores):
                raise ValueError("nonfinite CE score")
            call["scores"] = [asdict(s) for s in scores]
            return scores
        except BaseException as exc:
            call["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            call["seconds"] = time.perf_counter() - start
            if self.event_path:
                journal(self.event_path, {"context": self.context, "call": call})


class FeatureRecorder:
    def __init__(self, extractor):
        self.extractor, self.rows, self.seconds = extractor, [], 0.0

    def extract(self, query, candidates):
        start = time.perf_counter()
        result = self.extractor.extract(query, candidates)
        self.seconds += time.perf_counter() - start
        self.rows = [asdict(row) for row in result]
        return result


class PredictionRecorder:
    def __init__(self, booster):
        self.booster, self.seconds, self.values, self.error = booster, 0.0, [], None

    def predict(self, matrix):
        start = time.perf_counter()
        try:
            result = self.booster.predict(matrix)
            if not all(math.isfinite(float(x)) for x in result):
                raise ValueError("nonfinite meta predictions")
            self.values = [float(x) for x in result]
            return result
        except Exception as exc:
            self.error = repr(exc)
            raise
        finally:
            self.seconds += time.perf_counter() - start


class ResearchArm(CrossEncoderRerankRetrievalStrategy):
    @staticmethod
    def _ce_meta_ranker_eagerly_loaded(config):
        pass

    def _ce_meta_ranker_load(self):
        if self._ce_meta_ranker is None:
            raise RuntimeError("missing isolated meta model")

    def __init__(self, candidates, provider, config, root, hub_config, fanin, query, variant=False):
        super().__init__(FrozenPool(candidates), provider, copy.deepcopy(config), Trace(), root,
                         HubPriorScorer(copy.deepcopy(hub_config), copy.deepcopy(fanin).get))
        import lightgbm
        manifest = Path(config.ce_meta_model_path)
        model = manifest.parent / json.loads(manifest.read_text())["model_file"]
        self._ce_meta_ranker = PredictionRecorder(lightgbm.Booster(model_file=str(model)))
        self.ce_meta_feature_extractor = FeatureRecorder(CeMetaFeatureExtractor(self.hub_prior_scorer))
        self.query, self.variant, self.sources = query, variant, []

    def _document(self, result):
        if not self.variant:
            return super()._document(result)
        doc, source = fragment_document(result, self.config, self.repository_root, self.query)
        self.sources.append(source)
        return doc


def validate_config(config):
    ce = config.cross_encoder_rerank
    if (ce.candidate_limit, ce.max_document_chars, ce.second_pass_candidate_cap,
        ce.second_pass_max_document_chars, ce.second_pass_score_floor, ce.timeout_ms) != (34, 850, 24, 2400, 0.3, 60000):
        raise ValueError("champion budget mismatch")
    if not ce.ce_meta_ranker_enabled or not ce.second_pass_enabled or not ce.preserve_top_candidate:
        raise ValueError("champion stages disabled")
    if ce.use_file_head_document or ce.use_enhanced_file_document or ce.use_llm_purpose_document or ce.widen_when_uncertain_enabled:
        raise ValueError("unsupported champion document/window policy")
    if config.multi_query.enabled:
        raise ValueError("single-query study only")
    for url in (ce.url, config.embedding.url, config.storage.qdrant.url):
        if urlparse(url).hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("only existing localhost services permitted")


def service_metadata():
    urls = ["http://127.0.0.1:8081/health", "http://127.0.0.1:8081/v1/models",
            "http://127.0.0.1:8001/v1/models", "http://localhost:6333/aliases",
            "http://localhost:6333/collections/intellij_h66b_budget_qwen"]
    result = {}
    for url in urls:
        with urlopen(url, timeout=5) as response:
            result[url] = json.load(response)
    return result


def build_production(config):
    from replay_pool_recall import make_vector_store, make_embedding_provider, make_retrieval_strategy
    store = make_vector_store(config, progress=False)
    if not store.exists():
        raise RuntimeError("existing index required")
    provider = make_embedding_provider(config, store.metadata())
    strategy = make_retrieval_strategy(config, provider, store)
    if type(strategy) is not CrossEncoderRerankRetrievalStrategy:
        raise TypeError("expected actual production CE wrapper")
    strategy._ce_meta_ranker_load()
    if strategy._ce_meta_ranker is None:
        raise RuntimeError("production meta-model unavailable")
    return strategy, store


def score(paths, expected, limit=10):
    gold = exact(expected)
    ranked = paths[:limit]
    ranks = [i + 1 for i, p in enumerate(ranked) if p in gold]
    return {"hit10": float(bool(ranks)), "mrr10": 1 / ranks[0] if ranks else 0.0,
            "recall10": len(set(ranked) & gold) / len(gold) if gold else None,
            "gold": len(gold), "found": len(set(ranked) & gold)}


def execute_arm(arm, query):
    started = time.perf_counter()
    result = {"calls": arm.rerank_provider.calls, "sources": arm.sources}
    try:
        ranked = arm.search(query, 10)
        result["ranked"] = [r.item.path for r in ranked]
        result["outputs"] = [asdict(r) for r in ranked]
    except Exception as exc:
        result["error"] = repr(exc)
    except DeadlineExpired as exc:
        result["error"] = repr(exc)
        arm.interrupted_result = result
        raise
    finally:
        result.update(seconds=time.perf_counter() - started, events=arm.trace_logger.events,
                      features=arm.ce_meta_feature_extractor.rows,
                      feature_seconds=arm.ce_meta_feature_extractor.seconds,
                      meta_seconds=arm._ce_meta_ranker.seconds, meta_predictions=arm._ce_meta_ranker.values,
                      meta_error=arm._ce_meta_ranker.error, failure_count=arm.rerank_failure_count)
        result["complete"] = ("error" not in result and not result["meta_error"]
                              and not result["failure_count"]
                              and not any("error" in c for c in result["calls"])
                              and any(e["name"] == "cross_encoder_ce_meta_ranker" for e in result["events"]))
    return result


def smoke(config):
    path = OUT / "parity-smoke.json"
    if path.exists():
        raise ValueError("refusing to overwrite smoke")
    production, store = build_production(config)
    from replay_pool_recall import close_vector_store
    try:
        query = "Where is project opening implemented?"
        pool = production.base_strategy.search(query, 34)[:34]
        if len(pool) < 2:
            raise RuntimeError("insufficient parity pool")
        frozen = FrozenPool(pool)
        fanin = {c.item.path: production.hub_prior_scorer.fan_in_degree(c.item.path) for c in pool}
        production.base_strategy = frozen
        production.trace_logger = Trace()
        production.ce_meta_feature_extractor = FeatureRecorder(production.ce_meta_feature_extractor)
        live = RecordedProvider(production.rerank_provider)
        production.rerank_provider = live
        ranked = production.search(query, 10)
        replay = RecordedProvider(RerankProviderFactory().create(config.cross_encoder_rerank), replay=live.calls)
        arm = ResearchArm(pool, replay, config.cross_encoder_rerank, config.root, config.hub_prior, fanin, query)
        replayed = execute_arm(arm, query)
        passed = (replayed["complete"] and replayed["outputs"] == [asdict(r) for r in ranked]
                  and replayed["features"] == production.ce_meta_feature_extractor.rows
                  and len(live.calls) == len(replay.calls) and production.rerank_failure_count == 0)
        report = {"passed": passed, "kind": "one live production pool, recorded-score replay through isolated unmodified arm",
                  "query": query, "pool": json.loads(frozen.snapshot), "live_calls": live.calls,
                  "production_events": production.trace_logger.events, "replayed": replayed,
                  "runner_sha256": digest(__file__), "config_sha256": digest(CONFIG)}
        atomic(path, report)
        if not passed:
            raise RuntimeError("production parity failed")
        print("parity smoke PASS; live calls", len(live.calls), flush=True)
    finally:
        close_vector_store(store)


def prepare():
    path = OUT / "manifest.json"
    if path.exists():
        raise ValueError("refusing to overwrite frozen manifest")
    parity = json.loads((OUT / "parity-smoke.json").read_text())
    if not parity["passed"] or parity["runner_sha256"] != digest(__file__):
        raise ValueError("current runner parity required before freeze")
    audit = json.loads(AUDIT.read_text())
    audit = audit.get("audit", audit)
    manifest = select({k: rows(p) for k, p in DATA.items()},
                      audit["datasets"]["intellij_eval_1000.answer_sets"]["slices"]["query_and_answer_novel"])
    from importlib.metadata import version
    from replay_pool_recall import load_config
    manifest.update(hashes=provenance(), parity_sha256=digest(OUT / "parity-smoke.json"),
                    resolved_config=json.loads(encoded(asdict(load_config(CONFIG)))),
                    versions={name: version(name) for name in ("lightgbm", "numpy", "httpx", "qdrant-client", "pytest")},
                    deadline_seconds=DEADLINE, r1="deferred", frozen_at=time.time(),
                    git_revision=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                    git_status=subprocess.check_output(["git", "status", "--short"], text=True))
    atomic(path, manifest)
    print("frozen", manifest["counts"], "sha256", digest(path), flush=True)


def run(config, max_pairs):
    manifest = json.loads((OUT / "manifest.json").read_text())
    if manifest["hashes"] != provenance():
        raise ValueError("frozen provenance mismatch; no resume or inference")
    checkpoint = OUT / "checkpoint.json"
    if checkpoint.exists():
        state = json.loads(checkpoint.read_text())
        if state["manifest_sha256"] != digest(OUT / "manifest.json"):
            raise ValueError("manifest changed")
        if state.get("stop_reason") != "segment cap or bounded-pair deadline reserve":
            raise ValueError("resume permitted only at an intentional segment boundary")
        validate_retained_sources(state)
    else:
        state = {"manifest_sha256": digest(OUT / "manifest.json"), "started_at": time.time(), "pairs": [], "errors": []}
        atomic(checkpoint, state)
    remaining = state["started_at"] + DEADLINE - time.time()
    if remaining < 300:
        print("insufficient remaining campaign time; checkpoint retained", flush=True)
        return
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, remaining - 30)
    store = None
    try:
        before = service_metadata()
        state.setdefault("services_before", before)
        state.setdefault("segments", []).append({"started_at": time.time(), "before": before})
        production, store = build_production(config)
        initial = time.time()
        state["segments"][-1]["ready_at"] = initial
        completed_ids = {p["id"] for p in state["pairs"]}
        count = 0
        for case in manifest["cases"]:
            if case["id"] in completed_ids:
                continue
            if count >= max_pairs or state["started_at"] + DEADLINE - time.time() < 300:
                state["stop_reason"] = "segment cap or bounded-pair deadline reserve"
                break
            pair = {"id": case["id"], "order": case["order"], "arms": {}, "started_at": time.time()}
            state["pairs"].append(pair)
            try:
                start = time.perf_counter()
                pool = production.base_strategy.search(case["query"], 34)[:34]
                pair["retrieval_seconds"] = time.perf_counter() - start
                if not pool:
                    raise ValueError("empty candidate pool")
                frozen = FrozenPool(pool)
                pair["pool"] = json.loads(frozen.snapshot)
                pair["pool_sha256"] = sha(pair["pool"])
                fanin = {c.item.path: production.hub_prior_scorer.fan_in_degree(c.item.path) for c in pool}
                pair["fanin"] = fanin
                journal(OUT / "events.jsonl", {"id": case["id"], "stage": "retrieval", "pair": pair})
                for name in case["order"]:
                    provider = RecordedProvider(RerankProviderFactory().create(config.cross_encoder_rerank),
                                                OUT / "events.jsonl", {"id": case["id"], "arm": name})
                    start = time.perf_counter()
                    arm = ResearchArm(frozen.search(case["query"], 34), provider, config.cross_encoder_rerank,
                                      config.root, config.hub_prior, fanin, case["query"], name == "B")
                    setup_seconds = time.perf_counter() - start
                    try:
                        pair["arms"][name] = execute_arm(arm, case["query"])
                    except DeadlineExpired:
                        pair["arms"][name] = arm.interrupted_result
                        raise
                    pair["arms"][name]["setup_seconds"] = setup_seconds
                    if encoded([asdict(c) for c in pool]) != frozen.snapshot:
                        raise RuntimeError("shared retrieval pool mutated")
            except Exception as exc:
                pair["error"] = repr(exc)
            finally:
                pair["seconds"] = time.time() - pair["started_at"]
                pair["complete"] = len(pair["arms"]) == 2 and all(a["complete"] for a in pair["arms"].values()) and "error" not in pair
                atomic(OUT / "pairs" / f"{len(state['pairs']):03d}.json", pair)
                atomic(checkpoint, state)
            count += 1
            if len(state["pairs"]) % 12 == 0:
                elapsed = time.time() - state["started_at"]
                projected = elapsed + (N - len(state["pairs"])) * sum(p["seconds"] for p in state["pairs"]) / len(state["pairs"])
                state.setdefault("eta_checks", []).append({"attempted": len(state["pairs"]), "projected_seconds": projected, "elapsed": elapsed})
                print("checkpoint", len(state["pairs"]), "complete", sum(p["complete"] for p in state["pairs"]), "ETA total seconds", round(projected), flush=True)
                if projected > DEADLINE - 30:
                    state["stop_reason"] = "ETA exceeds fixed deadline; N remains 192"
                    break
        if len(state["pairs"]) == N:
            state["stop_reason"] = "all 192 attempted"
    except DeadlineExpired as exc:
        state["errors"].append(str(exc))
        state["stop_reason"] = "deadline"
    except Exception as exc:
        state["errors"].append(repr(exc))
        state["stop_reason"] = "explicit runtime error"
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        if store is not None:
            from replay_pool_recall import close_vector_store
            close_vector_store(store)
        try:
            state["services_after"] = service_metadata()
        except Exception as exc:
            state["errors"].append("postflight: " + repr(exc))
        state["elapsed_seconds"] = time.time() - state["started_at"]
        atomic(checkpoint, state)
    print("run segment stopped:", state.get("stop_reason"), "attempted", len(state["pairs"]), flush=True)


def validate_retained_sources(state):
    from replay_pool_recall import load_config
    root = load_config(CONFIG).root.resolve()
    for pair in state["pairs"]:
        if "pool" in pair and sha(pair["pool"]) != pair["pool_sha256"]:
            raise ValueError("retained pool hash mismatch")
        for arm in pair["arms"].values():
            for source in arm["sources"]:
                if source.get("sha256") and digest(root / source["path"]) != source["sha256"]:
                    raise ValueError("retained source hash mismatch")


def distribution(values):
    import numpy as np
    return {"n": len(values), "p50": float(np.percentile(values, 50)), "p95": float(np.percentile(values, 95)),
            "mean": float(np.mean(values)), "estimator": "linear"} if values else {"n": 0}


def paired_summary(values, planned):
    import numpy as np
    if not values:
        return {"complete": 0, "planned": planned, "missing_delta_bounds": [-1, 1]}
    a, b = np.array(values).T
    delta = b - a
    rng = np.random.default_rng(SEED)
    boot = delta[rng.integers(0, len(delta), (10000, len(delta)))].mean(axis=1)
    missing = planned - len(delta)
    return {"planned": planned, "complete": len(delta), "A": float(a.mean()), "B": float(b.mean()),
            "delta": float(delta.mean()), "ci95": np.percentile(boot, [2.5, 97.5]).tolist(),
            "wins": int((delta > 0).sum()), "losses": int((delta < 0).sum()), "ties": int((delta == 0).sum()),
            "missing_delta_bounds": [(float(delta.sum()) - missing) / planned, (float(delta.sum()) + missing) / planned]}


def summarize():
    manifest = json.loads((OUT / "manifest.json").read_text())
    state = json.loads((OUT / "checkpoint.json").read_text())
    pairs = {p["id"]: p for p in state["pairs"]}
    slices = {"selected192_full_labels": (manifest["cases"], "full"),
              "where78": ([c for c in manifest["cases"] if "where" in c["labels"]], "where"),
              "novel95_not_independent": ([c for c in manifest["cases"] if c["novel"]], "full"),
              "nonwhere_mechanical_guards": ([c for c in manifest["cases"] if "mech" in c["labels"] and "where" not in c["labels"]], "mech"),
              "selected_mechanical": ([c for c in manifest["cases"] if "mech" in c["labels"]], "mech")}
    seen_queries = set()
    dedup = []
    for case in manifest["cases"]:
        query = " ".join(case["query"].lower().split())
        if query not in seen_queries:
            dedup.append(case)
            seen_queries.add(query)
    slices["deduplicated_query_sensitivity"] = (dedup, "full")
    slices["no_glob_full_labels"] = ([c for c in manifest["cases"] if len(exact(c["labels"]["full"])) == len(set(c["labels"]["full"]))], "full")
    report = {"planned": N, "attempted": len(pairs), "complete": sum(p["complete"] for p in pairs.values()),
              "not_started": N - len(pairs), "stop_reason": state.get("stop_reason"), "slices": {},
              "bootstrap": {"seed": SEED, "replicates": 10000, "unit": "paired case; descriptive, not independent-case inference"},
              "elapsed_seconds": state["elapsed_seconds"], "errors": state["errors"], "latency": {},
              "manifest_sha256": digest(OUT / "manifest.json"), "checkpoint_sha256": digest(OUT / "checkpoint.json")}
    for name, (cases, label) in slices.items():
        complete = [(c, pairs[c["id"]]) for c in cases if c["id"] in pairs and pairs[c["id"]]["complete"]]
        attempted = [(c, pairs[c["id"]]) for c in cases if c["id"] in pairs]
        metric_rows = [(c, p, [score(p["arms"][a]["ranked"], c["labels"][label]) for a in "AB"]) for c, p in complete]
        metrics = {}
        for metric in ("hit10", "mrr10", "recall10"):
            values = [(m[0][metric], m[1][metric]) for _, _, m in metric_rows if m[0][metric] is not None]
            planned = sum(bool(exact(c["labels"][label])) for c in cases) if metric == "recall10" else len(cases)
            metrics[metric] = paired_summary(values, planned)
        pool_present = [(c, p) for c, p in attempted if "pool" in p and exact(c["labels"][label]) & {r["item"]["path"] for r in p["pool"]}]
        metrics["coverage"] = {"planned": len(cases), "attempted": len(attempted), "complete": len(complete),
                               "failed": len(attempted) - len(complete), "not_started": len(cases) - len(attempted),
                               "pool_gold_present": len(pool_present)}
        metrics["pool_present_hit10"] = paired_summary([(score(p["arms"]["A"]["ranked"], c["labels"][label])["hit10"],
                                                        score(p["arms"]["B"]["ranked"], c["labels"][label])["hit10"])
                                                       for c, p in pool_present if p["complete"]], len(pool_present))
        metrics["micro_recall10"] = {a: sum(m[i]["found"] for _, _, m in metric_rows) / max(1, sum(m[i]["gold"] for _, _, m in metric_rows)) for i, a in enumerate("AB")}
        metrics["discordant_ids"] = {"wins": [c["id"] for c, _, m in metric_rows if m[1]["hit10"] > m[0]["hit10"]],
                                      "losses": [c["id"] for c, _, m in metric_rows if m[1]["hit10"] < m[0]["hit10"]]}
        report["slices"][name] = metrics
    complete = [p for p in pairs.values() if p["complete"]]
    for arm in "AB":
        values = [p["arms"][arm] for p in complete]
        report["latency"][arm] = {"rerank": distribution([a["seconds"] for a in values]),
                                  "reconstructed_e2e": distribution([p["retrieval_seconds"] + p["arms"][arm]["seconds"] for p in complete]),
                                  "first_ce": distribution([a["calls"][0]["seconds"] for a in values if a["calls"]]),
                                  "retry_ce": distribution([a["calls"][1]["seconds"] if len(a["calls"]) > 1 else 0 for a in values]),
                                  "retry_counts": distribution([a["calls"][1]["count"] if len(a["calls"]) > 1 else 0 for a in values]),
                                  "total_rendered_chars": sum(c["chars"] for a in values for c in a["calls"]),
                                  "first_content_chars": distribution([len(c["documents"][i].split("\ncontent:\n", 1)[1]) for a in values for c in a["calls"][:1] for i in range(c["count"])]),
                                  "retry_total": sum(a["calls"][1]["count"] if len(a["calls"]) > 1 else 0 for a in values),
                                  "retry_buckets": dict(Counter("0" if len(a["calls"]) < 2 else "1-8" if a["calls"][1]["count"] <= 8 else "9-16" if a["calls"][1]["count"] <= 16 else "17-24" for a in values)),
                                  "model_setup": distribution([a["setup_seconds"] for a in values]),
                                  "feature_extraction": distribution([a["feature_seconds"] for a in values]),
                                  "meta_prediction": distribution([a["meta_seconds"] for a in values]),
                                  "source_fallbacks": sum(bool(s["fallback"]) for a in values for s in a["sources"])}
        report["latency"][arm]["warm_rerank"] = distribution([p["arms"][arm]["seconds"] for p in complete[1:]])
        report["latency"][arm]["by_order"] = {order: distribution([p["arms"][arm]["seconds"] for p in complete if p["order"] == order]) for order in ("AB", "BA")}
    report["latency"]["paired_rerank_delta"] = distribution([p["arms"]["B"]["seconds"] - p["arms"]["A"]["seconds"] for p in complete])
    report["failures"] = [{"id": p["id"], "error": p.get("error"), "arms": p["arms"]} for p in pairs.values() if not p["complete"]]
    report["order_counts"] = dict(Counter(p["order"] for p in pairs.values()))
    report["pool_sizes"] = dict(Counter(len(p.get("pool", [])) for p in pairs.values()))
    report["latency"]["scope"] = "shared retrieval counted once per reconstructed E2E arm; not standalone wall latency; setup/model loading excluded and recorded separately; service caches/order uncontrolled"
    atomic(OUT / "summary.json", report)
    print(json.dumps({k: report[k] for k in ("planned", "attempted", "complete", "not_started", "stop_reason")}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("smoke", "prepare", "run", "summarize"))
    parser.add_argument("--max-pairs", type=int, default=96)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.action == "prepare":
        prepare()
    elif args.action == "summarize":
        summarize()
    else:
        from replay_pool_recall import load_config
        config = load_config(CONFIG)
        validate_config(config)
        if args.action == "smoke":
            signal.signal(signal.SIGALRM, expired)
            signal.alarm(300)
            smoke(config)
            signal.alarm(0)
        else:
            run(config, args.max_pairs)


if __name__ == "__main__":
    main()