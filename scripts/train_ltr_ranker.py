"""Train a learning-to-rank model on features exported from a real retrieval run (H-80).

Why this exists: the final file ordering is decided by a hand-tuned weighted sum of seven
per-candidate signals. Those weights were set by sweeping one factor at a time against the
same small WHERE set, which is exactly the regime where hand-tuning stops being tuning and
starts being memorisation. A ranker fitted to labelled data at least makes the fitting
explicit, measurable, and splittable into train and test.

Input is the JSONL written by `code-diver evaluate --dump-features PATH`: a header line
holding the feature-name manifest, then one object per (query, candidate) with `query_id`,
`label` and `features`.

THE SPLIT IS BY QUERY, NEVER BY ROW. Candidates of one query are perfectly correlated with
each other, so a row-level split leaks the answer into the training half and the held-out
score becomes a description of the leak instead of the model.

Backends, in preference order:
  - LightGBM `LGBMRanker` with the `lambdarank` objective: the right tool, list-aware,
    optimises NDCG directly. Optional dependency (`uv sync --extra ltr`).
  - scikit-learn `GradientBoostingRegressor` on the 0/1 labels: dependency-light fallback
    that is POINTWISE. It cannot see a query's candidates as a list, so treat its numbers
    as a floor, not as what a proper lambdarank would do.

Usage:
    train_ltr_ranker.py FEATURES_JSONL --out artifacts/ltr/ranker.json
                        [--test-fraction 0.5] [--seed 0] [--backend auto|lightgbm|sklearn]
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

from code_diver.ranking.ltr_feature_row import LTR_FEATURE_NAMES
from code_diver.ranking.ltr_query_split import LtrQuerySplitter
from code_diver.ranking.ltr_ranker_model import (
    FORMAT_LIGHTGBM_TXT,
    FORMAT_SKLEARN_JOBLIB,
    LTR_MANIFEST_VERSION,
)

DEFAULT_K = 10


class TrainLtrRankerError(RuntimeError):
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
                raise TrainLtrRankerError(f"{path}:{line_number} is not valid JSON: {exc}") from exc
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
        raise TrainLtrRankerError(f"{path} contains no feature rows.")
    if feature_names and feature_names != LTR_FEATURE_NAMES:
        raise TrainLtrRankerError(
            f"{path} was exported with a different feature list than this checkout defines. "
            "Re-export the features before training."
        )
    return [by_query[query_id] for query_id in order], feature_names or LTR_FEATURE_NAMES


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
    """Mean NDCG@k and recall@k over the groups, plus the same for the exported base order.

    The base numbers come from the dump's own row order, which is the hand-tuned fused
    ranking. Reporting both is the only way to see whether the model did anything: a
    learned NDCG in isolation says nothing about whether it beat the sum it replaces.
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
    model_file = "ranker.lgb.txt"
    ranker.booster_.save_model(str(out_dir / model_file))
    return FORMAT_LIGHTGBM_TXT, model_file, ranker


def train_sklearn(groups: list[QueryGroup], seed: int, out_dir: Path) -> tuple[str, str, Any]:
    import joblib
    from sklearn.ensemble import GradientBoostingRegressor

    features = [row for group in groups for row in group.features]
    labels = [float(label) for group in groups for label in group.labels]
    estimator = GradientBoostingRegressor(
        n_estimators=200,
        learning_rate=0.05,
        max_depth=3,
        random_state=seed,
    )
    estimator.fit(features, labels)
    model_file = "ranker.joblib"
    joblib.dump(estimator, out_dir / model_file)
    return FORMAT_SKLEARN_JOBLIB, model_file, estimator


def select_backend(requested: str) -> str:
    if requested != "auto":
        return requested
    try:
        import lightgbm  # noqa: F401
    except ImportError:
        return "sklearn"
    return "lightgbm"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("features", type=Path, help="JSONL written by `evaluate --dump-features`.")
    parser.add_argument("--out", type=Path, required=True, help="Model manifest JSON to write.")
    parser.add_argument("--test-fraction", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--backend", choices=("auto", "lightgbm", "sklearn"), default="auto")
    parser.add_argument(
        "--test-features",
        type=Path,
        default=None,
        help="Score this dump as an additional, fully held-out test set (e.g. the human WHERE queries).",
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
        raise TrainLtrRankerError("train/test split produced overlapping queries.")
    train_ids = set(split.train_query_ids)
    train_groups = [group for group in groups if group.query_id in train_ids]
    test_groups = [group for group in groups if group.query_id not in train_ids]
    if not train_groups or not test_groups:
        raise TrainLtrRankerError(
            f"split left {len(train_groups)} train and {len(test_groups)} test queries; "
            "the dump is too small to train on honestly."
        )

    out_dir = args.out.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    backend = select_backend(args.backend)
    trainer = train_lightgbm if backend == "lightgbm" else train_sklearn
    model_format, model_file, estimator = trainer(train_groups, args.seed, out_dir)

    def score_rows(rows: list[list[float]]) -> list[float]:
        return [float(value) for value in estimator.predict(rows)]

    metrics: dict[str, Any] = {
        "backend": backend,
        "pointwise_fallback": backend == "sklearn",
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
        "manifest_version": LTR_MANIFEST_VERSION,
        "format": model_format,
        "model_file": model_file,
        "feature_names": list(feature_names),
        "seed": args.seed,
        "test_fraction": args.test_fraction,
        "metrics": metrics,
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
    except TrainLtrRankerError as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
