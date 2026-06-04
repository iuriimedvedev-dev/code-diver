from __future__ import annotations

import argparse
import json
import random
from dataclasses import replace
from itertools import product
from pathlib import Path
from time import perf_counter
from typing import Any

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


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate H5 hybrid retrieval weights on a train/validation split.")
    parser.add_argument("--config", type=Path, default=Path("configs/codesearchnet-mteb-python-h5-qwen-quality.yml"))
    parser.add_argument("--output", type=Path, default=Path(".code-diver/reports/h5-hybrid-weight-calibration.json"))
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--train-size", type=int, default=700)
    parser.add_argument("--validation-size", type=int, default=300)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--top", type=int, default=20)
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
        contexts = _collect_contexts(strategy, train + validation, args.limit)
        feature_rows = _build_feature_rows(contexts)
        context_duration_ms = (perf_counter() - context_started) * 1000
        grid = _candidate_weights()
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
                "train": _score_profile(train_features, manual_weights, args.limit)["metrics"],
                "validation": _score_profile(validation_features, manual_weights, args.limit)["metrics"],
            },
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
                "preserve_vector_top": context.config.preserve_vector_top
                and bool(context.vector_results)
                and vector_margin >= context.config.vector_top_score_margin,
                "vector_top_path": vector_top_path,
            }
        )
    return features


def _candidate_weights() -> list[dict[str, float]]:
    profiles: list[dict[str, float]] = []
    for vector, lexical, path, symbol, graph, file_vote in product(
        (0.30, 0.38, 0.46, 0.54),
        (0.18, 0.26, 0.34, 0.42),
        (0.08, 0.14, 0.20),
        (0.04, 0.08, 0.12),
        (0.0, 0.04, 0.08),
        (0.0, 0.04, 0.08),
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


def _summary(result: dict[str, Any]) -> dict[str, Any]:
    top = result["top_profiles"][0] if result["top_profiles"] else {}
    return {
        "output": result.get("output"),
        "dataset": result["dataset"],
        "split": result["split"],
        "manual_h5_validation": result["manual_h5"]["validation"],
        "best_validation": top.get("validation"),
        "best_weights": top.get("weights"),
        "profiles_tested": result["timing"]["profiles_tested"],
        "total_ms": result["timing"]["total_ms"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
