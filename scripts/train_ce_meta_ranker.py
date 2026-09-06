"""Train a LightGBM LambdaRank model on CE-stage meta features (H-91).

Input is the JSONL written by `code-diver evaluate --dump-ce-meta-features PATH`:
a header line with `feature_names`, then one object per (query, candidate) with
`query_id`, `label`, `features`.

The split is by query, never by row. LightGBM is the only backend (required).

Usage:
    train_ce_meta_ranker.py FEATURES_JSONL --out artifacts/ce_meta_ranker/ranker.json
                        [--test-fraction 0.2] [--seed 0] [--k 10]
                        [--test-features OTHER_JSONL] [--metrics-json PATH]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from code_diver.ranking.ce_meta_feature_row import CE_META_FEATURE_NAMES
from code_diver.ranking.ltr_query_split import LtrQuerySplitter

DEFAULT_K = 10
MANIFEST_VERSION = 1


class TrainCeMetaRankerError(RuntimeError):
    pass


@dataclass(slots=True)
class QueryGroup:
    query_id: str
    features: list[list[float]]
    labels: list[int]


def load_groups(path: Path) -> tuple[list[QueryGroup], tuple[str, ...]]:
    feature_names: tuple[str, ...] = ()
    by_query: dict[str, QueryGroup] = {}
    order: list[str] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise TrainCeMetaRankerError(f"{path}:{line_number} is not valid JSON: {exc}") from exc
            if "feature_names" in payload and "features" not in payload:
                feature_names = tuple(str(name) for name in payload["feature_names"])
                continue
            query_id = str(payload["query_id"])
            group = by_query.get(query_id)
            if group is None:
                group = QueryGroup(query_id=query_id, features=[], labels=[])
                by_query[query_id] = group
                order.append(query_id)
            group.features.append([float(value) for value in payload["features"]])
            group.labels.append(int(payload["label"]))
    if not by_query:
        raise TrainCeMetaRankerError(f"{path} contains no feature rows.")
    if feature_names and feature_names != CE_META_FEATURE_NAMES:
        raise TrainCeMetaRankerError(
            f"{path} was exported with a different feature list than this checkout defines. "
            "Re-export the features before training."
        )
    return [by_query[query_id] for query_id in order], feature_names or CE_META_FEATURE_NAMES


def ndcg_at_k(labels_in_rank_order: list[int], k: int) -> float:
    dcg = sum(label / math.log2(rank + 1) for rank, label in enumerate(labels_in_rank_order[:k], start=1))
    ideal_labels = sorted(labels_in_rank_order, reverse=True)[:k]
    ideal = sum(label / math.log2(rank + 1) for rank, label in enumerate(ideal_labels, start=1))
    return dcg / ideal if ideal else 0.0


def recall_at_k(labels_in_rank_order: list[int], k: int) -> float:
    relevant = sum(labels_in_rank_order)
    if relevant == 0:
        return 0.0
    return sum(labels_in_rank_order[:k]) / relevant


def evaluate_groups(groups: list[QueryGroup], score_rows: Any, k: int) -> dict[str, float]:
    """Mean NDCG@k and recall@k over the groups, plus the same for the base order.

    The base numbers come from the dump's own row order, which is the CE + hub_prior
    ranking. Reporting both shows whether the model beat the heuristic it replaces.
    """
    if not groups:
        return {}
    model_ndcg: list[float] = []
    model_recall: list[float] = []
    base_ndcg: list[float] = []
    base_recall: list[float] = []
    for group in groups:
        scores = score_rows(group.features)
        ordered = [
            label
            for _, label in sorted(
                zip(scores, group.labels, strict=True),
                key=lambda entry: entry[0],
                reverse=True,
            )
        ]
        model_ndcg.append(ndcg_at_k(ordered, k))
        model_recall.append(recall_at_k(ordered, k))
        base_ndcg.append(ndcg_at_k(group.labels, k))
        base_recall.append(recall_at_k(group.labels, k))
    return {
        f"ndcg@{k}": sum(model_ndcg) / len(model_ndcg),
        f"recall@{k}": sum(model_recall) / len(model_recall),
        f"base_ndcg@{k}": sum(base_ndcg) / len(base_ndcg),
        f"base_recall@{k}": sum(base_recall) / len(base_recall),
        "queries": float(len(groups)),
    }


def train_lightgbm(groups: list[QueryGroup], seed: int, out_dir: Path) -> tuple[str, str, Any]:
    import lightgbm

    features = [row for group in groups for row in group.features]
    labels = [label for group in groups for label in group.labels]
    group_sizes = [len(group.labels) for group in groups]
    ranker = lightgbm.LGBMRanker(
        objective="lambdarank",
        n_estimators=200,
        learning_rate=0.05,
        num_leaves=15,
        min_child_samples=10,
        random_state=seed,
        verbose=-1,
    )
    ranker.fit(features, labels, group=group_sizes)
    model_file = "ce_meta_ranker.lgb.txt"
    ranker.booster_.save_model(str(out_dir / model_file))
    return "lightgbm_txt", model_file, ranker


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("features", type=Path, help="JSONL written by `evaluate --dump-ce-meta-features`.")
    parser.add_argument("--out", type=Path, required=True, help="Model manifest JSON to write.")
    parser.add_argument("--test-fraction", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument(
        "--test-features",
        type=Path,
        default=None,
        help="Score this dump as an additional, fully held-out test set (e.g. WHERE-78).",
    )
    parser.add_argument("--metrics-json", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    groups, feature_names = load_groups(args.features)
    split = LtrQuerySplitter().split(
        (group.query_id for group in groups),
        test_fraction=args.test_fraction,
        seed=args.seed,
    )
    if split.overlap():
        raise TrainCeMetaRankerError("train/test split produced overlapping queries.")
    train_ids = set(split.train_query_ids)
    train_groups = [group for group in groups if group.query_id in train_ids]
    test_groups = [group for group in groups if group.query_id not in train_ids]
    if not train_groups or not test_groups:
        raise TrainCeMetaRankerError(
            f"split left {len(train_groups)} train and {len(test_groups)} test queries; "
            "the dump is too small to train on honestly."
        )

    out_dir = args.out.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    model_format, model_file, estimator = train_lightgbm(train_groups, args.seed, out_dir)

    def score_rows(rows: list[list[float]]) -> list[float]:
        return [float(value) for value in estimator.predict(rows)]

    metrics: dict[str, Any] = {
        "backend": "lightgbm",
        "features": args.features.name,
        "train_queries": len(train_groups),
        "test_queries": len(test_groups),
        "train": evaluate_groups(train_groups, score_rows, args.k),
        "test": evaluate_groups(test_groups, score_rows, args.k),
    }
    if args.test_features is not None:
        holdout_groups, _ = load_groups(args.test_features)
        metrics["holdout"] = {
            "features": args.test_features.name,
            **evaluate_groups(holdout_groups, score_rows, args.k),
        }

    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "format": model_format,
        "model_file": model_file,
        "feature_names": list(feature_names),
        "seed": args.seed,
        "test_fraction": args.test_fraction,
        "metrics": metrics,
        "type": "ce_meta_ranker",
    }
    args.out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    if args.metrics_json is not None:
        args.metrics_json.parent.mkdir(parents=True, exist_ok=True)
        args.metrics_json.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except TrainCeMetaRankerError as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)