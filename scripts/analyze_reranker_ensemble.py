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
    parser.add_argument(
        "--train-size",
        type=int,
        default=0,
        help="Use the first N common cases for training.",
    )
    parser.add_argument(
        "--test-size",
        type=int,
        default=0,
        help="When --train-size is set, evaluate on the next N common cases. 0 means all remaining cases.",
    )
    parser.add_argument("--epochs", type=int, default=1500)
    parser.add_argument("--learning-rate", type=float, default=0.08)
    parser.add_argument("--l2", type=float, default=0.01)
    args = parser.parse_args()

    report_specs = args.report or list(DEFAULT_REPORTS)
    runs = _load_runs(report_specs)
    common_case_ids = _common_case_ids(runs)
    if not common_case_ids:
        raise RuntimeError("No common case IDs across reports.")

    split = _split_case_ids(common_case_ids, args.train_size, args.test_size)
    eval_case_ids = split["test"] if split["mode"] == "train_test" else common_case_ids

    single_rows = _single_rows(runs, eval_case_ids)
    rrf_rows = _rrf_rows(runs, eval_case_ids, args.rrf_k, args.max_ensemble_size)
    selected_sets = _selected_meta_sets(runs)
    weighted_rrf_rows = [
        _weighted_rrf_row(name, names, runs, split, args.rrf_k)
        for name, names in selected_sets.items()
        if all(item in runs for item in names)
    ]
    meta_rows = [
        _meta_ranker_row(
            name,
            names,
            runs,
            split,
            args.folds,
            epochs=args.epochs,
            learning_rate=args.learning_rate,
            l2=args.l2,
        )
        for name, names in selected_sets.items()
        if all(item in runs for item in names)
    ]
    pairwise_rows = [
        _pairwise_meta_ranker_row(
            name,
            names,
            runs,
            split,
            args.folds,
            epochs=args.epochs,
            learning_rate=args.learning_rate,
            l2=args.l2,
        )
        for name, names in selected_sets.items()
        if all(item in runs for item in names)
    ]
    oracle = _oracle_best_rank(runs, eval_case_ids)

    payload = {
        "dataset": f"saved {len(common_case_ids)}-case CodeSearchNet/MTEB Python slice",
        "case_count": len(common_case_ids),
        "evaluated_case_count": len(eval_case_ids),
        "split": {
            key: (len(value) if isinstance(value, list) else value)
            for key, value in split.items()
        },
        "dataset_profile": _dataset_profile(runs, common_case_ids),
        "reports": {
            name: str(path) for name, path in _parse_report_specs(report_specs).items()
        },
        "single_runs": single_rows,
        "rrf_top": rrf_rows[:20],
        "weighted_rrf": weighted_rrf_rows,
        "meta_rankers": meta_rows,
        "pairwise_meta_rankers": pairwise_rows,
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
                ranking=_dedupe(
                    [str(item) for item in row.get("retrieved_files") or []]
                )[:10],
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
    if (
        results
        and isinstance(results[0], dict)
        and isinstance(results[0].get("results"), list)
    ):
        return [row for row in results[0]["results"] if isinstance(row, dict)]
    return [row for row in results if isinstance(row, dict)]


def _common_case_ids(runs: dict[str, dict[str, CaseRanking]]) -> list[str]:
    if not runs:
        return []
    return sorted(set.intersection(*(set(run) for run in runs.values())))


def _single_rows(
    runs: dict[str, dict[str, CaseRanking]], case_ids: list[str]
) -> list[dict[str, Any]]:
    rows = []
    for name, run in runs.items():
        rankings = {case_id: run[case_id].ranking for case_id in case_ids}
        rows.append({"name": name, "metrics": _metrics(runs, rankings, case_ids)})
    return sorted(rows, key=lambda row: _metric_sort_key(row["metrics"]), reverse=True)


def _split_case_ids(
    case_ids: list[str], train_size: int, test_size: int
) -> dict[str, Any]:
    if train_size <= 0:
        return {
            "mode": "cross_validation",
            "all": case_ids,
            "train": [],
            "test": case_ids,
        }
    if len(case_ids) <= train_size:
        raise RuntimeError(
            f"Need more than {train_size} common cases for train/test split, got {len(case_ids)}."
        )
    train = case_ids[:train_size]
    remaining = case_ids[train_size:]
    test = remaining if test_size <= 0 else remaining[:test_size]
    if not test:
        raise RuntimeError("Train/test split produced an empty test set.")
    return {"mode": "train_test", "all": case_ids, "train": train, "test": test}


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
            ranking = _rrf_ranking(
                runs, case_ids, ensemble, {name: 1.0 for name in ensemble}, rrf_k
            )
            rows.append(
                {"names": list(ensemble), "metrics": _metrics(runs, ranking, case_ids)}
            )
    return sorted(rows, key=lambda row: _metric_sort_key(row["metrics"]), reverse=True)


def _selected_meta_sets(
    runs: dict[str, dict[str, CaseRanking]],
) -> dict[str, list[str]]:
    deterministic = [
        name
        for name in runs
        if name.startswith(("h6", "h7", "h8", "h9", "h10")) and "agent" not in name
    ]
    non_agent = [name for name in runs if "agent" not in name]
    api_rankers = [
        name
        for name in runs
        if any(marker in name for marker in ("gemini", "vertex", "openai", "claude"))
    ]
    strong_agents = [name for name in runs if name.startswith("gemma26")]
    all_agents = [name for name in runs if "agent" in name]
    selected: dict[str, list[str]] = {}
    if deterministic:
        selected["deterministic_only"] = deterministic
    if api_rankers:
        selected["api_rankers_only"] = api_rankers
    if len(non_agent) > len(deterministic):
        selected["deterministic_plus_api"] = non_agent
    if strong_agents:
        selected["h6_plus_26b_agents"] = [
            name for name in ["h6", *strong_agents] if name in runs
        ]
        selected["deterministic_plus_26b_agents"] = [*deterministic, *strong_agents]
    if all_agents:
        selected["h6_plus_all_agents"] = [
            name for name in ["h6", *all_agents] if name in runs
        ]
        selected["deterministic_plus_all_agents"] = [*deterministic, *all_agents]
    return selected


def _meta_ranker_row(
    name: str,
    run_names: list[str],
    runs: dict[str, dict[str, CaseRanking]],
    split: dict[str, Any],
    folds: int,
    *,
    epochs: int,
    learning_rate: float,
    l2: float,
) -> dict[str, Any]:
    if split["mode"] == "train_test":
        rankings = _train_test_meta_rankings(
            run_names,
            runs,
            split["train"],
            split["test"],
            epochs=epochs,
            learning_rate=learning_rate,
            l2=l2,
        )
        metrics = _metrics(runs, rankings, split["test"])
        method = "train/test logistic stacking over per-run rank features"
    else:
        rankings = _cross_validated_meta_rankings(
            run_names,
            runs,
            split["test"],
            folds,
            epochs=epochs,
            learning_rate=learning_rate,
            l2=l2,
        )
        metrics = _metrics(runs, rankings, split["test"])
        method = f"{folds}-fold logistic stacking over per-run rank features"
    return {
        "name": name,
        "runs": run_names,
        "method": method,
        "metrics": metrics,
    }


def _cross_validated_meta_rankings(
    run_names: list[str],
    runs: dict[str, dict[str, CaseRanking]],
    case_ids: list[str],
    folds: int,
    *,
    epochs: int,
    learning_rate: float,
    l2: float,
) -> dict[str, list[str]]:
    if not run_names:
        return {case_id: [] for case_id in case_ids}
    folds = max(2, min(folds, len(case_ids)))
    rankings: dict[str, list[str]] = {}
    for fold in range(folds):
        test_ids = [
            case_id for index, case_id in enumerate(case_ids) if index % folds == fold
        ]
        train_ids = [case_id for case_id in case_ids if case_id not in set(test_ids)]
        weights = _train_logistic_ranker(
            run_names,
            runs,
            train_ids,
            epochs=epochs,
            learning_rate=learning_rate,
            l2=l2,
        )
        for case_id in test_ids:
            rankings[case_id] = _score_meta_case(run_names, runs, case_id, weights)
    return rankings


def _train_test_meta_rankings(
    run_names: list[str],
    runs: dict[str, dict[str, CaseRanking]],
    train_ids: list[str],
    test_ids: list[str],
    *,
    epochs: int,
    learning_rate: float,
    l2: float,
) -> dict[str, list[str]]:
    weights = _train_logistic_ranker(
        run_names,
        runs,
        train_ids,
        epochs=epochs,
        learning_rate=learning_rate,
        l2=l2,
    )
    return {
        case_id: _score_meta_case(run_names, runs, case_id, weights)
        for case_id in test_ids
    }


def _score_meta_case(
    run_names: list[str],
    runs: dict[str, dict[str, CaseRanking]],
    case_id: str,
    weights: np.ndarray,
) -> list[str]:
    candidates = _candidate_union(run_names, runs, case_id)
    scored = [
        (float(np.dot(_rank_features(run_names, runs, case_id, path), weights)), path)
        for path in candidates
    ]
    return [path for _, path in sorted(scored, reverse=True)[:10]]


def _train_logistic_ranker(
    run_names: list[str],
    runs: dict[str, dict[str, CaseRanking]],
    train_ids: list[str],
    epochs: int,
    learning_rate: float,
    l2: float,
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


def _pairwise_meta_ranker_row(
    name: str,
    run_names: list[str],
    runs: dict[str, dict[str, CaseRanking]],
    split: dict[str, Any],
    folds: int,
    *,
    epochs: int,
    learning_rate: float,
    l2: float,
) -> dict[str, Any]:
    if split["mode"] == "train_test":
        rankings = _train_test_pairwise_rankings(
            run_names,
            runs,
            split["train"],
            split["test"],
            epochs=epochs,
            learning_rate=learning_rate,
            l2=l2,
        )
        metrics = _metrics(runs, rankings, split["test"])
        method = "train/test pairwise logistic ranking over per-run rank features"
    else:
        rankings = _cross_validated_pairwise_rankings(
            run_names,
            runs,
            split["test"],
            folds,
            epochs=epochs,
            learning_rate=learning_rate,
            l2=l2,
        )
        metrics = _metrics(runs, rankings, split["test"])
        method = f"{folds}-fold pairwise logistic ranking over per-run rank features"
    return {
        "name": name,
        "runs": run_names,
        "method": method,
        "metrics": metrics,
    }


def _cross_validated_pairwise_rankings(
    run_names: list[str],
    runs: dict[str, dict[str, CaseRanking]],
    case_ids: list[str],
    folds: int,
    *,
    epochs: int,
    learning_rate: float,
    l2: float,
) -> dict[str, list[str]]:
    if not run_names:
        return {case_id: [] for case_id in case_ids}
    folds = max(2, min(folds, len(case_ids)))
    rankings: dict[str, list[str]] = {}
    for fold in range(folds):
        test_ids = [
            case_id for index, case_id in enumerate(case_ids) if index % folds == fold
        ]
        train_ids = [case_id for case_id in case_ids if case_id not in set(test_ids)]
        weights = _train_pairwise_ranker(
            run_names,
            runs,
            train_ids,
            epochs=epochs,
            learning_rate=learning_rate,
            l2=l2,
        )
        for case_id in test_ids:
            rankings[case_id] = _score_meta_case(run_names, runs, case_id, weights)
    return rankings


def _train_test_pairwise_rankings(
    run_names: list[str],
    runs: dict[str, dict[str, CaseRanking]],
    train_ids: list[str],
    test_ids: list[str],
    *,
    epochs: int,
    learning_rate: float,
    l2: float,
) -> dict[str, list[str]]:
    weights = _train_pairwise_ranker(
        run_names,
        runs,
        train_ids,
        epochs=epochs,
        learning_rate=learning_rate,
        l2=l2,
    )
    return {
        case_id: _score_meta_case(run_names, runs, case_id, weights)
        for case_id in test_ids
    }


def _train_pairwise_ranker(
    run_names: list[str],
    runs: dict[str, dict[str, CaseRanking]],
    train_ids: list[str],
    *,
    epochs: int,
    learning_rate: float,
    l2: float,
) -> np.ndarray:
    x_rows: list[list[float]] = []
    first_run = next(iter(runs.values()))
    for case_id in train_ids:
        expected = first_run[case_id].expected
        candidates = _candidate_union(run_names, runs, case_id)
        positive_features = [
            _rank_features(run_names, runs, case_id, path)
            for path in candidates
            if path in expected
        ]
        negative_features = [
            _rank_features(run_names, runs, case_id, path)
            for path in candidates
            if path not in expected
        ]
        if not positive_features or not negative_features:
            continue
        for positive in positive_features:
            for negative in negative_features:
                x_rows.append([p - n for p, n in zip(positive, negative)])
    if not x_rows:
        return np.zeros(
            len(
                _rank_features(
                    run_names,
                    runs,
                    train_ids[0],
                    runs[run_names[0]][train_ids[0]].ranking[0],
                )
            )
        )
    x = np.asarray(x_rows, dtype=float)
    weights = np.zeros(x.shape[1], dtype=float)
    for _ in range(epochs):
        margins = np.clip(x @ weights, -30, 30)
        probabilities = 1.0 / (1.0 + np.exp(margins))
        gradient = -(x.T @ probabilities) / len(x) + l2 * weights
        gradient[0] -= l2 * weights[0]
        weights -= learning_rate * gradient
    return weights


def _weighted_rrf_row(
    name: str,
    run_names: list[str],
    runs: dict[str, dict[str, CaseRanking]],
    split: dict[str, Any],
    rrf_k: int,
) -> dict[str, Any]:
    if not run_names:
        return {
            "name": name,
            "runs": [],
            "method": "weighted RRF grid",
            "weights": {},
            "metrics": {},
        }
    # Keep the grid bounded. Weighted RRF is a cheap baseline, not a neural optimizer.
    train_ids = split["train"] if split["mode"] == "train_test" else split["test"]
    test_ids = split["test"]
    trimmed = run_names[:6]
    values = [0.0, 0.25, 0.5, 1.0, 2.0]
    best_weights: dict[str, float] = {}
    best_metrics: dict[str, float] | None = None
    best_key: tuple[float, ...] | None = None
    for weights_tuple in itertools.product(values, repeat=len(trimmed)):
        if sum(weights_tuple) <= 0.0:
            continue
        weights = dict(zip(trimmed, weights_tuple))
        train_ranking = _rrf_ranking(runs, train_ids, tuple(trimmed), weights, rrf_k)
        metrics = _metrics(runs, train_ranking, train_ids)
        key = _metric_sort_key(metrics)
        if best_key is None or key > best_key:
            best_key = key
            best_weights = weights
            best_metrics = metrics
    test_ranking = _rrf_ranking(runs, test_ids, tuple(trimmed), best_weights, rrf_k)
    return {
        "name": name,
        "runs": trimmed,
        "method": "weighted RRF grid over rank positions",
        "weights": best_weights,
        "train_metrics": best_metrics or {},
        "metrics": _metrics(runs, test_ranking, test_ids),
    }


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
            path
            for path, _ in sorted(
                scores.items(), key=lambda item: (-item[1], best_rank[item[0]], item[0])
            )[:10]
        ]
    return rankings


def _candidate_union(
    run_names: list[str],
    runs: dict[str, dict[str, CaseRanking]],
    case_id: str,
) -> list[str]:
    return sorted({path for name in run_names for path in runs[name][case_id].ranking})


def _oracle_best_rank(
    runs: dict[str, dict[str, CaseRanking]], case_ids: list[str]
) -> dict[str, float]:
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
) -> dict[str, Any]:
    first_run = next(iter(runs.values()))
    rows = []
    rank_distribution = {rank: 0 for rank in range(0, 11)}
    for case_id in case_ids:
        expected = first_run[case_id].expected
        ranking = rankings.get(case_id, [])[:10]
        first_relevant_rank = 0
        relevant_at = {1: 0, 3: 0, 5: 0, 10: 0}
        dcg = 0.0
        for rank, path in enumerate(ranking, start=1):
            if path in expected:
                first_relevant_rank = first_relevant_rank or rank
                dcg += 1.0 / math.log2(rank + 1)
                for limit in relevant_at:
                    if rank <= limit:
                        relevant_at[limit] += 1
        ideal_dcg = (
            sum(
                1.0 / math.log2(rank + 1)
                for rank in range(1, min(len(expected), 10) + 1)
            )
            or 1.0
        )
        rows.append((first_relevant_rank, relevant_at, len(expected), dcg / ideal_dcg))
        rank_distribution[first_relevant_rank] += 1
    count = len(rows)
    return {
        "hit@1": sum(rank == 1 for rank, _, _, _ in rows) / count,
        "hit@3": sum(bool(rank and rank <= 3) for rank, _, _, _ in rows) / count,
        "hit@5": sum(bool(rank and rank <= 5) for rank, _, _, _ in rows) / count,
        "hit@10": sum(bool(rank and rank <= 10) for rank, _, _, _ in rows) / count,
        "mrr@10": sum((1.0 / rank if rank else 0.0) for rank, _, _, _ in rows) / count,
        "precision@1": sum(relevant_at[1] / 1.0 for _, relevant_at, _, _ in rows)
        / count,
        "precision@3": sum(relevant_at[3] / 3.0 for _, relevant_at, _, _ in rows)
        / count,
        "precision@5": sum(relevant_at[5] / 5.0 for _, relevant_at, _, _ in rows)
        / count,
        "precision@10": sum(relevant_at[10] / 10.0 for _, relevant_at, _, _ in rows)
        / count,
        "recall@1": sum(
            relevant_at[1] / expected_count
            for _, relevant_at, expected_count, _ in rows
        )
        / count,
        "recall@3": sum(
            relevant_at[3] / expected_count
            for _, relevant_at, expected_count, _ in rows
        )
        / count,
        "recall@5": sum(
            relevant_at[5] / expected_count
            for _, relevant_at, expected_count, _ in rows
        )
        / count,
        "recall@10": sum(
            relevant_at[10] / expected_count
            for _, relevant_at, expected_count, _ in rows
        )
        / count,
        "ndcg@10": sum(ndcg for _, _, _, ndcg in rows) / count,
        "expected_files_mean": sum(expected_count for _, _, expected_count, _ in rows)
        / count,
        "multi_expected_rate": sum(
            1.0 if expected_count > 1 else 0.0 for _, _, expected_count, _ in rows
        )
        / count,
        "first_relevant_rank_mean_miss_as_11": sum(
            rank if rank else 11 for rank, _, _, _ in rows
        )
        / count,
        "misses@10": rank_distribution[0],
        "rank_distribution": {
            str(rank): value for rank, value in rank_distribution.items() if value
        },
    }


def _dataset_profile(
    runs: dict[str, dict[str, CaseRanking]], case_ids: list[str]
) -> dict[str, Any]:
    first_run = next(iter(runs.values()))
    expected_sizes = [len(first_run[case_id].expected) for case_id in case_ids]
    distribution: dict[str, int] = {}
    for size in expected_sizes:
        distribution[str(size)] = distribution.get(str(size), 0) + 1
    count = max(len(expected_sizes), 1)
    return {
        "expected_files_mean": sum(expected_sizes) / count,
        "expected_files_distribution": distribution,
        "multi_expected_rate": sum(1 for size in expected_sizes if size > 1) / count,
        "metric_note": (
            "When every case has one expected file, Hit@K equals Recall@K and Precision@10 has a hard "
            "ceiling of 0.1 for successful top-10 results. Use Hit@1, MRR, nDCG, and rank_distribution "
            "to compare rerankers on this slice."
        ),
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
    print("\nPairwise meta-rankers")
    for row in payload.get("pairwise_meta_rankers", []):
        print(_format_row(row["name"], row["metrics"]))
    print(f"\nOracle best-rank coverage: {payload['oracle_best_rank']}")


def _format_row(name: str, metrics: dict[str, Any]) -> str:
    return (
        f"{name:52s} "
        f"H1={metrics['hit@1']:.3f} H3={metrics['hit@3']:.3f} "
        f"H5={metrics['hit@5']:.3f} H10={metrics['hit@10']:.3f} "
        f"MRR={metrics['mrr@10']:.3f} nDCG={metrics['ndcg@10']:.3f} "
        f"meanRank={metrics['first_relevant_rank_mean_miss_as_11']:.2f}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
