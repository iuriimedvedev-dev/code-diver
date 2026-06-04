from __future__ import annotations

import argparse
import json
import random
from dataclasses import replace
from itertools import product
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from code_diver.cli import close_vector_store, make_embedding_provider
from code_diver.config import ConfigLoader
from code_diver.config.trace_config import TraceConfig
from code_diver.domain import CodeItemIndexKindResolver, EvalCase, SearchResult
from code_diver.env import EnvFileLoader
from code_diver.services import DatasetLoader
from code_diver.store import create_vector_store
from code_diver.strategies import HybridRankContext, HybridRetrievalStrategy, RetrievalStrategyFactory


WEIGHT_FIELDS = (
    "vector_weight",
    "lexical_weight",
    "path_weight",
    "symbol_weight",
    "symbol_match_weight",
    "graph_weight",
    "file_vote_weight",
)
FEATURE_KEYS = (
    "vector",
    "lexical",
    "path_score",
    "symbol",
    "symbol_match",
    "graph",
    "file_vote",
    "kind_weight",
)
SCORING_FEATURE_KEYS = FEATURE_KEYS[:7]


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate H5 hybrid retrieval weights on a train/validation split.")
    parser.add_argument("--config", type=Path, default=Path("configs/codesearchnet-mteb-python-h5-qwen-quality.yml"))
    parser.add_argument("--output", type=Path, default=Path(".code-diver/reports/h5-hybrid-weight-calibration.json"))
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--train-size", type=int, default=700)
    parser.add_argument("--validation-size", type=int, default=300)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--feature-cache", type=Path)
    parser.add_argument("--reuse-feature-cache", action="store_true")
    parser.add_argument("--grid-step", choices=["coarse", "medium"], default="coarse")
    parser.add_argument("--mlp-depth", type=int, choices=[0, 1, 2, 3], default=0)
    parser.add_argument("--mlp-output", choices=["scalar", "weights"], default="scalar")
    parser.add_argument("--mlp-hidden-size", type=int, default=16)
    parser.add_argument("--mlp-epochs", type=int, default=160)
    parser.add_argument("--mlp-learning-rate", type=float, default=0.02)
    args = parser.parse_args()

    base_config = ConfigLoader().load(args.config)
    EnvFileLoader().load(base_config.env_file.path, base_config.env_file.override)
    config = replace(
        base_config,
        search=replace(base_config.search, strategy="hybrid", limit=args.limit),
        trace=TraceConfig(enabled=False, artifact=base_config.trace.artifact, include_prompts=False),
    )
    vector_store = create_vector_store(config)
    started = perf_counter()
    try:
        if not vector_store.exists():
            raise RuntimeError(f"Index does not exist for {args.config}. Run index/evaluate --reindex first.")
        provider = make_embedding_provider(config, vector_store.metadata())
        strategy = RetrievalStrategyFactory().create("hybrid", config, provider, vector_store)
        if not isinstance(strategy, HybridRetrievalStrategy):
            raise RuntimeError(f"Expected HybridRetrievalStrategy, got {type(strategy).__name__}.")
        cases = DatasetLoader().load(config.evaluation.dataset)
        rng = random.Random(args.seed)
        shuffled = list(cases)
        rng.shuffle(shuffled)
        train = shuffled[: args.train_size]
        validation = shuffled[args.train_size : args.train_size + args.validation_size]
        if not train or not validation:
            raise RuntimeError("Both train and validation splits must be non-empty.")

        context_started = perf_counter()
        if args.reuse_feature_cache and args.feature_cache and args.feature_cache.exists():
            feature_rows = _load_feature_cache(args.feature_cache)
            print(f"loaded feature cache: {args.feature_cache} rows={len(feature_rows)}", flush=True)
        else:
            contexts = _collect_contexts(strategy, train + validation, args.limit)
            feature_rows = _build_feature_rows(contexts)
            if args.feature_cache:
                _save_feature_cache(args.feature_cache, feature_rows)
                print(f"saved feature cache: {args.feature_cache} rows={len(feature_rows)}", flush=True)
        _attach_effective_weights(feature_rows, strategy)
        context_duration_ms = (perf_counter() - context_started) * 1000
        grid = _candidate_weights(args.grid_step)
        train_features = feature_rows[: len(train)]
        validation_features = feature_rows[len(train) :]
        train_rows = []
        for index, weights in enumerate(grid, start=1):
            train_rows.append(_score_profile(train_features, weights, args.limit))
            if index % 250 == 0:
                print(f"scored profiles: {index}/{len(grid)}", flush=True)
        ranked = sorted(
            train_rows,
            key=lambda row: (
                row["metrics"]["file_hit_rate@5"],
                row["metrics"][f"file_mrr@{args.limit}"],
                row["metrics"][f"file_hit_rate@{args.limit}"],
            ),
            reverse=True,
        )
        validation_rows = []
        for row in ranked[: args.top]:
            validation_rows.append(
                {
                    "weights": row["weights"],
                    "train": row["metrics"],
                    "validation": _score_profile(validation_features, row["weights"], args.limit)["metrics"],
                }
            )
        manual_weights = {field: getattr(config.hybrid_search, field) for field in WEIGHT_FIELDS}
        mlp_result = _train_and_score_mlp(
            train_features,
            validation_features,
            limit=args.limit,
            depth=args.mlp_depth,
            output_mode=args.mlp_output,
            hidden_size=args.mlp_hidden_size,
            epochs=args.mlp_epochs,
            learning_rate=args.mlp_learning_rate,
            seed=args.seed,
        )
        result = {
            "output": str(args.output),
            "config": str(args.config),
            "dataset": str(config.evaluation.dataset),
            "target": "rank by train file_hit_rate@5, then file_mrr@limit, validate on holdout",
            "split": {
                "seed": args.seed,
                "train_size": len(train),
                "validation_size": len(validation),
            },
            "limit": args.limit,
            "manual_h5": {
                "weights": manual_weights,
                "effective": "route-specific H3 weights from HybridQueryRouter",
                "train": _score_effective_profile(train_features, args.limit)["metrics"],
                "validation": _score_effective_profile(validation_features, args.limit)["metrics"],
            },
            "mlp": mlp_result,
            "top_profiles": validation_rows,
            "timing": {
                "context_collection_ms": context_duration_ms,
                "total_ms": (perf_counter() - started) * 1000,
                "profiles_tested": len(grid),
            },
        }
    finally:
        close_vector_store(vector_store)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(_summary(result), indent=2))
    return 0


def _collect_contexts(
    strategy: HybridRetrievalStrategy,
    cases: list[EvalCase],
    limit: int,
) -> list[tuple[EvalCase, HybridRankContext | None, list[SearchResult]]]:
    rows: list[tuple[EvalCase, HybridRankContext | None, list[SearchResult]]] = []
    for index, case in enumerate(cases, start=1):
        context = strategy.collect_rank_context(case.query, limit)
        fallback = context.vector_results[:limit] if context is not None else strategy.search(case.query, limit)
        rows.append((case, context, fallback))
        if index % 100 == 0:
            print(f"collected contexts: {index}/{len(cases)}", flush=True)
    return rows


def _build_feature_rows(
    rows: list[tuple[EvalCase, HybridRankContext | None, list[SearchResult]]],
) -> list[dict[str, Any]]:
    resolver = CodeItemIndexKindResolver()
    features = []
    for case, context, fallback in rows:
        if context is None:
            features.append(
                {
                    "case": case,
                    "fallback_files": _dedupe_files(result.item.path for result in fallback),
                    "candidates": [],
                    "effective_weights": {},
                    "preserve_vector_top": False,
                    "vector_top_path": None,
                }
            )
            continue
        vector_rank = {result.item.id: rank for rank, result in enumerate(context.vector_results, start=1)}
        vector_top_path = context.vector_results[0].item.path if context.vector_results else None
        vector_margin = 0.0
        if len(context.vector_results) > 1:
            vector_margin = context.vector_results[0].score - context.vector_results[1].score
        candidates = []
        for score in context.scores.values():
            kind = resolver.resolve(score.item)
            candidates.append(
                {
                    "id": score.item.id,
                    "path": score.item.path,
                    "kind_weight": context.config.item_kind_weights.get(kind, 1.0),
                    "vector": score.vector_score,
                    "lexical": score.lexical_score,
                    "path_score": score.path_score,
                    "symbol": score.symbol_score,
                    "symbol_match": score.symbol_match_score,
                    "graph": score.graph_score,
                    "file_vote": score.file_vote_score,
                    "vector_rank": vector_rank.get(score.item.id, 1_000_000),
                }
            )
        features.append(
            {
                "case": case,
                "fallback_files": [],
                "candidates": candidates,
                "effective_weights": {field: getattr(context.config, field) for field in WEIGHT_FIELDS},
                "preserve_vector_top": context.config.preserve_vector_top
                and bool(context.vector_results)
                and vector_margin >= context.config.vector_top_score_margin,
                "vector_top_path": vector_top_path,
            }
        )
    return features


def _attach_effective_weights(rows: list[dict[str, Any]], strategy: HybridRetrievalStrategy) -> None:
    for row in rows:
        if row.get("effective_weights"):
            continue
        case = row["case"]
        query_profile = strategy.analyzer.analyze(case.query)
        active_config = strategy.router.route(case.query, query_profile.terms, strategy.config)
        row["effective_weights"] = {field: getattr(active_config, field) for field in WEIGHT_FIELDS}


def _candidate_weights(step: str) -> list[dict[str, float]]:
    if step == "medium":
        vector_values = (0.32, 0.38, 0.44, 0.50, 0.56)
        lexical_values = (0.16, 0.22, 0.28, 0.34, 0.40)
        path_values = (0.06, 0.10, 0.14, 0.18, 0.22)
        symbol_values = (0.03, 0.06, 0.09, 0.12)
        graph_values = (0.0, 0.03, 0.06, 0.09, 0.12)
        file_vote_values = (0.0, 0.03, 0.06, 0.09, 0.12)
    else:
        vector_values = (0.30, 0.38, 0.46, 0.54)
        lexical_values = (0.18, 0.26, 0.34, 0.42)
        path_values = (0.08, 0.14, 0.20)
        symbol_values = (0.04, 0.08, 0.12)
        graph_values = (0.0, 0.04, 0.08)
        file_vote_values = (0.0, 0.04, 0.08)
    profiles: list[dict[str, float]] = []
    for vector, lexical, path, symbol, graph, file_vote in product(
        vector_values,
        lexical_values,
        path_values,
        symbol_values,
        graph_values,
        file_vote_values,
    ):
        symbol_match = symbol
        total = vector + lexical + path + symbol + symbol_match + graph + file_vote
        if total <= 0:
            continue
        profiles.append(
            {
                "vector_weight": vector / total,
                "lexical_weight": lexical / total,
                "path_weight": path / total,
                "symbol_weight": symbol / total,
                "symbol_match_weight": symbol_match / total,
                "graph_weight": graph / total,
                "file_vote_weight": file_vote / total,
            }
        )
    return profiles


def _score_profile(
    rows: list[dict[str, Any]],
    weights: dict[str, float],
    limit: int,
) -> dict[str, Any]:
    per_case = []
    for row in rows:
        case = row["case"]
        files = row["fallback_files"]
        if row["candidates"]:
            files = _rank_feature_row(row, weights, limit)
        per_case.append(_file_metrics(files, case.expected, limit))
    return {
        "weights": weights,
        "metrics": {
            "cases": len(per_case),
            "file_hit_rate@1": _mean(1.0 if row["hit_at_1"] else 0.0 for row in per_case),
            "file_hit_rate@3": _mean(1.0 if row["hit_at_3"] else 0.0 for row in per_case),
            "file_hit_rate@5": _mean(1.0 if row["hit_at_5"] else 0.0 for row in per_case),
            f"file_hit_rate@{limit}": _mean(1.0 if row["hit_at_limit"] else 0.0 for row in per_case),
            f"file_mrr@{limit}": _mean(row["mrr"] for row in per_case),
            f"file_recall@{limit}": _mean(row["recall"] for row in per_case),
            "file_precision@R": _mean(row["precision_at_r"] for row in per_case),
        },
    }


def _score_effective_profile(
    rows: list[dict[str, Any]],
    limit: int,
) -> dict[str, Any]:
    per_case = []
    for row in rows:
        case = row["case"]
        files = row["fallback_files"]
        if row["candidates"]:
            files = _rank_feature_row(row, row["effective_weights"], limit)
        per_case.append(_file_metrics(files, case.expected, limit))
    return {
        "weights": "route-specific",
        "metrics": {
            "cases": len(per_case),
            "file_hit_rate@1": _mean(1.0 if row["hit_at_1"] else 0.0 for row in per_case),
            "file_hit_rate@3": _mean(1.0 if row["hit_at_3"] else 0.0 for row in per_case),
            "file_hit_rate@5": _mean(1.0 if row["hit_at_5"] else 0.0 for row in per_case),
            f"file_hit_rate@{limit}": _mean(1.0 if row["hit_at_limit"] else 0.0 for row in per_case),
            f"file_mrr@{limit}": _mean(row["mrr"] for row in per_case),
            f"file_recall@{limit}": _mean(row["recall"] for row in per_case),
            "file_precision@R": _mean(row["precision_at_r"] for row in per_case),
        },
    }


def _train_and_score_mlp(
    train_rows: list[dict[str, Any]],
    validation_rows: list[dict[str, Any]],
    *,
    limit: int,
    depth: int,
    output_mode: str,
    hidden_size: int,
    epochs: int,
    learning_rate: float,
    seed: int,
) -> dict[str, Any]:
    started = perf_counter()
    train_x, train_y = _candidate_matrix(train_rows)
    if len(train_x) == 0 or len(set(train_y.reshape(-1).tolist())) < 2:
        return {
            "enabled": False,
            "reason": "not enough positive/negative candidates",
            "duration_ms": (perf_counter() - started) * 1000,
        }
    output_size = len(SCORING_FEATURE_KEYS) if output_mode == "weights" else 1
    model = _init_mlp(train_x.shape[1], depth, hidden_size, output_size, seed)
    pos_count = float(train_y.sum())
    neg_count = float(len(train_y) - pos_count)
    pos_weight = min(max(neg_count / max(pos_count, 1.0), 1.0), 30.0)
    for epoch in range(epochs):
        loss = _mlp_step(model, train_x, train_y, learning_rate, pos_weight, output_mode)
        if (epoch + 1) % 50 == 0:
            print(f"mlp epoch: {epoch + 1}/{epochs} loss={loss:.5f}", flush=True)
    return {
        "enabled": True,
        "depth": depth,
        "output_mode": output_mode,
        "hidden_size": hidden_size,
        "epochs": epochs,
        "learning_rate": learning_rate,
        "positive_candidates": int(pos_count),
        "negative_candidates": int(neg_count),
        "positive_weight": pos_weight,
        "train": _score_mlp_profile(train_rows, model, limit, output_mode)["metrics"],
        "validation": _score_mlp_profile(validation_rows, model, limit, output_mode)["metrics"],
        "duration_ms": (perf_counter() - started) * 1000,
    }


def _candidate_matrix(rows: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray]:
    x_rows = []
    y_rows = []
    for row in rows:
        case = row["case"]
        for candidate in row["candidates"]:
            x_rows.append([float(candidate[key]) for key in FEATURE_KEYS])
            y_rows.append(1.0 if _matches_any(candidate["path"], case.expected) else 0.0)
    return np.asarray(x_rows, dtype=np.float64), np.asarray(y_rows, dtype=np.float64).reshape(-1, 1)


def _init_mlp(
    input_size: int,
    depth: int,
    hidden_size: int,
    output_size: int,
    seed: int,
) -> list[dict[str, np.ndarray]]:
    rng = np.random.default_rng(seed)
    widths = [input_size, *([hidden_size] * depth), output_size]
    model = []
    for left, right in zip(widths, widths[1:]):
        scale = np.sqrt(2.0 / max(left, 1))
        model.append(
            {
                "w": rng.normal(0.0, scale, size=(left, right)),
                "b": np.zeros((1, right), dtype=np.float64),
            }
        )
    return model


def _mlp_step(
    model: list[dict[str, np.ndarray]],
    x: np.ndarray,
    y: np.ndarray,
    learning_rate: float,
    pos_weight: float,
    output_mode: str,
) -> float:
    activations = [x]
    pre_activations = []
    current = x
    for index, layer in enumerate(model):
        z = current @ layer["w"] + layer["b"]
        pre_activations.append(z)
        current = z if index == len(model) - 1 else np.maximum(z, 0.0)
        activations.append(current)

    logits = activations[-1]
    if output_mode == "weights":
        dynamic_weights = _softmax(logits)
        score = np.sum(dynamic_weights * x[:, : len(SCORING_FEATURE_KEYS)], axis=1, keepdims=True) * x[:, 7:8]
    else:
        score = logits
    predictions = np.clip(_sigmoid(score), 1e-7, 1 - 1e-7)
    weights = np.where(y > 0.5, pos_weight, 1.0)
    loss = -float(np.mean(weights * (y * np.log(predictions) + (1.0 - y) * np.log(1.0 - predictions))))
    grad_score = weights * (predictions - y) / max(len(y), 1)
    if output_mode == "weights":
        signal_grad = grad_score * x[:, : len(SCORING_FEATURE_KEYS)] * x[:, 7:8]
        weighted_grad_sum = np.sum(signal_grad * dynamic_weights, axis=1, keepdims=True)
        grad = dynamic_weights * (signal_grad - weighted_grad_sum)
    else:
        grad = grad_score

    for index in reversed(range(len(model))):
        if index < len(model) - 1:
            grad = grad * (pre_activations[index] > 0)
        prev = activations[index]
        grad_w = prev.T @ grad
        grad_b = grad.sum(axis=0, keepdims=True)
        if index > 0:
            next_grad = grad @ model[index]["w"].T
        else:
            next_grad = grad
        model[index]["w"] -= learning_rate * grad_w
        model[index]["b"] -= learning_rate * grad_b
        grad = next_grad
    return loss


def _sigmoid(values: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(values, -40.0, 40.0)))


def _softmax(values: np.ndarray) -> np.ndarray:
    shifted = values - np.max(values, axis=1, keepdims=True)
    exp = np.exp(np.clip(shifted, -40.0, 40.0))
    return exp / np.maximum(exp.sum(axis=1, keepdims=True), 1e-12)


def _score_mlp_profile(
    rows: list[dict[str, Any]],
    model: list[dict[str, np.ndarray]],
    limit: int,
    output_mode: str,
) -> dict[str, Any]:
    per_case = []
    for row in rows:
        files = row["fallback_files"]
        if row["candidates"]:
            files = _rank_mlp_feature_row(row, model, limit, output_mode)
        per_case.append(_file_metrics(files, row["case"].expected, limit))
    return {
        "metrics": {
            "cases": len(per_case),
            "file_hit_rate@1": _mean(1.0 if row["hit_at_1"] else 0.0 for row in per_case),
            "file_hit_rate@3": _mean(1.0 if row["hit_at_3"] else 0.0 for row in per_case),
            "file_hit_rate@5": _mean(1.0 if row["hit_at_5"] else 0.0 for row in per_case),
            f"file_hit_rate@{limit}": _mean(1.0 if row["hit_at_limit"] else 0.0 for row in per_case),
            f"file_mrr@{limit}": _mean(row["mrr"] for row in per_case),
            f"file_recall@{limit}": _mean(row["recall"] for row in per_case),
            "file_precision@R": _mean(row["precision_at_r"] for row in per_case),
        }
    }


def _rank_mlp_feature_row(
    row: dict[str, Any],
    model: list[dict[str, np.ndarray]],
    limit: int,
    output_mode: str,
) -> list[str]:
    matrix = np.asarray([[float(candidate[key]) for key in FEATURE_KEYS] for candidate in row["candidates"]])
    scores = _mlp_scores(model, matrix, output_mode).reshape(-1).tolist()
    ranked = sorted(
        zip(row["candidates"], scores),
        key=lambda pair: (pair[1], pair[0]["vector"], pair[0]["lexical"], pair[0]["path"]),
        reverse=True,
    )
    paths = _dedupe_files(candidate["path"] for candidate, _ in ranked)
    if row["preserve_vector_top"] and row["vector_top_path"] and paths[:1] != [row["vector_top_path"]]:
        paths = [row["vector_top_path"], *(path for path in paths if path != row["vector_top_path"])]
    return paths[:limit]


def _mlp_logits(model: list[dict[str, np.ndarray]], x: np.ndarray) -> np.ndarray:
    current = x
    for index, layer in enumerate(model):
        current = current @ layer["w"] + layer["b"]
        if index < len(model) - 1:
            current = np.maximum(current, 0.0)
    return current


def _mlp_scores(model: list[dict[str, np.ndarray]], x: np.ndarray, output_mode: str) -> np.ndarray:
    logits = _mlp_logits(model, x)
    if output_mode == "weights":
        dynamic_weights = _softmax(logits)
        return np.sum(dynamic_weights * x[:, : len(SCORING_FEATURE_KEYS)], axis=1, keepdims=True) * x[:, 7:8]
    return logits


def _rank_feature_row(row: dict[str, Any], weights: dict[str, float], limit: int) -> list[str]:
    ranked = sorted(
        row["candidates"],
        key=lambda candidate: (
            _candidate_total(candidate, weights),
            candidate["vector"],
            candidate["lexical"],
            candidate["path"],
        ),
        reverse=True,
    )
    paths = _dedupe_files(candidate["path"] for candidate in ranked)
    if row["preserve_vector_top"] and row["vector_top_path"] and paths[:1] != [row["vector_top_path"]]:
        paths = [row["vector_top_path"], *(path for path in paths if path != row["vector_top_path"])]
    return paths[:limit]


def _candidate_total(candidate: dict[str, Any], weights: dict[str, float]) -> float:
    return (
        candidate["vector"] * weights["vector_weight"]
        + candidate["lexical"] * weights["lexical_weight"]
        + candidate["path_score"] * weights["path_weight"]
        + candidate["symbol"] * weights["symbol_weight"]
        + candidate["symbol_match"] * weights["symbol_match_weight"]
        + candidate["graph"] * weights["graph_weight"]
        + candidate["file_vote"] * weights["file_vote_weight"]
    ) * candidate["kind_weight"]


def _file_metrics(files: list[str], expected: list[str], limit: int) -> dict[str, float | bool]:
    ranks = [rank for rank, path in enumerate(files, start=1) if _matches_any(path, expected)]
    expected_count = max(len(expected), 1)
    matched_expected_count = sum(1 for value in expected if any(_matches(path, value) for path in files))
    r = min(expected_count, limit)
    top_r = files[:r]
    return {
        "hit_at_1": bool(ranks and ranks[0] <= 1),
        "hit_at_3": bool(ranks and ranks[0] <= 3),
        "hit_at_5": bool(ranks and ranks[0] <= 5),
        "hit_at_limit": bool(ranks),
        "mrr": 1.0 / ranks[0] if ranks else 0.0,
        "recall": min(matched_expected_count / expected_count, 1.0),
        "precision_at_r": sum(1 for path in top_r if _matches_any(path, expected)) / max(r, 1),
    }


def _dedupe_files(paths: Any) -> list[str]:
    seen: set[str] = set()
    files: list[str] = []
    for path in paths:
        text = str(path)
        if text in seen:
            continue
        seen.add(text)
        files.append(text)
    return files


def _matches_any(path: str, expected: list[str]) -> bool:
    return any(_matches(path, value) for value in expected)


def _matches(path: str, expected: str) -> bool:
    normalized = expected.strip()
    return path == normalized or path.startswith(normalized.rstrip("/") + "/")


def _mean(values: Any) -> float:
    materialized = list(values)
    if not materialized:
        return 0.0
    return sum(materialized) / len(materialized)


def _save_feature_cache(path: Path, rows: list[dict[str, Any]]) -> None:
    payload = []
    for row in rows:
        case = row["case"]
        payload.append(
            {
                "case": {"id": case.id, "query": case.query, "expected": case.expected},
                "fallback_files": row["fallback_files"],
                "candidates": row["candidates"],
                "effective_weights": row.get("effective_weights") or {},
                "preserve_vector_top": row["preserve_vector_top"],
                "vector_top_path": row["vector_top_path"],
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _load_feature_cache(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for row in payload:
        case = row["case"]
        rows.append(
            {
                "case": EvalCase(id=str(case["id"]), query=str(case["query"]), expected=list(case["expected"])),
                "fallback_files": list(row.get("fallback_files") or []),
                "candidates": list(row.get("candidates") or []),
                "effective_weights": dict(row.get("effective_weights") or {}),
                "preserve_vector_top": bool(row.get("preserve_vector_top")),
                "vector_top_path": row.get("vector_top_path"),
            }
        )
    return rows


def _summary(result: dict[str, Any]) -> dict[str, Any]:
    top = result["top_profiles"][0] if result["top_profiles"] else {}
    return {
        "output": result.get("output"),
        "dataset": result["dataset"],
        "split": result["split"],
        "manual_h5_validation": result["manual_h5"]["validation"],
        "best_validation": top.get("validation"),
        "best_weights": top.get("weights"),
        "mlp_validation": result.get("mlp", {}).get("validation"),
        "profiles_tested": result["timing"]["profiles_tested"],
        "total_ms": result["timing"]["total_ms"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
