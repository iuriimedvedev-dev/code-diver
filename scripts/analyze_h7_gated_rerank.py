#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True)
class CaseRow:
    case_id: str
    query: str
    expected: set[str]
    base: list[str]
    rerank: list[str]
    features: dict[str, float | str]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Simulate cost-aware gated rerank policies over saved H7 and reranker runs."
    )
    parser.add_argument("--base-report", type=Path, required=True)
    parser.add_argument("--rerank-report", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-strategy")
    parser.add_argument("--rerank-strategy")
    parser.add_argument("--reranker-name", default="reranker")
    parser.add_argument("--rerank-mean-ms", type=float)
    parser.add_argument("--rerank-cost-per-call-usd", type=float, default=0.0)
    parser.add_argument("--rerank-tokens-per-call", type=float, default=0.0)
    parser.add_argument("--train-size", type=int, default=700)
    parser.add_argument("--validation-size", type=int, default=150)
    parser.add_argument("--test-size", type=int, default=150)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--base-mean-ms", type=float, default=780.1964113758877)
    args = parser.parse_args()

    rows = _load_rows(
        args.base_report,
        args.rerank_report,
        args.trace,
        base_strategy=args.base_strategy,
        rerank_strategy=args.rerank_strategy,
    )
    random.Random(args.seed).shuffle(rows)
    train = rows[: args.train_size]
    validation = rows[args.train_size : args.train_size + args.validation_size]
    test = rows[
        args.train_size + args.validation_size : args.train_size
        + args.validation_size
        + args.test_size
    ]
    if not train or not validation or not test:
        raise RuntimeError("Train/validation/test split must be non-empty.")
    llm_usage = _llm_usage(
        args.trace,
        base_mean_ms=args.base_mean_ms,
        rerank_mean_ms=args.rerank_mean_ms,
        rerank_cost_per_call_usd=args.rerank_cost_per_call_usd,
        rerank_tokens_per_call=args.rerank_tokens_per_call,
    )

    candidates = [
        *_threshold_policies(args.reranker_name),
        *_route_threshold_policies(),
    ]
    validation_rows = [
        _policy_row(policy, validation, llm_usage, args.base_mean_ms)
        for policy in candidates
    ]
    best_by_ndcg_sec = max(
        validation_rows,
        key=lambda row: (row["metrics"]["ndcg_per_second"], row["metrics"]["hit@1"]),
    )
    best_by_utility = max(
        validation_rows,
        key=lambda row: (row["metrics"]["utility"], row["metrics"]["hit@1"]),
    )
    best_route_threshold = max(
        [
            row
            for row in validation_rows
            if row["policy"]["type"] == "route_margin_table"
        ],
        key=lambda row: (
            row["metrics"]["utility"],
            row["metrics"]["hit@1"],
            -row["metrics"]["rerank_call_rate"],
        ),
    )
    test_rows = [
        _policy_row(
            {"name": "always_h7", "type": "always_base"},
            test,
            llm_usage,
            args.base_mean_ms,
        ),
        _policy_row(
            {"name": f"always_{args.reranker_name}", "type": "always_rerank"},
            test,
            llm_usage,
            args.base_mean_ms,
        ),
        _policy_row(best_by_ndcg_sec["policy"], test, llm_usage, args.base_mean_ms),
        _policy_row(best_by_utility["policy"], test, llm_usage, args.base_mean_ms),
        _policy_row(best_route_threshold["policy"], test, llm_usage, args.base_mean_ms),
        _oracle_row(test, llm_usage, args.base_mean_ms),
    ]
    logistic = _train_logistic_gate(train)
    logistic_validation_rows = [
        _logistic_policy_row(
            logistic, threshold, validation, llm_usage, args.base_mean_ms
        )
        for threshold in [0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.6, 0.7]
    ]
    best_logistic = max(
        logistic_validation_rows,
        key=lambda row: (
            row["metrics"]["utility"],
            row["metrics"]["hit@1"],
            -row["metrics"]["rerank_call_rate"],
        ),
    )
    test_rows.append(
        _logistic_policy_row(
            logistic, best_logistic["threshold"], test, llm_usage, args.base_mean_ms
        )
    )
    mlp = _train_mlp_gate(train)
    mlp_validation_rows = [
        _mlp_policy_row(mlp, threshold, validation, llm_usage, args.base_mean_ms)
        for threshold in [0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.6, 0.7]
    ]
    best_mlp = max(
        mlp_validation_rows,
        key=lambda row: (
            row["metrics"]["utility"],
            row["metrics"]["hit@1"],
            -row["metrics"]["rerank_call_rate"],
        ),
    )
    test_rows.append(
        _mlp_policy_row(mlp, best_mlp["threshold"], test, llm_usage, args.base_mean_ms)
    )

    payload = {
        "base_report": str(args.base_report),
        "rerank_report": str(args.rerank_report),
        "base_strategy": args.base_strategy,
        "rerank_strategy": args.rerank_strategy,
        "reranker_name": args.reranker_name,
        "trace": str(args.trace),
        "split": {
            "seed": args.seed,
            "train": len(train),
            "validation": len(validation),
            "test": len(test),
        },
        "llm_usage": llm_usage,
        "validation_top": {
            "by_ndcg_per_second": best_by_ndcg_sec,
            "by_utility": best_by_utility,
            "route_threshold_by_utility": best_route_threshold,
            "logistic_by_utility": best_logistic,
            "mlp_by_utility": best_mlp,
        },
        "route_diagnostics": _route_diagnostics(rows),
        "feature_names": _feature_names(),
        "test_rows": test_rows,
        "interpretation": {
            "utility": "hit@1 - 0.01 * mean_seconds - 0.25 * api_cost_per_query_usd",
            "oracle": "Chooses rerank only when rerank improves first relevant rank; label leak upper bound.",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _print_table(test_rows)
    return 0


def _load_rows(
    base_report: Path,
    rerank_report: Path,
    trace: Path,
    *,
    base_strategy: str | None,
    rerank_strategy: str | None,
) -> list[CaseRow]:
    base_rows = {
        str(row["case_id"]): row
        for row in _report_rows(_read_json(base_report), strategy=base_strategy)
    }
    rerank_rows = {
        str(row["case_id"]): row
        for row in _report_rows(_read_json(rerank_report), strategy=rerank_strategy)
    }
    features = _trace_features(trace)
    rows: list[CaseRow] = []
    for case_id, base in base_rows.items():
        query = str(base.get("query") or "")
        rerank = rerank_rows.get(case_id)
        trace_features = features.get(query)
        if rerank is None or trace_features is None:
            continue
        rows.append(
            CaseRow(
                case_id=str(base["case_id"]),
                query=query,
                expected=set(base.get("expected") or []),
                base=[str(path) for path in base.get("retrieved_files") or []],
                rerank=[str(path) for path in rerank.get("retrieved_files") or []],
                features=trace_features,
            )
        )
    return sorted(rows, key=lambda row: row.case_id)


def _read_json(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    return json.loads(text[text.find("{") :])


def _report_rows(
    payload: dict[str, Any], *, strategy: str | None = None
) -> list[dict[str, Any]]:
    if isinstance(payload.get("metrics"), dict):
        return [row for row in payload.get("results") or [] if isinstance(row, dict)]
    results = payload.get("results") or []
    if (
        results
        and isinstance(results[0], dict)
        and isinstance(results[0].get("results"), list)
    ):
        selected = _select_strategy(results, strategy)
        return [row for row in selected.get("results") or [] if isinstance(row, dict)]
    strategies = payload.get("strategies") or []
    if strategies and isinstance(strategies[0], dict):
        selected = _select_strategy(strategies, strategy)
        return [row for row in selected.get("results") or [] if isinstance(row, dict)]
    return [row for row in results if isinstance(row, dict)]


def _select_strategy(
    strategies: list[dict[str, Any]], strategy: str | None
) -> dict[str, Any]:
    if strategy is None:
        return strategies[0]
    for row in strategies:
        if (
            row.get("strategy") == strategy
            or row.get("name") == strategy
            or row.get("hypothesis") == strategy
        ):
            return row
    available = [
        str(row.get("strategy") or row.get("name") or row.get("hypothesis"))
        for row in strategies
    ]
    raise RuntimeError(f"Strategy {strategy!r} not found. Available: {available}")


def _trace_features(path: Path) -> dict[str, dict[str, float | str]]:
    rows: dict[str, dict[str, float | str]] = {}
    for line in path.open(encoding="utf-8", errors="ignore"):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event") != "hybrid_rank_stages":
            continue
        payload = event.get("payload") or {}
        query = str(payload.get("query") or "")
        candidates = [
            candidate
            for candidate in payload.get("candidates") or []
            if candidate.get("final_rank")
        ]
        candidates = sorted(
            candidates,
            key=lambda candidate: int(candidate.get("final_rank") or 1_000_000),
        )
        unique_candidates = []
        seen = set()
        for candidate in candidates:
            path_value = candidate.get("path")
            if path_value in seen:
                continue
            seen.add(path_value)
            unique_candidates.append(candidate)
        unique_scores = [
            float((candidate.get("scores") or {}).get("total") or 0.0)
            for candidate in unique_candidates
        ]
        top = unique_scores[0] if unique_scores else 0.0
        second = unique_scores[1] if len(unique_scores) > 1 else 0.0
        top5 = unique_scores[:5]
        top10 = unique_scores[:10]
        score_sum = sum(max(score, 0.0) for score in top10) or 1.0
        entropy = -sum(
            (max(score, 0.0) / score_sum) * math.log(max(score, 1e-9) / score_sum)
            for score in top10
        )
        entropy_norm = entropy / math.log(max(len(top10), 2))
        top_candidate = unique_candidates[0] if unique_candidates else {}
        top_scores = top_candidate.get("scores") or {}
        agreement_top10 = 0
        vector_top10 = 0
        lexical_top10 = 0
        path_symbol_top10 = 0
        for candidate in unique_candidates[:10]:
            vector_hit = _rank_at_most(candidate.get("vector_rank"), 10)
            lexical_hit = _rank_at_most(candidate.get("lexical_rank"), 10)
            path_hit = _rank_at_most(candidate.get("path_rank"), 10)
            symbol_hit = _rank_at_most(
                candidate.get("symbol_rank"), 10
            ) or _rank_at_most(candidate.get("symbol_match_rank"), 10)
            vector_top10 += int(vector_hit)
            lexical_top10 += int(lexical_hit)
            path_symbol_top10 += int(path_hit or symbol_hit)
            agreement_top10 += int(vector_hit and lexical_hit)
        graph = payload.get("graph") or {}
        query_tokens = [
            token
            for token in query.replace("_", " ").replace("-", " ").split()
            if token
        ]
        rows[query] = {
            "route": str(payload.get("route") or "unknown"),
            "query_chars": float(len(query)),
            "query_tokens": float(len(query_tokens)),
            "candidate_count": float(payload.get("candidate_count") or 0),
            "top_score": top,
            "margin": top - second,
            "score_3_gap": top - (unique_scores[2] if len(unique_scores) > 2 else 0.0),
            "score_5_gap": top - (unique_scores[4] if len(unique_scores) > 4 else 0.0),
            "score_top5_mean": _mean(top5),
            "score_top10_mean": _mean(top10),
            "score_top10_std": float(np.std(np.asarray(top10, dtype=float)))
            if top10
            else 0.0,
            "score_top10_entropy": float(entropy_norm),
            "top_vector_score": float(top_scores.get("vector") or 0.0),
            "top_lexical_score": float(top_scores.get("lexical") or 0.0),
            "top_path_score": float(top_scores.get("path") or 0.0),
            "top_symbol_score": float(top_scores.get("symbol") or 0.0),
            "top_symbol_match_score": float(top_scores.get("symbol_match") or 0.0),
            "top_graph_score": float(top_scores.get("graph") or 0.0),
            "top_kind_file_summary": 1.0
            if top_candidate.get("kind") == "file_summary"
            else 0.0,
            "top_kind_file_manifest": 1.0
            if top_candidate.get("kind") == "file_manifest"
            else 0.0,
            "vector_top10_rate": vector_top10 / 10.0,
            "lexical_top10_rate": lexical_top10 / 10.0,
            "path_symbol_top10_rate": path_symbol_top10 / 10.0,
            "agreement_top10_rate": agreement_top10 / 10.0,
            "graph_candidate_count": float(graph.get("candidate_count") or 0),
            "graph_effective_depth": float(graph.get("effective_depth") or 0),
            "final_result_rate": float(graph.get("final_result_rate") or 0),
        }
    return rows


def _rank_at_most(value: Any, limit: int) -> bool:
    try:
        return 0 < int(value) <= limit
    except (TypeError, ValueError):
        return False


def _llm_usage(
    path: Path,
    *,
    base_mean_ms: float,
    rerank_mean_ms: float | None,
    rerank_cost_per_call_usd: float,
    rerank_tokens_per_call: float,
) -> dict[str, float]:
    if rerank_mean_ms is not None:
        return {
            "calls": 1.0,
            "input_tokens": 0.0,
            "output_tokens": 0.0,
            "total_tokens": rerank_tokens_per_call,
            "cost": rerank_cost_per_call_usd,
            "duration_ms": max(rerank_mean_ms - base_mean_ms, 0.0),
            "cost_per_call": rerank_cost_per_call_usd,
            "tokens_per_call": rerank_tokens_per_call,
            "duration_ms_per_call": max(rerank_mean_ms - base_mean_ms, 0.0),
        }
    usage = {
        "calls": 0.0,
        "input_tokens": 0.0,
        "output_tokens": 0.0,
        "total_tokens": 0.0,
        "cost": 0.0,
        "duration_ms": 0.0,
    }
    for line in path.open(encoding="utf-8", errors="ignore"):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event") != "llm_rerank_response":
            continue
        payload = event.get("payload") or {}
        usage["calls"] += 1
        usage["input_tokens"] += float(payload.get("input_tokens") or 0)
        usage["output_tokens"] += float(payload.get("output_tokens") or 0)
        usage["total_tokens"] += float(payload.get("total_tokens") or 0)
        usage["cost"] += float(payload.get("estimated_cost") or 0)
        usage["duration_ms"] += float(payload.get("duration_ms") or 0)
    calls = max(usage["calls"], 1.0)
    return {
        **usage,
        "cost_per_call": usage["cost"] / calls,
        "tokens_per_call": usage["total_tokens"] / calls,
        "duration_ms_per_call": usage["duration_ms"] / calls,
    }


def _threshold_policies(reranker_name: str) -> list[dict[str, Any]]:
    policies: list[dict[str, Any]] = [
        {"name": "always_h7", "type": "always_base"},
        {"name": f"always_{reranker_name}", "type": "always_rerank"},
    ]
    for threshold in [0.01, 0.015, 0.02, 0.03, 0.04, 0.05, 0.075, 0.1, 0.15, 0.2]:
        policies.append(
            {
                "name": f"margin_lt_{threshold}",
                "type": "margin_lt",
                "threshold": threshold,
            }
        )
    for route in ["semantic", "workflow", "path_symbol"]:
        policies.append({"name": f"route_{route}", "type": "route", "route": route})
        for threshold in [0.02, 0.04, 0.075, 0.1, 0.15]:
            policies.append(
                {
                    "name": f"route_{route}_margin_lt_{threshold}",
                    "type": "route_margin_lt",
                    "route": route,
                    "threshold": threshold,
                }
            )
    for threshold in [200, 300, 400, 600, 800, 1000]:
        policies.append(
            {
                "name": f"candidates_gt_{threshold}",
                "type": "candidates_gt",
                "threshold": threshold,
            }
        )
    return policies


def _route_threshold_policies() -> list[dict[str, Any]]:
    policies: list[dict[str, Any]] = []
    thresholds: list[float | None] = [None, 0.03, 0.05, 0.075, 0.1, 0.15, 0.2]
    for semantic in thresholds:
        for workflow in thresholds:
            for path_symbol in thresholds:
                if semantic is None and workflow is None and path_symbol is None:
                    continue
                table = {
                    "semantic": semantic,
                    "workflow": workflow,
                    "path_symbol": path_symbol,
                }
                name_parts = [
                    f"{route}:{'off' if threshold is None else threshold}"
                    for route, threshold in table.items()
                ]
                policies.append(
                    {
                        "name": "route_margin_table_" + ",".join(name_parts),
                        "type": "route_margin_table",
                        "thresholds": table,
                    }
                )
    return policies


def _policy_row(
    policy: dict[str, Any],
    rows: list[CaseRow],
    llm_usage: dict[str, float],
    base_mean_ms: float,
) -> dict[str, Any]:
    rerank_flags = [_should_rerank(policy, row) for row in rows]
    rankings = [_choose(row, use_rerank) for row, use_rerank in zip(rows, rerank_flags)]
    call_count = sum(1 for use_rerank in rerank_flags if use_rerank)
    return {
        "policy": policy,
        "metrics": _metrics(rows, rankings, call_count, llm_usage, base_mean_ms),
        "route_metrics": _route_metrics(
            rows, rankings, rerank_flags, llm_usage, base_mean_ms
        ),
    }


def _choose(row: CaseRow, rerank: bool) -> list[str]:
    return row.rerank if rerank else row.base


def _should_rerank(policy: dict[str, Any], row: CaseRow) -> bool:
    kind = policy["type"]
    if kind == "always_base":
        return False
    if kind == "always_rerank":
        return True
    if kind == "margin_lt":
        return float(row.features["margin"]) < float(policy["threshold"])
    if kind == "route":
        return row.features["route"] == policy["route"]
    if kind == "route_margin_lt":
        return row.features["route"] == policy["route"] and float(
            row.features["margin"]
        ) < float(policy["threshold"])
    if kind == "candidates_gt":
        return float(row.features["candidate_count"]) > float(policy["threshold"])
    if kind == "route_margin_table":
        thresholds = policy["thresholds"]
        route = str(row.features["route"])
        threshold = thresholds.get(route)
        return threshold is not None and float(row.features["margin"]) < float(
            threshold
        )
    raise ValueError(f"Unknown policy type: {kind}")


def _oracle_row(
    rows: list[CaseRow], llm_usage: dict[str, float], base_mean_ms: float
) -> dict[str, Any]:
    rankings = []
    rerank_flags = []
    calls = 0
    for row in rows:
        base_rank = _first_rank(row.base, row.expected)
        rerank_rank = _first_rank(row.rerank, row.expected)
        use_rerank = rerank_rank and (not base_rank or rerank_rank < base_rank)
        rerank_flags.append(bool(use_rerank))
        calls += int(bool(use_rerank))
        rankings.append(row.rerank if use_rerank else row.base)
    return {
        "policy": {"name": "oracle_improvement_gate", "type": "oracle"},
        "metrics": _metrics(rows, rankings, calls, llm_usage, base_mean_ms),
        "route_metrics": _route_metrics(
            rows, rankings, rerank_flags, llm_usage, base_mean_ms
        ),
    }


def _train_logistic_gate(rows: list[CaseRow]) -> dict[str, Any]:
    x_raw = np.asarray([_feature_vector(row) for row in rows], dtype=float)
    mean, std = _fit_scaler(x_raw)
    x = (x_raw - mean) / std
    y = np.asarray([_rerank_improves(row) for row in rows], dtype=float).reshape(-1, 1)
    weights = np.zeros((x.shape[1], 1), dtype=float)
    bias = np.zeros((1, 1), dtype=float)
    pos_weight = min(max((len(y) - y.sum()) / max(y.sum(), 1.0), 1.0), 20.0)
    for _ in range(1200):
        logits = x @ weights + bias
        pred = 1.0 / (1.0 + np.exp(-np.clip(logits, -40, 40)))
        sample_weight = np.where(y > 0.5, pos_weight, 1.0)
        grad = sample_weight * (pred - y) / max(len(y), 1)
        weights -= 0.05 * (x.T @ grad)
        bias -= 0.05 * grad.sum(axis=0, keepdims=True)
    return {
        "weights": weights.reshape(-1).tolist(),
        "bias": float(bias[0, 0]),
        "mean": mean.reshape(-1).tolist(),
        "std": std.reshape(-1).tolist(),
        "pos_rate": float(y.mean()),
    }


def _logistic_policy_row(
    model: dict[str, Any],
    threshold: float,
    rows: list[CaseRow],
    llm_usage: dict[str, float],
    base_mean_ms: float,
) -> dict[str, Any]:
    weights = np.asarray(model["weights"], dtype=float)
    mean = np.asarray(model["mean"], dtype=float)
    std = np.asarray(model["std"], dtype=float)
    rankings = []
    rerank_flags = []
    calls = 0
    for row in rows:
        features = (np.asarray(_feature_vector(row), dtype=float) - mean) / std
        logit = float(np.clip((features @ weights).item() + model["bias"], -40, 40))
        score = float(1.0 / (1.0 + math.exp(-logit)))
        use_rerank = score >= threshold
        rerank_flags.append(use_rerank)
        calls += int(use_rerank)
        rankings.append(row.rerank if use_rerank else row.base)
    return {
        "policy": {
            "name": f"logistic_gate_ge_{threshold}",
            "type": "logistic",
            "threshold": threshold,
        },
        "threshold": threshold,
        "metrics": _metrics(rows, rankings, calls, llm_usage, base_mean_ms),
        "route_metrics": _route_metrics(
            rows, rankings, rerank_flags, llm_usage, base_mean_ms
        ),
    }


def _train_mlp_gate(rows: list[CaseRow]) -> dict[str, Any]:
    x_raw = np.asarray([_feature_vector(row) for row in rows], dtype=float)
    mean, std = _fit_scaler(x_raw)
    x = (x_raw - mean) / std
    y = np.asarray([_rerank_improves(row) for row in rows], dtype=float).reshape(-1, 1)
    rng = np.random.default_rng(17)
    hidden = 10
    w1 = rng.normal(0.0, 0.12, size=(x.shape[1], hidden))
    b1 = np.zeros((1, hidden), dtype=float)
    w2 = rng.normal(0.0, 0.12, size=(hidden, 1))
    b2 = np.zeros((1, 1), dtype=float)
    pos_weight = min(max((len(y) - y.sum()) / max(y.sum(), 1.0), 1.0), 20.0)
    for _ in range(1800):
        hidden_pre = x @ w1 + b1
        hidden_act = np.maximum(hidden_pre, 0.0)
        logits = hidden_act @ w2 + b2
        pred = 1.0 / (1.0 + np.exp(-np.clip(logits, -40, 40)))
        sample_weight = np.where(y > 0.5, pos_weight, 1.0)
        grad_logits = sample_weight * (pred - y) / max(len(y), 1)
        grad_w2 = hidden_act.T @ grad_logits
        grad_b2 = grad_logits.sum(axis=0, keepdims=True)
        grad_hidden = grad_logits @ w2.T
        grad_hidden[hidden_pre <= 0.0] = 0.0
        grad_w1 = x.T @ grad_hidden
        grad_b1 = grad_hidden.sum(axis=0, keepdims=True)
        w1 -= 0.015 * grad_w1
        b1 -= 0.015 * grad_b1
        w2 -= 0.015 * grad_w2
        b2 -= 0.015 * grad_b2
    return {
        "w1": w1.tolist(),
        "b1": b1.reshape(-1).tolist(),
        "w2": w2.reshape(-1).tolist(),
        "b2": float(b2[0, 0]),
        "mean": mean.reshape(-1).tolist(),
        "std": std.reshape(-1).tolist(),
        "pos_rate": float(y.mean()),
    }


def _mlp_policy_row(
    model: dict[str, Any],
    threshold: float,
    rows: list[CaseRow],
    llm_usage: dict[str, float],
    base_mean_ms: float,
) -> dict[str, Any]:
    w1 = np.asarray(model["w1"], dtype=float)
    b1 = np.asarray(model["b1"], dtype=float)
    w2 = np.asarray(model["w2"], dtype=float).reshape(-1, 1)
    b2 = float(model["b2"])
    mean = np.asarray(model["mean"], dtype=float)
    std = np.asarray(model["std"], dtype=float)
    rankings = []
    rerank_flags = []
    calls = 0
    for row in rows:
        features = (np.asarray(_feature_vector(row), dtype=float) - mean) / std
        hidden = np.maximum(features @ w1 + b1, 0.0)
        logit = float(np.clip((hidden @ w2).item() + b2, -40, 40))
        score = float(1.0 / (1.0 + math.exp(-logit)))
        use_rerank = score >= threshold
        rerank_flags.append(use_rerank)
        calls += int(use_rerank)
        rankings.append(row.rerank if use_rerank else row.base)
    return {
        "policy": {
            "name": f"mlp_gate_ge_{threshold}",
            "type": "mlp",
            "threshold": threshold,
        },
        "threshold": threshold,
        "metrics": _metrics(rows, rankings, calls, llm_usage, base_mean_ms),
        "route_metrics": _route_metrics(
            rows, rankings, rerank_flags, llm_usage, base_mean_ms
        ),
    }


def _fit_scaler(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mean = x.mean(axis=0, keepdims=True)
    std = x.std(axis=0, keepdims=True)
    std[std < 1e-6] = 1.0
    return mean, std


def _feature_vector(row: CaseRow) -> list[float]:
    route = row.features["route"]
    return [
        1.0 if route == "semantic" else 0.0,
        1.0 if route == "workflow" else 0.0,
        1.0 if route == "path_symbol" else 0.0,
        min(float(row.features["query_chars"]) / 240.0, 1.0),
        min(float(row.features["query_tokens"]) / 32.0, 1.0),
        float(row.features["candidate_count"]) / 1200.0,
        float(row.features["graph_candidate_count"]) / 1200.0,
        float(row.features["top_score"]),
        float(row.features["margin"]),
        float(row.features["score_3_gap"]),
        float(row.features["score_5_gap"]),
        float(row.features["score_top5_mean"]),
        float(row.features["score_top10_mean"]),
        float(row.features["score_top10_std"]),
        float(row.features["score_top10_entropy"]),
        float(row.features["top_vector_score"]),
        float(row.features["top_lexical_score"]),
        float(row.features["top_path_score"]),
        float(row.features["top_symbol_score"]),
        float(row.features["top_symbol_match_score"]),
        float(row.features["top_graph_score"]),
        float(row.features["top_kind_file_summary"]),
        float(row.features["top_kind_file_manifest"]),
        float(row.features["vector_top10_rate"]),
        float(row.features["lexical_top10_rate"]),
        float(row.features["path_symbol_top10_rate"]),
        float(row.features["agreement_top10_rate"]),
        float(row.features["graph_effective_depth"]) / 3.0,
        float(row.features["final_result_rate"]),
    ]


def _feature_names() -> list[str]:
    return [
        "route_semantic",
        "route_workflow",
        "route_path_symbol",
        "query_chars_norm",
        "query_tokens_norm",
        "candidate_count_norm",
        "graph_candidate_count_norm",
        "top_score",
        "margin",
        "score_3_gap",
        "score_5_gap",
        "score_top5_mean",
        "score_top10_mean",
        "score_top10_std",
        "score_top10_entropy",
        "top_vector_score",
        "top_lexical_score",
        "top_path_score",
        "top_symbol_score",
        "top_symbol_match_score",
        "top_graph_score",
        "top_kind_file_summary",
        "top_kind_file_manifest",
        "vector_top10_rate",
        "lexical_top10_rate",
        "path_symbol_top10_rate",
        "agreement_top10_rate",
        "graph_effective_depth_norm",
        "final_result_rate",
    ]


def _rerank_improves(row: CaseRow) -> float:
    base_rank = _first_rank(row.base, row.expected)
    rerank_rank = _first_rank(row.rerank, row.expected)
    return float(bool(rerank_rank and (not base_rank or rerank_rank < base_rank)))


def _metrics(
    rows: list[CaseRow],
    rankings: list[list[str]],
    calls: int,
    llm_usage: dict[str, float],
    base_mean_ms: float,
) -> dict[str, float]:
    ranks = [_first_rank(ranking, row.expected) for row, ranking in zip(rows, rankings)]
    count = max(len(rows), 1)
    call_rate = calls / count
    mean_ms = base_mean_ms + call_rate * llm_usage["duration_ms_per_call"]
    cost_per_query = call_rate * llm_usage["cost_per_call"]
    ndcg = _mean(_ndcg(ranking, row.expected) for row, ranking in zip(rows, rankings))
    hit1 = _mean(1.0 if rank and rank <= 1 else 0.0 for rank in ranks)
    return {
        "cases": len(rows),
        "hit@1": hit1,
        "hit@3": _mean(1.0 if rank and rank <= 3 else 0.0 for rank in ranks),
        "hit@5": _mean(1.0 if rank and rank <= 5 else 0.0 for rank in ranks),
        "hit@10": _mean(1.0 if rank and rank <= 10 else 0.0 for rank in ranks),
        "mrr@10": _mean((1.0 / rank) if rank else 0.0 for rank in ranks),
        "ndcg@10": ndcg,
        "rerank_calls": float(calls),
        "rerank_call_rate": call_rate,
        "mean_ms_estimated": mean_ms,
        "api_cost_per_query_usd": cost_per_query,
        "api_cost_per_1000_usd": cost_per_query * 1000,
        "tokens_per_query": call_rate * llm_usage["tokens_per_call"],
        "ndcg_per_second": ndcg / max(mean_ms / 1000, 1e-9),
        "hit1_per_second": hit1 / max(mean_ms / 1000, 1e-9),
        "utility": hit1 - 0.01 * (mean_ms / 1000) - 0.25 * cost_per_query,
    }


def _route_metrics(
    rows: list[CaseRow],
    rankings: list[list[str]],
    rerank_flags: list[bool],
    llm_usage: dict[str, float],
    base_mean_ms: float,
) -> dict[str, dict[str, float]]:
    route_rows: dict[str, list[CaseRow]] = {}
    route_rankings: dict[str, list[list[str]]] = {}
    route_flags: dict[str, list[bool]] = {}
    for row, ranking, use_rerank in zip(rows, rankings, rerank_flags):
        route = str(row.features["route"])
        route_rows.setdefault(route, []).append(row)
        route_rankings.setdefault(route, []).append(ranking)
        route_flags.setdefault(route, []).append(use_rerank)
    metrics: dict[str, dict[str, float]] = {}
    for route, subset in sorted(route_rows.items()):
        route_calls = sum(1 for use_rerank in route_flags[route] if use_rerank)
        metrics[route] = _metrics(
            subset,
            route_rankings[route],
            route_calls,
            llm_usage,
            base_mean_ms,
        )
    return metrics


def _route_diagnostics(rows: list[CaseRow]) -> dict[str, dict[str, float]]:
    diagnostics: dict[str, dict[str, float]] = {}
    for route in sorted({str(row.features["route"]) for row in rows}):
        subset = [row for row in rows if row.features["route"] == route]
        margins = [float(row.features["margin"]) for row in subset]
        diagnostics[route] = {
            "cases": float(len(subset)),
            "rerank_improvement_rate": _mean(_rerank_improves(row) for row in subset),
            "h7_hit@1": _mean(
                1.0 if (_first_rank(row.base, row.expected) or 1_000_000) <= 1 else 0.0
                for row in subset
            ),
            "gemini_hit@1": _mean(
                1.0
                if (_first_rank(row.rerank, row.expected) or 1_000_000) <= 1
                else 0.0
                for row in subset
            ),
            "margin_mean": _mean(margins),
            "margin_p50": _percentile(margins, 50),
            "margin_p90": _percentile(margins, 90),
        }
    return diagnostics


def _first_rank(ranking: list[str], expected: set[str]) -> int | None:
    for index, path in enumerate(ranking, start=1):
        if path in expected:
            return index
    return None


def _ndcg(ranking: list[str], expected: set[str]) -> float:
    dcg = 0.0
    for index, path in enumerate(ranking[:10], start=1):
        if path in expected:
            dcg += 1.0 / math.log2(index + 1)
    ideal = (
        sum(
            1.0 / math.log2(index + 1) for index in range(1, min(len(expected), 10) + 1)
        )
        or 1.0
    )
    return dcg / ideal


def _mean(values: Any) -> float:
    materialized = list(values)
    return sum(materialized) / len(materialized) if materialized else 0.0


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile / 100.0
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[int(index)]
    fraction = index - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _print_table(rows: list[dict[str, Any]]) -> None:
    print(
        "| policy | hit@1 | hit@3 | hit@5 | hit@10 | mrr | ndcg | calls | call_rate | mean_ms | $/1k | ndcg/sec |"
    )
    print(
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    )
    for row in rows:
        metrics = row["metrics"]
        print(
            "| {name} | {hit1:.3f} | {hit3:.3f} | {hit5:.3f} | {hit10:.3f} | {mrr:.3f} | {ndcg:.3f} | {calls:.0f} | {rate:.3f} | {ms:.1f} | {cost:.3f} | {ndcg_sec:.3f} |".format(
                name=row["policy"]["name"],
                hit1=metrics["hit@1"],
                hit3=metrics["hit@3"],
                hit5=metrics["hit@5"],
                hit10=metrics["hit@10"],
                mrr=metrics["mrr@10"],
                ndcg=metrics["ndcg@10"],
                calls=metrics["rerank_calls"],
                rate=metrics["rerank_call_rate"],
                ms=metrics["mean_ms_estimated"],
                cost=metrics["api_cost_per_1000_usd"],
                ndcg_sec=metrics["ndcg_per_second"],
            )
        )


if __name__ == "__main__":
    raise SystemExit(main())
