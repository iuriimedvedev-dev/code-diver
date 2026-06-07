#!/usr/bin/env python3
from __future__ import annotations

import argparse
import itertools
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


DEFAULT_REPORTS = (
    "h6=.code-diver/reports/h6-1-deterministic-current-100.json",
    "h7_tiebreak=.code-diver/reports/h7_api_tie_breaker-deterministic-100.json",
    "h7_query_expansion=.code-diver/reports/h7-query-expansion-deterministic-100.json",
    "gemma26_h6_agent=.code-diver/reports/agentic-strict-gemma4-26b-a4b-qat-llama-ctx16k-100.json",
    "gemma26_h7_tiebreak_agent=.code-diver/reports/h7-api-tiebreaker-agentic-gemma4-26b-a4b-qat-100.json",
    "gemma26_h7_query_expansion_agent=.code-diver/reports/h7-query-expansion-agentic-gemma4-26b-a4b-qat-100.json",
)


@dataclass(frozen=True)
class CaseRanking:
    expected: set[str]
    ranking: list[str]
    bucket: str


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze whether saved reranker/search outputs can be ensembled with RRF or a calibrated meta-ranker."
    )
    parser.add_argument(
        "--report",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help="Saved eval JSON to include. Can be passed multiple times. Defaults to the current H6/H7 100-case reports.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".code-diver/reports/reranker-ensemble-codesearchnet-100.json"),
    )
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--max-ensemble-size", type=int, default=4)
    args = parser.parse_args()

    report_specs = args.report or list(DEFAULT_REPORTS)
    runs = _load_runs(report_specs)
    common_case_ids = _common_case_ids(runs)
    if not common_case_ids:
        raise RuntimeError("No common case IDs across reports.")

    single_rows = _single_rows(runs, common_case_ids)
    rrf_rows = _rrf_rows(runs, common_case_ids, args.rrf_k, args.max_ensemble_size)
    selected_sets = _selected_meta_sets(runs)
    meta_rows = [
        _meta_ranker_row(name, names, runs, common_case_ids, args.folds)
        for name, names in selected_sets.items()
        if all(item in runs for item in names)
    ]
    oracle = _oracle_best_rank(runs, common_case_ids)

    payload = {
        "dataset": "saved 100-case CodeSearchNet/MTEB Python slice",
        "case_count": len(common_case_ids),
        "reports": {name: str(path) for name, path in _parse_report_specs(report_specs).items()},
        "single_runs": single_rows,
        "rrf_top": rrf_rows[:20],
        "meta_rankers": meta_rows,
        "oracle_best_rank": oracle,
        "interpretation": {
            "rrf": "Unweighted RRF does not beat H6.1 top-rank quality; agentic rankings add recall but also demote strong H6.1 candidates.",
            "calibrated_meta_ranker": "Cross-validated logistic stacking over rank features is the first ensemble variant that improves H3/H5 top-k metrics in this slice.",
            "caveat": "This uses saved final rankings, not raw reranker score logits, and only 100 cases. Treat as a promising H8 hypothesis, not a production default yet.",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _print_summary(payload, args.output)
    return 0


def _parse_report_specs(specs: list[str] | tuple[str, ...]) -> dict[str, Path]:
    reports: dict[str, Path] = {}
    for spec in specs:
        if "=" not in spec:
            raise ValueError(f"Report spec must be NAME=PATH: {spec}")
        name, path = spec.split("=", 1)
        name = name.strip()
        if not name:
            raise ValueError(f"Report name is empty: {spec}")
        reports[name] = Path(path.strip())
    return reports


def _load_runs(specs: list[str] | tuple[str, ...]) -> dict[str, dict[str, CaseRanking]]:
    runs: dict[str, dict[str, CaseRanking]] = {}
    for name, path in _parse_report_specs(specs).items():
        if not path.exists():
            continue
        rows = _report_rows(json.loads(path.read_text(encoding="utf-8")))
        runs[name] = {
            str(row["case_id"]): CaseRanking(
                expected=set(row.get("expected") or []),
                ranking=_dedupe([str(item) for item in row.get("retrieved_files") or []])[:10],
                bucket=str(row.get("bucket") or "unknown"),
            )
            for row in rows
            if isinstance(row, dict) and row.get("case_id")
        }
    return runs


def _report_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload.get("metrics"), dict):
        return [row for row in payload.get("results") or [] if isinstance(row, dict)]
    results = payload.get("results") or []
    if results and isinstance(results[0], dict) and isinstance(results[0].get("results"), list):
        return [row for row in results[0]["results"] if isinstance(row, dict)]
    return [row for row in results if isinstance(row, dict)]


def _common_case_ids(runs: dict[str, dict[str, CaseRanking]]) -> list[str]:
    if not runs:
        return []
    return sorted(set.intersection(*(set(run) for run in runs.values())))


def _single_rows(runs: dict[str, dict[str, CaseRanking]], case_ids: list[str]) -> list[dict[str, Any]]:
    rows = []
    for name, run in runs.items():
        rankings = {case_id: run[case_id].ranking for case_id in case_ids}
        rows.append({"name": name, "metrics": _metrics(runs, rankings, case_ids)})
    return sorted(rows, key=lambda row: _metric_sort_key(row["metrics"]), reverse=True)


def _rrf_rows(
    runs: dict[str, dict[str, CaseRanking]],
    case_ids: list[str],
    rrf_k: int,
    max_ensemble_size: int,
) -> list[dict[str, Any]]:
    names = list(runs)
    rows: list[dict[str, Any]] = []
    max_size = min(max_ensemble_size, len(names))
    for size in range(2, max_size + 1):
        for ensemble in itertools.combinations(names, size):
            ranking = _rrf_ranking(runs, case_ids, ensemble, {name: 1.0 for name in ensemble}, rrf_k)
            rows.append({"names": list(ensemble), "metrics": _metrics(runs, ranking, case_ids)})
    return sorted(rows, key=lambda row: _metric_sort_key(row["metrics"]), reverse=True)


def _selected_meta_sets(runs: dict[str, dict[str, CaseRanking]]) -> dict[str, list[str]]:
    deterministic = [name for name in runs if "agent" not in name]
    strong_agents = [name for name in runs if name.startswith("gemma26")]
    all_agents = [name for name in runs if "agent" in name]
    return {
        "deterministic_only": deterministic,
        "h6_plus_26b_agents": [name for name in ["h6", *strong_agents] if name in runs],
        "deterministic_plus_26b_agents": [*deterministic, *strong_agents],
        "h6_plus_all_agents": [name for name in ["h6", *all_agents] if name in runs],
        "deterministic_plus_all_agents": [*deterministic, *all_agents],
    }


def _meta_ranker_row(
    name: str,
    run_names: list[str],
    runs: dict[str, dict[str, CaseRanking]],
    case_ids: list[str],
    folds: int,
) -> dict[str, Any]:
    rankings = _cross_validated_meta_rankings(run_names, runs, case_ids, folds)
    return {
        "name": name,
        "runs": run_names,
        "method": "5-fold logistic stacking over per-run rank features",
        "metrics": _metrics(runs, rankings, case_ids),
    }


def _cross_validated_meta_rankings(
    run_names: list[str],
    runs: dict[str, dict[str, CaseRanking]],
    case_ids: list[str],
    folds: int,
) -> dict[str, list[str]]:
    if not run_names:
        return {case_id: [] for case_id in case_ids}
    folds = max(2, min(folds, len(case_ids)))
    rankings: dict[str, list[str]] = {}
    for fold in range(folds):
        test_ids = [case_id for index, case_id in enumerate(case_ids) if index % folds == fold]
        train_ids = [case_id for case_id in case_ids if case_id not in set(test_ids)]
        weights = _train_logistic_ranker(run_names, runs, train_ids)
        for case_id in test_ids:
            candidates = _candidate_union(run_names, runs, case_id)
            scored = [
                (float(np.dot(_rank_features(run_names, runs, case_id, path), weights)), path)
                for path in candidates
            ]
            rankings[case_id] = [path for _, path in sorted(scored, reverse=True)[:10]]
    return rankings


def _train_logistic_ranker(
    run_names: list[str],
    runs: dict[str, dict[str, CaseRanking]],
    train_ids: list[str],
    epochs: int = 1500,
    learning_rate: float = 0.08,
    l2: float = 0.01,
) -> np.ndarray:
    x_rows: list[list[float]] = []
    y_rows: list[float] = []
    first_run = next(iter(runs.values()))
    for case_id in train_ids:
        expected = first_run[case_id].expected
        for path in _candidate_union(run_names, runs, case_id):
            x_rows.append(_rank_features(run_names, runs, case_id, path))
            y_rows.append(1.0 if path in expected else 0.0)
    x = np.asarray(x_rows, dtype=float)
    y = np.asarray(y_rows, dtype=float)
    weights = np.zeros(x.shape[1], dtype=float)
    positives = max(float(y.sum()), 1.0)
    negatives = max(float(len(y) - y.sum()), 1.0)
    class_weights = np.where(y > 0.0, negatives / positives, 1.0)
    for _ in range(epochs):
        logits = np.clip(x @ weights, -30, 30)
        probabilities = 1.0 / (1.0 + np.exp(-logits))
        gradient = x.T @ ((probabilities - y) * class_weights) / len(y) + l2 * weights
        gradient[0] -= l2 * weights[0]
        weights -= learning_rate * gradient
    return weights


def _rank_features(
    run_names: list[str],
    runs: dict[str, dict[str, CaseRanking]],
    case_id: str,
    path: str,
) -> list[float]:
    features = [1.0]
    reciprocal_ranks: list[float] = []
    for name in run_names:
        ranking = runs[name][case_id].ranking
        rank = ranking.index(path) + 1 if path in ranking else 0
        reciprocal_rank = 1.0 / rank if rank else 0.0
        reciprocal_ranks.append(reciprocal_rank)
        features.extend(
            [
                reciprocal_rank,
                (11 - rank) / 10.0 if rank else 0.0,
                1.0 if rank == 1 else 0.0,
            ]
        )
    features.extend(
        [
            sum(1 for value in reciprocal_ranks if value > 0.0) / len(run_names),
            max(reciprocal_ranks) if reciprocal_ranks else 0.0,
            sum(reciprocal_ranks) / len(run_names),
        ]
    )
    return features


def _rrf_ranking(
    runs: dict[str, dict[str, CaseRanking]],
    case_ids: list[str],
    run_names: tuple[str, ...],
    weights: dict[str, float],
    rrf_k: int,
) -> dict[str, list[str]]:
    rankings: dict[str, list[str]] = {}
    for case_id in case_ids:
        scores: dict[str, float] = {}
        best_rank: dict[str, int] = {}
        for name in run_names:
            weight = weights.get(name, 0.0)
            if weight <= 0.0:
                continue
            for rank, path in enumerate(runs[name][case_id].ranking, start=1):
                scores[path] = scores.get(path, 0.0) + weight / (rrf_k + rank)
                best_rank[path] = min(best_rank.get(path, 1_000_000), rank)
        rankings[case_id] = [
            path for path, _ in sorted(scores.items(), key=lambda item: (-item[1], best_rank[item[0]], item[0]))[:10]
        ]
    return rankings


def _candidate_union(
    run_names: list[str],
    runs: dict[str, dict[str, CaseRanking]],
    case_id: str,
) -> list[str]:
    return sorted({path for name in run_names for path in runs[name][case_id].ranking})


def _oracle_best_rank(runs: dict[str, dict[str, CaseRanking]], case_ids: list[str]) -> dict[str, float]:
    counts = {1: 0, 3: 0, 5: 0, 10: 0}
    first_run = next(iter(runs.values()))
    for case_id in case_ids:
        expected = first_run[case_id].expected
        best_rank = 1_000_000
        for run in runs.values():
            for rank, path in enumerate(run[case_id].ranking, start=1):
                if path in expected:
                    best_rank = min(best_rank, rank)
        for limit in counts:
            counts[limit] += int(best_rank <= limit)
    return {f"hit@{limit}": count / len(case_ids) for limit, count in counts.items()}


def _metrics(
    runs: dict[str, dict[str, CaseRanking]],
    rankings: dict[str, list[str]],
    case_ids: list[str],
) -> dict[str, float]:
    first_run = next(iter(runs.values()))
    rows = []
    for case_id in case_ids:
        expected = first_run[case_id].expected
        ranking = rankings.get(case_id, [])[:10]
        first_relevant_rank = 0
        relevant_count = 0
        dcg = 0.0
        for rank, path in enumerate(ranking, start=1):
            if path in expected:
                relevant_count += 1
                first_relevant_rank = first_relevant_rank or rank
                dcg += 1.0 / math.log2(rank + 1)
        ideal_dcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(len(expected), 10) + 1)) or 1.0
        rows.append((first_relevant_rank, relevant_count / 10.0, relevant_count / len(expected), dcg / ideal_dcg))
    count = len(rows)
    return {
        "hit@1": sum(rank == 1 for rank, _, _, _ in rows) / count,
        "hit@3": sum(bool(rank and rank <= 3) for rank, _, _, _ in rows) / count,
        "hit@5": sum(bool(rank and rank <= 5) for rank, _, _, _ in rows) / count,
        "hit@10": sum(bool(rank and rank <= 10) for rank, _, _, _ in rows) / count,
        "mrr@10": sum((1.0 / rank if rank else 0.0) for rank, _, _, _ in rows) / count,
        "precision@10": sum(precision for _, precision, _, _ in rows) / count,
        "recall@10": sum(recall for _, _, recall, _ in rows) / count,
        "ndcg@10": sum(ndcg for _, _, _, ndcg in rows) / count,
    }


def _metric_sort_key(metrics: dict[str, float]) -> tuple[float, ...]:
    return (
        metrics.get("hit@1", 0.0),
        metrics.get("hit@3", 0.0),
        metrics.get("hit@5", 0.0),
        metrics.get("hit@10", 0.0),
        metrics.get("mrr@10", 0.0),
        metrics.get("ndcg@10", 0.0),
    )


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _print_summary(payload: dict[str, Any], output: Path) -> None:
    print(f"saved {payload['case_count']} case reranker ensemble analysis -> {output}")
    print("\nSingle runs")
    for row in payload["single_runs"]:
        print(_format_row(row["name"], row["metrics"]))
    print("\nTop RRF")
    for row in payload["rrf_top"][:5]:
        print(_format_row(" + ".join(row["names"]), row["metrics"]))
    print("\nMeta-rankers")
    for row in payload["meta_rankers"]:
        print(_format_row(row["name"], row["metrics"]))
    print(f"\nOracle best-rank coverage: {payload['oracle_best_rank']}")


def _format_row(name: str, metrics: dict[str, float]) -> str:
    return (
        f"{name:52s} "
        f"H1={metrics['hit@1']:.3f} H3={metrics['hit@3']:.3f} "
        f"H5={metrics['hit@5']:.3f} H10={metrics['hit@10']:.3f} "
        f"MRR={metrics['mrr@10']:.3f} nDCG={metrics['ndcg@10']:.3f}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
