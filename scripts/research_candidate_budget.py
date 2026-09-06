"""Offline R3 evidence audit and historical fused-pool budget diagnostic.

No application imports, providers, model loading, or training. Labels are read only
by the metric join; selection receives path/rank/signal data only.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import platform
import time

BUDGET = 34
DEPTHS = (34, 60, 80)
QUOTAS = (("vector_score", 12), ("lexical_score", 12), ("graph_score", 10))
DATASETS = (
    "datasets/intellij_eval_where_only.jsonl",
    "datasets/intellij_eval_mech150.jsonl",
    "datasets/intellij_eval_1000.answer_sets.jsonl",
    "datasets/intellij_eval_where_holdout.jsonl",
)


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def normalize_query(query):
    return " ".join(query.casefold().split())


def load_dataset(path):
    cases = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["id"] in cases:
            raise ValueError("duplicate dataset case_id")
        cases[row["id"]] = row
    return cases


def load_pool(path):
    groups = defaultdict(list)
    queries = {}
    with path.open() as stream:
        names = json.loads(next(stream))["feature_names"]
        required = {name for name, _ in QUOTAS} | {"fused_score"}
        if not required <= set(names) or len(names) != len(set(names)):
            raise ValueError("missing or duplicate signal provenance")
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            qid = row["query_id"]
            if qid in queries and queries[qid] != row["query"]:
                raise ValueError("inconsistent query_id mapping")
            queries[qid] = row["query"]
            if len(row["features"]) != len(names):
                raise ValueError("feature width mismatch")
            signals = dict(zip(names, row["features"]))
            if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in signals.values()):
                raise ValueError("nonfinite or nonnumeric signal")
            rank = row["base_rank"]
            if not isinstance(rank, int) or rank < 1 or not row["path"]:
                raise ValueError("invalid candidate identity/order")
            groups[qid].append({"path": row["path"], "rank": rank, "signals": signals})
    for rows in groups.values():
        rows.sort(key=lambda row: row["rank"])
        if [r["rank"] for r in rows] != list(range(1, len(rows) + 1)):
            raise ValueError("noncontiguous or duplicate base ranks")
        if len({r["path"] for r in rows}) != len(rows):
            raise ValueError("duplicate pool file paths")
    return groups, queries, names


def select(rows, quotas=(), budget=BUDGET):
    if budget <= 0 or any(count < 0 for _, count in quotas) or sum(n for _, n in quotas) > budget:
        raise ValueError("invalid budget/quotas")
    base = sorted(rows, key=lambda row: (row["rank"], row["path"]))
    chosen = {}
    for channel, count in quotas:
        if any(channel not in row["signals"] for row in base):
            raise ValueError("missing channel provenance")
        eligible = sorted(
            (row for row in base if row["signals"][channel] > 0 and row["path"] not in chosen),
            key=lambda row: (-row["signals"][channel], row["rank"], row["path"]),
        )
        for row in eligible[:count]:
            chosen[row["path"]] = row
    for row in base:
        if len(chosen) >= budget:
            break
        chosen.setdefault(row["path"], row)
    return sorted(chosen.values(), key=lambda row: (row["rank"], row["path"]))


def evaluate_case(case, rows):
    expected = set(case["expected"])
    if not expected or any(any(c in path for c in "*?[") for path in expected):
        raise ValueError("exact-only nonempty labels required")
    pools = {f"fixed{depth}": select(rows, budget=depth) for depth in DEPTHS}
    pools["quota34"] = select(rows, QUOTAS)
    pools["full"] = rows
    hits = {arm: sorted(expected & {row["path"] for row in selected}) for arm, selected in pools.items()}
    return {
        "case_id": case["id"], "pool_size": len(rows), "expected_count": len(expected),
        "hits": hits,
        "recall": {arm: len(found) / len(expected) for arm, found in hits.items()},
        "gold_absent_from_export": sorted(expected - set(hits["full"])),
        "rescued_by_quota": sorted(set(hits["quota34"]) - set(hits["fixed34"])),
        "lost_by_quota": sorted(set(hits["fixed34"]) - set(hits["quota34"])),
        "selected_paths": {arm: [row["path"] for row in chosen] for arm, chosen in pools.items() if arm != "full"},
        "fused_tie_at_34": len(rows) > BUDGET and rows[33]["signals"]["fused_score"] == rows[34]["signals"]["fused_score"],
    }


def replay(feature_path, dataset_path, limit=None):
    groups, queries, names = load_pool(feature_path)
    cases = load_dataset(dataset_path)
    matched = sorted(set(cases) & set(groups))
    mismatch = [qid for qid in matched if queries[qid] != cases[qid]["query"]]
    if mismatch:
        raise ValueError(f"query text mismatch: {mismatch}")
    eligible = [qid for qid in matched if cases[qid]["expected"] and not any(
        any(c in p for c in "*?[") for p in cases[qid]["expected"])]
    if limit is not None:
        eligible = eligible[:limit]
    details = [evaluate_case(cases[qid], groups[qid]) for qid in eligible]
    total = sum(row["expected_count"] for row in details)
    metrics = {}
    for arm in ("fixed34", "fixed60", "fixed80", "quota34", "full"):
        metrics[arm] = {
            "micro_recall": sum(len(row["hits"][arm]) for row in details) / total if total else None,
            "macro_recall": sum(row["recall"][arm] for row in details) / len(details) if details else None,
            "gold_hits": sum(len(row["hits"][arm]) for row in details),
        }
    return {
        "scope": "historical single-query fused export; NOT H91a CE or multi-probe recall",
        "features": str(feature_path), "feature_sha256": digest(feature_path),
        "dataset": str(dataset_path), "dataset_sha256": digest(dataset_path),
        "feature_names": names, "export_queries": len(groups), "dataset_cases": len(cases),
        "missing_case_ids": sorted(set(cases) - set(groups)),
        "extra_export_ids": sorted(set(groups) - set(cases)),
        "matched_cases": len(matched), "evaluated_cases": len(details), "expected_files": total,
        "metrics": metrics, "details": details,
        "ce_recall": None, "ce_mrr": None, "ce_latency": None,
    }


def inspect_json(path, targets=None):
    result = {"path": str(path), "bytes": path.stat().st_size, "sha256": digest(path)}
    try:
        payload = json.loads(path.read_text())
    except (ValueError, UnicodeError) as exc:
        return {**result, "error": type(exc).__name__}
    counts = Counter()
    schemas = Counter()
    matched = set()
    stack = [payload]
    while stack:
        obj = stack.pop()
        if isinstance(obj, dict):
            if isinstance(obj.get("query_plan"), dict):
                counts["query_plan_objects"] += 1
                if obj["query_plan"].get("queries"):
                    counts["nonempty_query_plans"] += 1
                    if targets and (obj.get("case_id"), obj.get("question")) in targets:
                        matched.add(obj["case_id"])
            if obj.get("error"):
                counts["error_objects"] += 1
            for key, value in obj.items():
                if key in ("candidates", "ranked_paths", "pool_paths", "reranked_paths", "retrieved_paths", "retrieved_files") and isinstance(value, list):
                    counts[key + "_lists"] += 1
                    counts[key + "_max_length"] = max(counts[key + "_max_length"], len(value))
                if key == "results" and isinstance(value, list):
                    counts["result_rows"] += len(value)
                    for row in value:
                        if isinstance(row, dict):
                            schemas[",".join(sorted(row))] += 1
                if isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(obj, list):
            stack.extend(value for value in obj if isinstance(value, (dict, list)))
    return {**result, "counts": dict(counts), "result_schemas": dict(schemas),
            "target_plan_case_ids": sorted(matched)}


def audit_traces(root, target_queries):
    inventory = []
    for path in sorted((root / ".code-diver/traces").rglob("*.jsonl")):
        record = {"path": str(path), "bytes": path.stat().st_size}
        if "intellij" not in str(path):
            inventory.append({**record, "status": "not parsed: outside filename-selected IntelliJ scope"})
            continue
        events = Counter()
        matched = Counter()
        max_candidates = Counter()
        lengths = defaultdict(Counter)
        query_counts = defaultdict(Counter)
        explicit_case_ids = Counter()
        errors = 0
        with path.open() as stream:
            for line in stream:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    errors += 1
                    continue
                event = row.get("event", "unknown")
                events[event] += 1
                payload = row.get("payload", {})
                if payload.get("query"):
                    query_counts[event][payload["query"]] += 1
                if payload.get("case_id") or payload.get("query_id") or payload.get("request_id"):
                    explicit_case_ids[event] += 1
                for field in ("documents", "scores"):
                    if isinstance(payload.get(field), list):
                        lengths[event + ":" + field][len(payload[field])] += 1
                if payload.get("query") in target_queries:
                    matched[event] += 1
                candidates = payload.get("candidates", [])
                if isinstance(candidates, list):
                    max_candidates[event] = max(max_candidates[event], len(candidates))
        inventory.append({**record, "status": "parsed", "sha256": digest(path),
                          "events": dict(events), "target_query_events": dict(matched),
                          "max_candidates": dict(max_candidates), "parse_errors": errors,
                          "document_score_lengths": {k: dict(v) for k, v in lengths.items()},
                          "explicit_join_id_events": dict(explicit_case_ids),
                          "repeated_query_events": {k: sum(n - 1 for n in v.values()) for k, v in query_counts.items()}})
    return inventory


def audit(root):
    target_cases = [row for name in DATASETS for row in load_dataset(root / name).values()]
    targets = {(row["id"], row["query"]) for row in target_cases}
    records = []
    for directory in (".code-diver/reports", ".code-diver/traces", "artifacts/ltr", "artifacts/ce_meta_ranker"):
        for path in sorted((root / directory).rglob("*.json")):
            records.append(inspect_json(path, targets))
    for name in ("champion_results.json", "h83_results.json"):
        records.append(inspect_json(root / name, targets))
    features = []
    for path in sorted((root / "artifacts/ltr").rglob("*.jsonl")):
        with path.open() as stream:
            header = json.loads(next(stream))
            counts = Counter()
            ranks = defaultdict(int)
            queries = set()
            for line in stream:
                if line.strip():
                    row = json.loads(line)
                    queries.add(normalize_query(row.get("query", "")))
                    counts[str(row.get("query_id"))] += 1
                    ranks[str(row.get("query_id"))] = max(ranks[str(row.get("query_id"))], row.get("base_rank", 0))
        features.append({"path": str(path), "sha256": digest(path), "header": header,
                         "rows": sum(counts.values()), "queries": len(counts),
                         "min_rows_per_query": min(counts.values(), default=0),
                         "max_rank": max(ranks.values(), default=0),
                         "dataset_overlap": {
                             name: {"case_ids": len(set(counts) & set(load_dataset(root / name))),
                                    "normalized_queries": len(queries & {normalize_query(c["query"]) for c in load_dataset(root / name).values()})}
                             for name in DATASETS}})
    datasets = []
    for name in DATASETS:
        path = root / name
        cases = load_dataset(path)
        queries = Counter(normalize_query(row["query"]) for row in cases.values())
        datasets.append({"path": name, "sha256": digest(path), "cases": len(cases),
                         "duplicate_normalized_queries": sum(n - 1 for n in queries.values()),
                         "glob_cases": sum(any(any(c in p for c in "*?[") for p in row["expected"]) for row in cases.values())})
    manifest = {}
    for name in (
        "configs/intellij/intellij-h66b-champion.yml", "configs/intellij/intellij-h83-ce-twopass.yml",
        "configs/intellij/intellij-h91a-champion.yml", "configs/intellij/intellij-h91a-meta-ranker.yml",
        "artifacts/ce_meta_ranker/ranker.json", "artifacts/ce_meta_ranker/ce_meta_ranker.lgb.txt",
        ".code-diver/models/rerankers/qwen3-reranker-0.6b/Qwen3-Reranker-0.6B-Q4_K_M.gguf",
        ".code-diver/intellij-h37-jvm-graph.json", "uv.lock", "pyproject.toml", "package-lock.json",
        "scripts/replay_pool_recall.py", "scripts/replay_rerank_depth.py",
        "src/code_diver/strategies/graph_file_retrieval_strategy.py",
        "src/code_diver/ranking/ltr_feature_collector.py", "src/code_diver/ranking/ltr_feature_extractor.py",
    ):
        path = root / name
        manifest[name] = digest(path) if path.is_file() else None
    return {"json_files": len(records), "parse_errors": sum("error" in r for r in records),
            "nonempty_query_plans": sum(r.get("counts", {}).get("nonempty_query_plans", 0) for r in records),
            "target_plan_case_ids": sorted({qid for r in records for qid in r.get("target_plan_case_ids", [])}),
            "records": records, "feature_exports": features, "datasets": datasets,
            "traces": audit_traces(root, {row["query"] for row in target_cases}),
            "manifest": manifest, "python": platform.python_version(),
            "corpus_snapshot": "unknown; graph hash is not a source/Qdrant snapshot hash",
            "training_split": "unknown; H91a manifest has counts/seed but no query-id assignments"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", type=Path)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--cases", type=int)
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.audit == bool(args.features) or (args.features and not args.dataset):
        parser.error("choose --audit or --features PATH --dataset PATH")
    if args.cases is not None and args.cases <= 0:
        parser.error("--cases must be positive")
    started = time.monotonic()
    result = audit(Path(".")) if args.audit else replay(args.features, args.dataset, args.cases)
    result["wall_seconds"] = time.monotonic() - started
    result["script_sha256"] = digest(Path(__file__))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("records", "details", "traces")}))


if __name__ == "__main__":
    main()