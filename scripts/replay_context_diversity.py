"""Test diversity-constrained selection of the reranked context window, offline.

Why this exists: Finding 53 found that widening the rerank cut from 10 to 14 raised retrieval
(`candidate_file_recall` 0.805 -> 0.865) but converted only two thirds of that into primary,
because five cases cited FEWER expected files while being shown strictly more. The H33
diagnosis identified the mechanism: a cross-encoder scores same-directory files alike, so the
four extra files at cut 14 are usually near-duplicate siblings of files already in the top 10,
and the generator spends a roughly fixed 4-6 citation budget on cluster-internal consistency
while dropping the lone cross-cluster file that was the answer. `where-generated-code-service`
cited all six `scaffolding/generators/*` files and dropped `codegen/service.py`, its only
expected path.

What this script measures, and what it CANNOT measure: it reranks each case's pool once to a
deep ordered list, then applies several selection policies to pick the context window from that
ordering, and reports recall / bundle-completeness / directory spread for each policy. That is
a RETRIEVAL measurement. Whether breaking up the clusters actually makes the generator cite
better is a GENERATION question and needs a live arm -- no offline replay can answer it. The
purpose here is to kill the idea cheaply if diversity costs recall, and to size the live arm if
it does not.

Fidelity notes:
- One rerank call per case at `--pool` depth, then every policy is evaluated against that same
  ordering for free. This relies on the prefix-stability property validated in Finding 51 (the
  top-k of a limit-N call equals the top-k of a limit-k call). Policies differ only in which
  members of the ordering they keep, never in the scores.
- Recall is MACRO (mean of per-case recall), matching the pipeline's report metrics. Do not
  compare these numbers to a micro figure from elsewhere.
- `plain` reproduces the shipped behaviour and is the baseline every policy is scored against.
  If `plain` at k=14 does not land on 0.8650 for the champion, the harness is wrong, not the
  finding -- that value has now been reproduced three independent times.

Usage:
    replay_context_diversity.py REPORT_JSON --config CONFIG_YML
                                [--pool 34] [--k 14] [--cases N] [--json-out PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from posixpath import dirname
from time import perf_counter
from typing import Any, Callable

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

DEFAULT_POOL = 34
DEFAULT_K = 14
DEFAULT_PROBE_WORKERS = 4


@dataclass(slots=True, frozen=True)
class CaseOrdering:
    case_id: str
    expected_paths: tuple[str, ...]
    reranked_paths: tuple[str, ...]


def directory_of(path: str) -> str:
    return dirname(path) or "."


def select_plain(ordering: tuple[str, ...], k: int) -> list[str]:
    return list(ordering[:k])


def make_dircap(cap: int) -> Callable[[tuple[str, ...], int], list[str]]:
    """Greedy in rerank order, but no directory may contribute more than `cap` files.

    Skipped files are not discarded -- if the cap starves the window they are appended in
    rerank order until it is full. Without that backfill the policy would silently return
    fewer than k files on cases whose pool is dominated by one directory, and a shorter
    window would confound "diversity helped" with "we showed less".
    """

    def select(ordering: tuple[str, ...], k: int) -> list[str]:
        chosen: list[str] = []
        skipped: list[str] = []
        counts: dict[str, int] = {}
        for path in ordering:
            if len(chosen) >= k:
                break
            directory = directory_of(path)
            if counts.get(directory, 0) >= cap:
                skipped.append(path)
                continue
            chosen.append(path)
            counts[directory] = counts.get(directory, 0) + 1
        for path in skipped:
            if len(chosen) >= k:
                break
            chosen.append(path)
        return chosen

    return select


def select_round_robin(ordering: tuple[str, ...], k: int) -> list[str]:
    """One file per directory in rerank order, then a second from each, and so on.

    The most aggressive diversity policy available without changing the scores: it guarantees
    every directory represented in the pool appears before any directory gets a second slot.
    Included as the extreme end of the axis -- if even this does not cost recall, the cut has a
    lot of slack; if it costs a lot, the useful setting is a mild cap.
    """
    buckets: dict[str, list[str]] = {}
    order: list[str] = []
    for path in ordering:
        directory = directory_of(path)
        if directory not in buckets:
            buckets[directory] = []
            order.append(directory)
        buckets[directory].append(path)
    chosen: list[str] = []
    round_index = 0
    while len(chosen) < k:
        added = False
        for directory in order:
            if len(chosen) >= k:
                break
            files = buckets[directory]
            if round_index < len(files):
                chosen.append(files[round_index])
                added = True
        if not added:
            break
        round_index += 1
    return chosen


POLICIES: dict[str, Callable[[tuple[str, ...], int], list[str]]] = {
    "plain": select_plain,
    "dircap-2": make_dircap(2),
    "dircap-3": make_dircap(3),
    "dircap-4": make_dircap(4),
    "round-robin": select_round_robin,
}


def macro_recall(orderings: list[CaseOrdering], selected: dict[str, list[str]]) -> float:
    eligible = [o for o in orderings if o.expected_paths]
    if not eligible:
        return 0.0
    total = 0.0
    for ordering in eligible:
        window = frozenset(selected[ordering.case_id])
        hits = sum(1 for path in ordering.expected_paths if path in window)
        total += hits / len(ordering.expected_paths)
    return total / len(eligible)


def bundle_complete(orderings: list[CaseOrdering], selected: dict[str, list[str]]) -> float:
    eligible = [o for o in orderings if o.expected_paths]
    if not eligible:
        return 0.0
    hits = sum(
        1 for o in eligible if frozenset(o.expected_paths) <= frozenset(selected[o.case_id])
    )
    return hits / len(eligible)


def mean_directories(orderings: list[CaseOrdering], selected: dict[str, list[str]]) -> float:
    return sum(len({directory_of(p) for p in selected[o.case_id]}) for o in orderings) / len(orderings)


def max_directory_share(orderings: list[CaseOrdering], selected: dict[str, list[str]]) -> float:
    """Mean over cases of (largest directory's file count / window size).

    This is the quantity the H33 diagnosis actually indicts: `where-generated-code-service`
    showed six of eight files from one directory. A policy that does not move this number is
    not testing the hypothesis, whatever it does to recall.
    """
    total = 0.0
    for ordering in orderings:
        window = selected[ordering.case_id]
        if not window:
            continue
        counts: dict[str, int] = {}
        for path in window:
            directory = directory_of(path)
            counts[directory] = counts.get(directory, 0) + 1
        total += max(counts.values()) / len(window)
    return total / len(orderings)


def collect_orderings(
    probe_strategy: Any,
    reranker: AnswerCandidateCrossEncoderReranker,
    rows: list[dict[str, Any]],
    pool: int,
    limit: int,
    probe_workers: int,
) -> list[CaseOrdering]:
    query_limit = max(limit, pool)
    orderings: list[CaseOrdering] = []
    for row in rows:
        case_id = str(row.get("case_id") or "")
        question = str(row.get("question") or "")
        expected = tuple(normalize_path(p) for p in row.get("expected_paths") or [])
        queries = extract_probe_queries(row.get("query_plan") or {}, case_id)
        workers = max(1, min(probe_workers, len(queries)))
        if workers == 1:
            result_sets = [probe_strategy.search(q, query_limit) for q in queries]
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [executor.submit(probe_strategy.search, q, query_limit) for q in queries]
                result_sets = [f.result() for f in futures]
        merged = merge_query_results(result_sets, query_limit)
        reranked, payload = reranker.rerank(question, merged, pool)
        if payload.get("error"):
            raise ReplayPoolRecallError(case_id, f"rerank failed: {payload['error']}")
        orderings.append(
            CaseOrdering(
                case_id=case_id,
                expected_paths=expected,
                reranked_paths=tuple(normalize_path(r.item.path) for r in reranked),
            )
        )
        print(f"  {len(orderings):>3}/{len(rows)} {case_id}", file=sys.stderr, flush=True)
    return orderings


def make_reranker(config: AppConfig, pool: int) -> AnswerCandidateCrossEncoderReranker:
    rerank_config = replace(config.cross_encoder_rerank, candidate_limit=pool)
    return AnswerCandidateCrossEncoderReranker(
        RerankProviderFactory().create(rerank_config), rerank_config
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("report", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--pool", type=int, default=DEFAULT_POOL)
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--cases", type=int, default=None)
    parser.add_argument("--probe-workers", type=int, default=DEFAULT_PROBE_WORKERS)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()

    if args.json_out is not None and args.json_out.exists():
        raise SystemExit(f"refusing to overwrite existing {args.json_out}")

    report = load_report(args.report)
    rows = [r for r in report["results"] if r.get("query_plan") and r.get("expected_paths")]
    if args.cases:
        rows = rows[: args.cases]
    if not rows:
        raise SystemExit(f"{args.report}: no rows with both query_plan and expected_paths")

    config = load_config(args.config)
    limit = int(config.evaluation.limit)
    probe_strategy, _, vector_store = build_probe_strategy(config)
    started = perf_counter()
    try:
        reranker = make_reranker(config, args.pool)
        orderings = collect_orderings(
            probe_strategy, reranker, rows, args.pool, limit, args.probe_workers
        )
    finally:
        close_vector_store(vector_store)
    elapsed = perf_counter() - started

    output: dict[str, Any] = {
        "report": str(args.report),
        "config": str(args.config),
        "cases": len(orderings),
        "pool": args.pool,
        "k": args.k,
        "seconds_per_case": elapsed / len(orderings),
        "policies": {},
    }
    baseline: dict[str, float] = {}
    print(f"\npool {args.pool}, window k={args.k}, {len(orderings)} cases\n")
    print("%-12s %8s %8s %9s %9s %9s" % ("policy", "recall", "d", "bundle", "mean_dirs", "max_share"))
    for name, policy in POLICIES.items():
        selected = {o.case_id: policy(o.reranked_paths, args.k) for o in orderings}
        short = [cid for cid, window in selected.items() if len(window) < args.k]
        block = {
            "macro_recall": macro_recall(orderings, selected),
            "bundle_complete": bundle_complete(orderings, selected),
            "mean_directories": mean_directories(orderings, selected),
            "max_directory_share": max_directory_share(orderings, selected),
            "cases_with_short_window": len(short),
        }
        if name == "plain":
            baseline = dict(block)
        output["policies"][name] = block
        print(
            "%-12s %8.4f %+8.4f %9.3f %9.2f %9.3f"
            % (
                name,
                block["macro_recall"],
                block["macro_recall"] - baseline.get("macro_recall", 0.0),
                block["bundle_complete"],
                block["mean_directories"],
                block["max_directory_share"],
            )
        )
    output["per_case"] = [
        {
            "case_id": o.case_id,
            "expected": list(o.expected_paths),
            "reranked": list(o.reranked_paths),
        }
        for o in orderings
    ]

    if args.json_out is not None:
        args.json_out.write_text(json.dumps(output, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
