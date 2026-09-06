"""Offline R4 microbenchmark and conditional dataset independence audit."""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
import unicodedata
from collections import Counter

from code_diver.ranking.ltr_query_split import LtrQuerySplitter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/research/2026-09-05/latency-independence"
MANIFEST = ROOT / "artifacts/ce_meta_ranker/ranker.json"
DATASETS = ("intellij_eval_1000.answer_sets", "intellij_eval_where_only", "intellij_eval_mech150")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(query):
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", query).casefold()))


def labels(row, policy="exact_only"):
    values = {v.strip() for v in row["expected"]}
    if policy != "full":
        values = {v for v in values if not v.startswith("glob:")}
    if policy == "exact_only":
        values = {v for v in values if re.search(r"\.[A-Za-z0-9]+$", v) and not any(c in v for c in "*?[")}
    return values


def overlap(train, test):
    ids = {r["id"] for r in train}
    queries = {normalize(r["query"]) for r in train}
    signatures = {tuple(sorted(labels(r))) for r in train if labels(r)}
    files = set().union(*(labels(r) for r in train))
    result = {
        "id": [r["id"] for r in test if r["id"] in ids],
        "normalized_query": [r["id"] for r in test if normalize(r["query"]) in queries],
        "exact_answer_set": [r["id"] for r in test if labels(r) and tuple(sorted(labels(r))) in signatures],
        "any_exact_answer": [r["id"] for r in test if labels(r) & files],
    }
    return {"counts": {k: len(v) for k, v in result.items()}, "case_ids": result,
            "shared_exact_labels": len(files & set().union(*(labels(r) for r in test)))}


def slices(train, test):
    seen = {normalize(r["query"]) for r in train}
    novel_queries = []
    for row in test:
        query = normalize(row["query"])
        if query not in seen:
            novel_queries.append(row["id"])
            seen.add(query)
    risk = overlap(train, test)["case_ids"]
    excluded = set(risk["normalized_query"]) | set(risk["any_exact_answer"])
    return {"deduplicated_query_novel": novel_queries,
            "query_and_answer_novel": [i for i in novel_queries if i not in excluded],
            "family_overlap_risk": [r["id"] for r in test if r["id"] in excluded]}


def audit():
    manifest = json.loads(MANIFEST.read_text())
    datasets = {name: [json.loads(line) for line in (ROOT / f"datasets/{name}.jsonl").read_text().splitlines() if line.strip()] for name in DATASETS}
    result = {"provenance": "UNPROVEN: split reconstructed on current datasets, not recovered training dump", "datasets": {}, "pairs": {}}
    for name, rows in datasets.items():
        split = LtrQuerySplitter().split((r["id"] for r in rows), manifest["test_fraction"], manifest["seed"])
        train_ids = set(split.train_query_ids)
        train = [r for r in rows if r["id"] in train_ids]
        test = [r for r in rows if r["id"] not in train_ids]
        queries = Counter(normalize(r["query"]) for r in rows)
        result["datasets"][name] = {
            "rows": len(rows), "unique_ids": len({r["id"] for r in rows}),
            "unique_normalized_queries": len(queries),
            "duplicate_query_groups": sum(n > 1 for n in queries.values()),
            "duplicate_query_excess": sum(n - 1 for n in queries.values()),
            "label_policies": {p: {"nonempty_cases": sum(bool(labels(r, p)) for r in rows), "label_entries": sum(len(labels(r, p)) for r in rows)} for p in ("full", "no_glob", "exact_only")},
            "train": len(train), "test": len(test), "train_ids": list(split.train_query_ids), "test_ids": list(split.test_query_ids),
            "split_overlap": overlap(train, test),
            "slices": slices(train, test),
        }
    for a, b in itertools.combinations(DATASETS, 2):
        result["pairs"][f"{a} -> {b}"] = overlap(datasets[a], datasets[b])
    main = datasets[DATASETS[0]]
    train_ids = set(result["datasets"][DATASETS[0]]["train_ids"])
    result["conditional_training_overlap"] = {name: overlap([r for r in main if r["id"] in train_ids], datasets[name]) for name in DATASETS[1:]}
    paths = [MANIFEST, MANIFEST.parent / manifest["model_file"], ROOT / "uv.lock", ROOT / "pyproject.toml", Path(__file__), ROOT / "tests/test_research_latency_independence.py", ROOT / "scripts/train_ce_meta_ranker.py", ROOT / "src/code_diver/ranking/ltr_query_split.py", ROOT / "src/code_diver/ranking/ce_meta_feature_collector.py", ROOT / "src/code_diver/services/expected_path_matcher.py"]
    paths += [ROOT / f"datasets/{name}.jsonl" for name in DATASETS]
    paths += [ROOT / f"configs/intellij/{name}.yml" for name in ("intellij-h91a-champion", "intellij-h66b-champion")]
    result["sha256"] = {str(p.relative_to(ROOT)): sha256(p) for p in paths}
    result["corpus_hash"] = "BLOCKED: no indexed-corpus snapshot/provenance; no services accessed"
    return result


def stats(values):
    import numpy as np
    return {"n": len(values), "p50_ms": float(np.percentile(values, 50)), "p95_ms": float(np.percentile(values, 95))} if values else {"n": 0}


def worker(threads, repeats):
    import lightgbm as lgb
    import numpy as np
    import resource

    manifest = json.loads(MANIFEST.read_text())
    features = np.random.default_rng(34).normal(size=(34, 16))
    start = time.perf_counter_ns()
    booster = lgb.Booster(model_file=str(MANIFEST.parent / manifest["model_file"]))
    load_ms = (time.perf_counter_ns() - start) / 1e6
    kwargs = {} if threads == "default" else {"num_threads": int(threads)}
    start = time.perf_counter_ns()
    scores = booster.predict(features, **kwargs)
    first_ms = (time.perf_counter_ns() - start) / 1e6
    samples = []
    for _ in range(repeats):
        start = time.perf_counter_ns()
        current = booster.predict(features, **kwargs)
        samples.append((time.perf_counter_ns() - start) / 1e6)
        if not np.array_equal(current, scores):
            raise RuntimeError("Within-worker prediction drift")
    print(json.dumps({"load_ms": load_ms, "first_predict_ms": first_ms, "warm_ms": samples,
                      "scores": scores.tolist(), "feature_sha256": hashlib.sha256(features.tobytes()).hexdigest(),
                      "maxrss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024),
                      "trees": booster.num_trees(), "features": booster.num_feature(), "lightgbm": lgb.__version__, "numpy": np.__version__}))


def run_child(command, timeout):
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "timeout_seconds": timeout}
    if proc.returncode:
        return {"status": "error", "returncode": proc.returncode, "stderr": proc.stderr}
    return {"status": "ok", "data": json.loads(proc.stdout)}


def benchmark(smoke=False):
    import numpy as np
    start = time.monotonic()
    deadline = start + 270
    runs = {key: [] for key in ("1", "2", "4", "8", "default")}
    rounds, repeats = (1, 3) if smoke else (20, 50)
    rng = np.random.default_rng(34)
    disabled = set()
    for _ in range(rounds):
        for key in rng.permutation(list(runs)):
            remaining = deadline - time.monotonic()
            if key in disabled or remaining < 1:
                continue
            result = run_child([sys.executable, str(Path(__file__)), "--worker", str(key), "--repeats", str(repeats)], min(10, remaining))
            runs[key].append(result)
            if result["status"] != "ok":
                disabled.add(key)
    reference = next((r["data"]["scores"] for r in runs["1"] if r["status"] == "ok"), None)
    summary = {}
    for key, results in runs.items():
        data = [r["data"] for r in results if r["status"] == "ok"]
        summary[key] = {"completed_processes": len(data), "failures": [r for r in results if r["status"] != "ok"],
                        "load": stats([r["load_ms"] for r in data]),
                        "first_prediction": stats([r["first_predict_ms"] for r in data]),
                        "warm": stats([v for r in data for v in r["warm_ms"]]),
                        "max_abs_score_drift_vs_1": max(float(np.max(np.abs(np.asarray(r["scores"]) - reference))) for r in data) if data and reference is not None else None}
    return {"synthetic_only": True, "seed": 34, "shape": [34, 16], "cold_definition": "fresh Booster in fresh Python process; imports excluded, filesystem cache NOT flushed", "elapsed_seconds": time.monotonic() - start, "platform": platform.platform(), "python": sys.version, "cpu_count": os.cpu_count(), "thread_environment": {k: os.environ.get(k) for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")}, "summary": summary, "runs": runs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", choices=("1", "2", "4", "8", "default"))
    parser.add_argument("--repeats", type=int, default=50)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()
    if args.worker:
        worker(args.worker, args.repeats)
        return
    OUT.mkdir(parents=True, exist_ok=True)
    result = {"command": sys.argv, "audit": audit()}
    if not args.audit_only:
        result["benchmark"] = benchmark(args.smoke)
    path = OUT / ("smoke.json" if args.smoke else "audit.json" if args.audit_only else "results.json")
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(path)
    if "benchmark" in result:
        print(json.dumps(result["benchmark"]["summary"], indent=2))


if __name__ == "__main__":
    main()