"""Sweep the `graph_file_search` fusion weights and seed limits offline against pool recall.

Why this exists: the answer pipeline's largest single loss is the candidate pool. At the
shipped rerank depth of 34 the pool holds 0.883 of the expected files, so 0.117 of the
primary is gone before the reranker is even called -- more than twice the generation loss
and six times the rerank-cut loss. That pool is produced by seven numbers in the
`graph_file_search` block, and Finding 22 swept exactly one of them (`graph_weight`). The
other six have never been measured at all; they are simply the values the config was born
with.

This script measures them. It replays the REAL probe queries persisted in an
`evaluate-answers` report (no planner call, no generation, no judge) through the REAL
`graph_file` strategy, rebuilding that strategy once per grid point with only the swept
fields overridden. Everything else -- embedding provider, vector store, graph, merge order --
is shared across grid points, so a difference between two rows is the weights and nothing
else.

Fidelity notes:
- `merge_query_results` is imported from the pipeline, not reimplemented, so the merged
  order cannot drift from what `AnswerEvaluator._retrieve` produces.
- Recall is reported MACRO (mean of per-case recall) because that is what the pipeline's
  report metrics use. Micro is printed alongside it only to keep the two from being
  confused again; do not compare a macro number here to a micro number anywhere else.
- Pool recall at depth k is a CEILING on the post-rerank recall that actually feeds the
  context builder, not a prediction of it. Finding 51 showed the two move differently --
  deeper pools raised the ceiling while *lowering* post-rerank recall at a narrow cut. Use
  `--rerank-cut` to measure the real thing on the finalists; screening on the ceiling alone
  is cheap but can rank two settings in the wrong order.
- The probe fan-out uses `query_limit = max(limit, depth)` exactly as `_retrieve` computes
  it, so a grid point's pool is built the same way the live arm's would be.

Usage:
    replay_weight_grid.py REPORT_JSON --config CONFIG_YML
                          [--depth 34] [--k 10,14,34] [--cases N]
                          [--grid-json PATH] [--rerank-cut N] [--json-out PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from time import perf_counter
from typing import Any

from code_diver.answering.answer_candidate_cross_encoder_reranker import (
    AnswerCandidateCrossEncoderReranker,
)
from code_diver.answering.answer_query_merge import merge_query_results
from code_diver.cli import (
    close_vector_store,
    make_embedding_provider,
    make_retrieval_strategy,
    make_vector_store,
)
from code_diver.config import AppConfig
from code_diver.reranking import RerankProviderFactory

sys.path.insert(0, str(Path(__file__).resolve().parent))

from replay_pool_recall import (  # noqa: E402
    ReplayPoolRecallError,
    extract_probe_queries,
    load_config,
    load_report,
    normalize_path,
    unwrap_probe_strategy,
)

DEFAULT_DEPTH = 34
DEFAULT_K_VALUES: tuple[int, ...] = (10, 14, 34)
DEFAULT_PROBE_WORKERS = 4

# One-at-a-time around the shipped champion. OAT rather than a full factorial because a
# 4-factor 3-level grid is 81 points at ~2 min each, and nothing yet says these factors
# interact -- the point of this pass is to find which knobs move the pool AT ALL. Whatever
# moves it gets a proper 2-D grid afterwards, where interaction can be tested on the two or
# three factors that earned it.
#
# `graph_weight` is deliberately absent: Finding 22 swept it and found 0.45 sitting on a
# cliff edge, so moving it here would confound every row with a known-sharp effect.
DEFAULT_GRID: tuple[dict[str, Any], ...] = (
    {"name": "champion"},
    {"name": "vector-0.15", "vector_weight": 0.15},
    {"name": "vector-0.35", "vector_weight": 0.35},
    {"name": "lexical-0.15", "lexical_weight": 0.15},
    {"name": "lexical-0.35", "lexical_weight": 0.35},
    {"name": "path-0.10", "path_weight": 0.10},
    {"name": "path-0.30", "path_weight": 0.30},
    {"name": "symbol-0.05", "symbol_weight": 0.05},
    {"name": "symbol-0.20", "symbol_weight": 0.20},
    {"name": "seed-100", "seed_limit": 100},
    {"name": "seed-200", "seed_limit": 200},
    {"name": "lexseed-200", "lexical_seed_limit": 200},
    {"name": "lexseed-400", "lexical_seed_limit": 400},
)

SWEEPABLE_FIELDS = frozenset(
    {
        "seed_limit",
        "lexical_seed_limit",
        "vector_weight",
        "lexical_weight",
        "path_weight",
        "symbol_weight",
        "graph_weight",
        "depth",
        "neighbor_limit",
        "frontier_limit",
        "decay",
        "min_token_length",
    }
)


@dataclass(slots=True, frozen=True)
class GridCaseRecord:
    case_id: str
    expected_paths: tuple[str, ...]
    pool_paths: tuple[str, ...]
    reranked_paths: tuple[str, ...]
    seconds: float


def macro_recall(records: list[GridCaseRecord], k: int, attribute: str) -> float:
    eligible = [record for record in records if record.expected_paths]
    if not eligible:
        return 0.0
    total = 0.0
    for record in eligible:
        window = frozenset(getattr(record, attribute)[:k])
        hits = sum(1 for path in record.expected_paths if path in window)
        total += hits / len(record.expected_paths)
    return total / len(eligible)


def micro_recall(records: list[GridCaseRecord], k: int, attribute: str) -> float:
    expected = 0
    hit = 0
    for record in records:
        window = frozenset(getattr(record, attribute)[:k])
        expected += len(record.expected_paths)
        hit += sum(1 for path in record.expected_paths if path in window)
    return hit / expected if expected else 0.0


def bundle_complete(records: list[GridCaseRecord], k: int, attribute: str) -> float:
    eligible = [record for record in records if record.expected_paths]
    if not eligible:
        return 0.0
    hits = sum(
        1
        for record in eligible
        if frozenset(record.expected_paths) <= frozenset(getattr(record, attribute)[:k])
    )
    return hits / len(eligible)


def apply_point(config: AppConfig, point: dict[str, Any]) -> AppConfig:
    overrides = {key: value for key, value in point.items() if key != "name"}
    unknown = set(overrides) - SWEEPABLE_FIELDS
    if unknown:
        raise SystemExit(f"grid point {point.get('name')!r}: unknown field(s) {sorted(unknown)}")
    return replace(config, graph_file_search=replace(config.graph_file_search, **overrides))


def build_strategy(config: AppConfig, provider: Any, vector_store: Any) -> Any:
    # Peel the final rerank wrapper off for the same reason `replay_pool_recall` does: the
    # real pipeline reranks the merged pool ONCE, not once per probe query.
    strategy = make_retrieval_strategy(config, provider, vector_store)
    probe_strategy, _ = unwrap_probe_strategy(strategy)
    return probe_strategy


def make_reranker(config: AppConfig, depth: int) -> AnswerCandidateCrossEncoderReranker:
    rerank_config = replace(config.cross_encoder_rerank, candidate_limit=depth)
    return AnswerCandidateCrossEncoderReranker(
        RerankProviderFactory().create(rerank_config), rerank_config
    )


def replay_point(
    probe_strategy: Any,
    reranker: AnswerCandidateCrossEncoderReranker | None,
    rows: list[dict[str, Any]],
    depth: int,
    limit: int,
    rerank_cut: int,
    probe_workers: int,
    label: str,
) -> list[GridCaseRecord]:
    query_limit = max(limit, depth)
    records: list[GridCaseRecord] = []
    for row in rows:
        case_id = str(row.get("case_id") or "")
        question = str(row.get("question") or "")
        expected = [normalize_path(path) for path in row.get("expected_paths") or []]
        queries = extract_probe_queries(row.get("query_plan") or {}, case_id)
        started = perf_counter()
        workers = max(1, min(probe_workers, len(queries)))
        if workers == 1:
            result_sets = [probe_strategy.search(query, query_limit) for query in queries]
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [executor.submit(probe_strategy.search, query, query_limit) for query in queries]
                result_sets = [future.result() for future in futures]
        merged = merge_query_results(result_sets, query_limit)
        reranked_paths: tuple[str, ...] = ()
        if reranker is not None:
            reranked, payload = reranker.rerank(question, merged, rerank_cut)
            if payload.get("error"):
                raise ReplayPoolRecallError(case_id, f"rerank failed at {label}: {payload['error']}")
            reranked_paths = tuple(normalize_path(r.item.path) for r in reranked)
        records.append(
            GridCaseRecord(
                case_id=case_id,
                expected_paths=tuple(expected),
                pool_paths=tuple(normalize_path(r.item.path) for r in merged[:depth]),
                reranked_paths=reranked_paths,
                seconds=perf_counter() - started,
            )
        )
        print(f"  {label} {len(records):>3}/{len(rows)} {case_id}", file=sys.stderr, flush=True)
    return records


def summarize(records: list[GridCaseRecord], k_values: list[int], depth: int, rerank_cut: int | None) -> dict[str, Any]:
    block: dict[str, Any] = {
        "pool": {
            str(k): {
                "macro_recall": macro_recall(records, k, "pool_paths"),
                "micro_recall": micro_recall(records, k, "pool_paths"),
                "bundle_complete": bundle_complete(records, k, "pool_paths"),
            }
            for k in k_values
            if k <= depth
        },
        "mean_seconds": sum(r.seconds for r in records) / len(records),
    }
    if rerank_cut is not None:
        block["reranked"] = {
            str(rerank_cut): {
                "macro_recall": macro_recall(records, rerank_cut, "reranked_paths"),
                "micro_recall": micro_recall(records, rerank_cut, "reranked_paths"),
                "bundle_complete": bundle_complete(records, rerank_cut, "reranked_paths"),
            }
        }
    return block


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("report", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    parser.add_argument("--k", default=",".join(str(k) for k in DEFAULT_K_VALUES))
    parser.add_argument("--cases", type=int, default=None)
    parser.add_argument("--grid-json", type=Path, default=None, help="JSON list of grid points")
    parser.add_argument("--only", default=None, help="comma-separated grid point names to run")
    parser.add_argument("--rerank-cut", type=int, default=None, help="also measure post-rerank recall at this cut")
    parser.add_argument("--probe-workers", type=int, default=DEFAULT_PROBE_WORKERS)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()

    if args.json_out is not None and args.json_out.exists():
        raise SystemExit(f"refusing to overwrite existing {args.json_out}")

    k_values = sorted({int(v) for v in args.k.split(",") if v.strip()})
    grid: tuple[dict[str, Any], ...]
    if args.grid_json is not None:
        grid = tuple(json.loads(args.grid_json.read_text(encoding="utf-8")))
    else:
        grid = DEFAULT_GRID
    if args.only:
        wanted = {name.strip() for name in args.only.split(",") if name.strip()}
        grid = tuple(point for point in grid if point.get("name") in wanted)
        missing = wanted - {point.get("name") for point in grid}
        if missing:
            raise SystemExit(f"--only names not in grid: {sorted(missing)}")
    if not grid:
        raise SystemExit("empty grid")

    report = load_report(args.report)
    rows = [row for row in report["results"] if row.get("query_plan") and row.get("expected_paths")]
    if args.cases:
        rows = rows[: args.cases]
    if not rows:
        raise SystemExit(f"{args.report}: no rows with both query_plan and expected_paths")

    base_config = load_config(args.config)
    limit = int(base_config.evaluation.limit)

    vector_store = make_vector_store(base_config, progress=False)
    if not vector_store.exists():
        raise SystemExit(
            f"No index found for {base_config.storage.qdrant.collection!r}. "
            "Build it first (this script never triggers indexing)."
        )
    provider = make_embedding_provider(base_config, vector_store.metadata())

    output: dict[str, Any] = {
        "report": str(args.report),
        "config": str(args.config),
        "cases": len(rows),
        "depth": args.depth,
        "rerank_cut": args.rerank_cut,
        "baseline_weights": {
            field: getattr(base_config.graph_file_search, field)
            for field in sorted(SWEEPABLE_FIELDS)
        },
        "points": {},
    }
    try:
        for point in grid:
            name = str(point.get("name") or "unnamed")
            config = apply_point(base_config, point)
            probe_strategy = build_strategy(config, provider, vector_store)
            reranker = make_reranker(config, args.depth) if args.rerank_cut else None
            records = replay_point(
                probe_strategy,
                reranker,
                rows,
                args.depth,
                limit,
                args.rerank_cut or 0,
                args.probe_workers,
                name,
            )
            block = summarize(records, k_values, args.depth, args.rerank_cut)
            block["overrides"] = {k: v for k, v in point.items() if k != "name"}
            output["points"][name] = block
            print_point(name, block, k_values, args.depth, args.rerank_cut)
    finally:
        close_vector_store(vector_store)

    if args.json_out is not None:
        args.json_out.write_text(json.dumps(output, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json_out}")
    return 0


def print_point(
    name: str, block: dict[str, Any], k_values: list[int], depth: int, rerank_cut: int | None
) -> None:
    print(f"\n{name}  {block['overrides'] or '(baseline)'}")
    for k in k_values:
        if k > depth:
            continue
        entry = block["pool"][str(k)]
        print(
            f"  pool@{k:<3} macro {entry['macro_recall']:.4f}  micro {entry['micro_recall']:.4f}"
            f"  bundle {entry['bundle_complete']:.3f}"
        )
    if rerank_cut is not None:
        entry = block["reranked"][str(rerank_cut)]
        print(
            f"  rerank@{rerank_cut:<2} macro {entry['macro_recall']:.4f}  micro {entry['micro_recall']:.4f}"
            f"  bundle {entry['bundle_complete']:.3f}"
        )
    print(f"  s/case {block['mean_seconds']:.2f}")


if __name__ == "__main__":
    raise SystemExit(main())
