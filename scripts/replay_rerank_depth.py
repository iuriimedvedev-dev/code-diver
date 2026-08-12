"""Measure POST-rerank file recall for a grid of (rerank pool depth, context cut) offline.

Why this exists, and why it is not `replay_pool_recall.py`: that script deliberately peels
the rerank stage off to measure the raw candidate pool, which answers "could the right file
ever be found" but not "does the reranker keep it". The answer pipeline's primary metric
`citation_expected_recall` is bounded above by the recall of the *reranked* top-`limit`
list, and nothing measured that quantity at any depth other than the one shipped.

The gap matters. On the h29 champion the raw pool at depth 34 holds 0.859 of the expected
files while the reranked top-10 delivers 0.805 to the context builder, so two separate
losses are stacked -- files the pool never had, and files the rerank cut discarded -- and
they call for opposite fixes. This script separates them by replaying the real probe
queries (no planner call, no answer generation) and then running the REAL
`AnswerCandidateCrossEncoderReranker` over the merged pool at several depths.

Fidelity notes:
- The probe fan-out is re-run per pool depth with `query_limit = max(limit, depth)`, exactly
  as `AnswerEvaluator._retrieve` computes it. Replaying once at the deepest limit and
  slicing would be cheaper but wrong: a deeper per-probe fetch changes which candidates
  reach the merge and therefore the top of the merged order.
- The reranker is constructed from the config's own `cross_encoder_rerank` block with only
  `candidate_limit` overridden, so `max_document_chars`, `preserve_top_candidate`, and the
  score-margin rules are whatever the arm actually ships.
- The rerank query is `case.question`, not a probe query -- again matching `_retrieve`.

Usage:
    replay_rerank_depth.py REPORT_JSON --config CONFIG_YML
                           [--depths 34,60,80] [--cuts 10,14,20] [--cases N]
                           [--json-out PATH]
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
from code_diver.cli import close_vector_store
from code_diver.config import AppConfig
from code_diver.reranking import RerankProviderFactory

sys.path.insert(0, str(Path(__file__).resolve().parent))

from replay_pool_recall import (  # noqa: E402
    ReplayPoolRecallError,
    build_probe_strategy,
    extract_probe_queries,
    load_config,
    load_report,
    normalize_path,
)

DEFAULT_DEPTHS: tuple[int, ...] = (34, 60, 80)
DEFAULT_CUTS: tuple[int, ...] = (10, 14, 20)
DEFAULT_PROBE_WORKERS = 4


@dataclass(slots=True, frozen=True)
class DepthCaseRecord:
    case_id: str
    expected_paths: tuple[str, ...]
    pool_paths: tuple[str, ...]
    reranked_paths: tuple[str, ...]
    retrieval_seconds: float
    rerank_seconds: float


def micro_recall(records: list[DepthCaseRecord], k: int, attribute: str) -> float:
    total_expected = 0
    total_hit = 0
    for record in records:
        window = frozenset(getattr(record, attribute)[:k])
        total_expected += len(record.expected_paths)
        total_hit += sum(1 for path in record.expected_paths if path in window)
    return total_hit / total_expected if total_expected else 0.0


def bundle_complete(records: list[DepthCaseRecord], k: int, attribute: str) -> float:
    eligible = [record for record in records if record.expected_paths]
    if not eligible:
        return 0.0
    hits = sum(
        1
        for record in eligible
        if frozenset(record.expected_paths) <= frozenset(getattr(record, attribute)[:k])
    )
    return hits / len(eligible)


def make_reranker(config: AppConfig, depth: int) -> AnswerCandidateCrossEncoderReranker:
    rerank_config = replace(config.cross_encoder_rerank, candidate_limit=depth)
    return AnswerCandidateCrossEncoderReranker(
        RerankProviderFactory().create(rerank_config), rerank_config
    )


def replay_depth(
    probe_strategy: Any,
    reranker: AnswerCandidateCrossEncoderReranker,
    rows: list[dict[str, Any]],
    depth: int,
    limit: int,
    max_cut: int,
    probe_workers: int,
) -> list[DepthCaseRecord]:
    query_limit = max(limit, depth)
    records: list[DepthCaseRecord] = []
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
        retrieval_seconds = perf_counter() - started
        started = perf_counter()
        # `max_cut`, not `limit`: one rerank call scores every cut we want. This assumes the
        # provider scores all documents and truncates, so the top-10 of a limit-20 call is
        # the top-10 of a limit-10 call. That is an assumption about the provider, not a
        # guarantee of this interface -- verify it with a small run at --cuts 10 before
        # trusting a grid, and go back to one call per cut if it ever fails.
        reranked, payload = reranker.rerank(question, merged, max_cut)
        rerank_seconds = perf_counter() - started
        if payload.get("error"):
            raise ReplayPoolRecallError(case_id, f"rerank failed at depth {depth}: {payload['error']}")
        records.append(
            DepthCaseRecord(
                case_id=case_id,
                expected_paths=tuple(expected),
                pool_paths=tuple(normalize_path(r.item.path) for r in merged[:depth]),
                reranked_paths=tuple(normalize_path(r.item.path) for r in reranked),
                retrieval_seconds=retrieval_seconds,
                rerank_seconds=rerank_seconds,
            )
        )
        print(
            f"  depth={depth} {len(records):>3}/{len(rows)} {case_id}",
            file=sys.stderr,
            flush=True,
        )
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("report", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--depths", default=",".join(str(d) for d in DEFAULT_DEPTHS))
    parser.add_argument("--cuts", default=",".join(str(c) for c in DEFAULT_CUTS))
    parser.add_argument("--cases", type=int, default=None)
    parser.add_argument("--probe-workers", type=int, default=DEFAULT_PROBE_WORKERS)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()

    if args.json_out is not None and args.json_out.exists():
        raise SystemExit(f"refusing to overwrite existing {args.json_out}")

    depths = sorted({int(value) for value in args.depths.split(",") if value.strip()})
    cuts = sorted({int(value) for value in args.cuts.split(",") if value.strip()})
    max_cut = max(cuts)

    report = load_report(args.report)
    rows = [row for row in report["results"] if row.get("query_plan") and row.get("expected_paths")]
    if args.cases:
        rows = rows[: args.cases]
    if not rows:
        raise SystemExit(f"{args.report}: no rows with both query_plan and expected_paths")

    config = load_config(args.config)
    limit = int(config.evaluation.limit)
    probe_strategy, configured_depth, vector_store = build_probe_strategy(config)

    output: dict[str, Any] = {
        "report": str(args.report),
        "config": str(args.config),
        "cases": len(rows),
        "shipped_depth": configured_depth,
        "cuts": cuts,
        "depths": {},
    }
    try:
        for depth in depths:
            reranker = make_reranker(config, depth)
            records = replay_depth(
                probe_strategy, reranker, rows, depth, limit, max_cut, args.probe_workers
            )
            output["depths"][str(depth)] = {
                "pool_recall": micro_recall(records, depth, "pool_paths"),
                "pool_bundle_complete": bundle_complete(records, depth, "pool_paths"),
                "reranked": {
                    str(cut): {
                        "recall": micro_recall(records, cut, "reranked_paths"),
                        "bundle_complete": bundle_complete(records, cut, "reranked_paths"),
                    }
                    for cut in cuts
                },
                "mean_retrieval_seconds": sum(r.retrieval_seconds for r in records) / len(records),
                "mean_rerank_seconds": sum(r.rerank_seconds for r in records) / len(records),
                "per_case": [
                    {
                        "case_id": r.case_id,
                        "expected": list(r.expected_paths),
                        "pool": list(r.pool_paths),
                        "reranked": list(r.reranked_paths),
                        "missing_from_pool": [p for p in r.expected_paths if p not in r.pool_paths],
                    }
                    for r in records
                ],
            }
            print_depth(depth, output["depths"][str(depth)], cuts)
    finally:
        close_vector_store(vector_store)

    if args.json_out is not None:
        args.json_out.write_text(json.dumps(output, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json_out}")
    return 0


def print_depth(depth: int, block: dict[str, Any], cuts: list[int]) -> None:
    print(f"\npool depth {depth}")
    print(f"  pool_recall            {block['pool_recall']:.3f}   bundle {block['pool_bundle_complete']:.3f}")
    for cut in cuts:
        entry = block["reranked"][str(cut)]
        print(f"  reranked recall@{cut:<3}   {entry['recall']:.3f}   bundle {entry['bundle_complete']:.3f}")
    print(
        f"  s/case retrieval {block['mean_retrieval_seconds']:.2f}   rerank {block['mean_rerank_seconds']:.2f}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
