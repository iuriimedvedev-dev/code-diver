"""Measure retrieval pool recall by replaying probe queries from a saved answer-eval report.

Why this exists: the naive way to benchmark retrieval cheaply is `code-diver evaluate`, but
that command issues exactly one query per case with no query planner and no multi-probe
fan-out, so its recall curve does not describe the real answer pipeline's candidate pool.
This script avoids that flaw by reusing the REAL probe queries the query planner already
produced for a case -- they are persisted per case in an `evaluate-answers` report under
`query_plan.queries` -- and merging their per-query results exactly the way `AnswerEvaluator`
does (see `code_diver.answering.answer_query_merge.merge_query_results`, which both this
script and `AnswerEvaluator` call so the two cannot drift). No planner call and no answer
generation are needed: the probe queries are input data, and this script never talks to a
generation/judge model.

The retrieval strategy that actually executes each probe query is `--config`'s search
strategy with any final LLM/cross-encoder rerank stage peeled off (`unwrap_probe_strategy`,
below): a rerank stage is applied ONCE to the merged pool in the real pipeline, not per
probe query, and running the LLM rerank on every one of ~8 probes per case would be both
slow and unfaithful to what actually produced the persisted pool.

Usage:
    replay_pool_recall.py REPORT_JSON --config CONFIG_YML [--json-out PATH]
                          [--candidate-limit N] [--k 1,5,10,20,34,60] [--cases N]
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from code_diver.answering.answer_query_merge import merge_query_results
from code_diver.cli import close_vector_store, make_embedding_provider, make_retrieval_strategy, make_vector_store
from code_diver.config import AppConfig, ConfigLoader
from code_diver.env import EnvFileLoader
from code_diver.strategies import CrossEncoderRerankRetrievalStrategy, LlmRerankRetrievalStrategy, RetrievalStrategy

# The only two strategy wrappers the factory applies as a *final* rerank pass over an
# already-merged candidate pool (see `RetrievalStrategyFactory.create`). Both name their
# wrapped strategy `.base_strategy` and their rerank candidate cap `config.candidate_limit`,
# but so do several non-rerank strategies (`GraphFileRetrievalStrategy`,
# `HybridRetrievalStrategy`) that also wrap an inner strategy as `.base_strategy` -- duck
# typing on that attribute alone would peel through those too and pick up the wrong
# candidate_limit. Checking these two concrete types keeps the unwrap exact.
RERANK_WRAPPER_TYPES: tuple[type[RetrievalStrategy], ...] = (
    LlmRerankRetrievalStrategy,
    CrossEncoderRerankRetrievalStrategy,
)

# Mirrors the `--query-workers` default in `code-diver evaluate-answers`
# (see `evaluate_answers.add_argument("--query-workers", default=4, ...)` in cli.py).
DEFAULT_PROBE_WORKERS = 4

DEFAULT_K_VALUES: tuple[int, ...] = (1, 5, 10, 20, 34, 60)


class ReplayPoolRecallError(Exception):
    def __init__(self, case_id: str, reason: str) -> None:
        super().__init__(f"case {case_id}: {reason}")
        self.case_id = case_id
        self.reason = reason


@dataclass(slots=True, frozen=True)
class CaseReplayRecord:
    """One case's replayed merged pool, reduced to what recall arithmetic needs.

    `ranked_paths` is the normalized, deduplicated file path ranking of the full merge (up
    to `query_limit`), before any truncation to the reported candidate pool size -- this lets
    `recall_at_k` answer "how big would the pool need to be" for k beyond `candidate_limit`.
    """

    case_id: str
    expected_paths: tuple[str, ...]
    ranked_paths: tuple[str, ...]
    ranked_ids: tuple[str, ...]
    ranked_scores: tuple[float, ...]
    probe_queries: tuple[str, ...]
    wall_seconds: float


def normalize_path(path: str) -> str:
    return path.strip().lstrip("./")


def extract_probe_queries(query_plan: dict[str, Any], case_id: str) -> list[str]:
    """Pull the probe query strings out of a report row's `query_plan.queries`.

    Handles the two plausible JSON shapes -- a list of plain strings (what
    `AnswerQueryPlanner` actually persists today) or a list of `{"query": "..."}`-style
    objects -- and fails loudly on anything else rather than silently skipping a case.
    """
    raw_queries = query_plan.get("queries")
    if not isinstance(raw_queries, list) or not raw_queries:
        raise ReplayPoolRecallError(case_id, "query_plan.queries is missing or not a non-empty list")
    queries: list[str] = []
    for item in raw_queries:
        if isinstance(item, str):
            query = item.strip()
        elif isinstance(item, dict):
            value = item.get("query") if "query" in item else item.get("text")
            query = str(value or "").strip()
        else:
            raise ReplayPoolRecallError(
                case_id, f"unsupported query_plan.queries item type: {type(item).__name__}"
            )
        if query:
            queries.append(query)
    if not queries:
        raise ReplayPoolRecallError(case_id, "query_plan.queries contained no usable query strings")
    return queries


def unwrap_probe_strategy(strategy: RetrievalStrategy) -> tuple[RetrievalStrategy, int | None]:
    """Peel off a final rerank wrapper, if any, to recover the pre-rerank probe strategy.

    This is what `AnswerEvaluator._retrieve` effectively runs for its per-query fan-out: a
    rerank stage (`LlmRerankRetrievalStrategy` / `CrossEncoderRerankRetrievalStrategy`) is
    applied ONCE, to the already-merged pool, never per probe query. Recovering the wrapped
    strategy here means probe queries never trigger a rerank LLM/cross-encoder call.

    Only one level is peeled off (the factory never nests rerank wrappers), and only for the
    two concrete rerank wrapper types -- not any strategy exposing `.base_strategy`, since
    several non-rerank strategies (`GraphFileRetrievalStrategy`, `HybridRetrievalStrategy`)
    use that same attribute name for an unrelated purpose.
    """
    if isinstance(strategy, RERANK_WRAPPER_TYPES):
        return strategy.base_strategy, int(strategy.config.candidate_limit)
    return strategy, None


def load_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or "results" not in report:
        raise ValueError(f"{path}: missing top-level 'results' list")
    if not isinstance(report["results"], list):
        raise ValueError(f"{path}: 'results' must be a list")
    return report


def load_config(path: Path) -> AppConfig:
    config = ConfigLoader().load(path)
    EnvFileLoader().load(config.env_file.path, config.env_file.override)
    return config


def build_probe_strategy(config: AppConfig) -> tuple[RetrievalStrategy, int | None, Any]:
    vector_store = make_vector_store(config, progress=False)
    if not vector_store.exists():
        raise RuntimeError(
            f"No index found for {config.storage.qdrant.collection!r}. "
            "Build it first (this script never triggers indexing)."
        )
    provider = make_embedding_provider(config, vector_store.metadata())
    strategy = make_retrieval_strategy(config, provider, vector_store)
    probe_strategy, configured_candidate_limit = unwrap_probe_strategy(strategy)
    return probe_strategy, configured_candidate_limit, vector_store


def replay_case(
    probe_strategy: RetrievalStrategy,
    case_id: str,
    expected_paths: list[str],
    probe_queries: list[str],
    query_limit: int,
    query_workers: int,
) -> CaseReplayRecord:
    started = perf_counter()
    worker_count = max(1, min(query_workers, len(probe_queries)))
    if worker_count == 1:
        result_sets = [probe_strategy.search(query, query_limit) for query in probe_queries]
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(probe_strategy.search, query, query_limit) for query in probe_queries]
            result_sets = [future.result() for future in futures]
    merged = merge_query_results(result_sets, query_limit)
    ranked_paths = tuple(normalize_path(result.item.path) for result in merged)
    ranked_ids = tuple(str(result.item.id) for result in merged)
    ranked_scores = tuple(float(result.score) for result in merged)
    wall_seconds = perf_counter() - started
    return CaseReplayRecord(
        case_id=case_id,
        expected_paths=tuple(normalize_path(path) for path in expected_paths),
        ranked_paths=ranked_paths,
        ranked_ids=ranked_ids,
        ranked_scores=ranked_scores,
        probe_queries=tuple(probe_queries),
        wall_seconds=wall_seconds,
    )


def micro_recall_at_k(records: list[CaseReplayRecord], k: int) -> float:
    """Fraction of all expected paths, pooled across every case, found within the top k of
    that case's merged ranking. Micro-averaged: cases with more expected paths count more."""
    total_expected = 0
    total_hit = 0
    for record in records:
        window = frozenset(record.ranked_paths[:k])
        total_expected += len(record.expected_paths)
        total_hit += sum(1 for path in record.expected_paths if path in window)
    return total_hit / total_expected if total_expected else 0.0


def bundle_complete_rate(records: list[CaseReplayRecord], k: int) -> float:
    """Fraction of CASES where every expected path is within the top k of the ranking.
    Cases with no expected paths cannot be complete and are excluded from both sides."""
    eligible = [record for record in records if record.expected_paths]
    if not eligible:
        return 0.0
    complete = sum(
        1
        for record in eligible
        if frozenset(record.expected_paths) <= frozenset(record.ranked_paths[:k])
    )
    return complete / len(eligible)


def case_detail(record: CaseReplayRecord, candidate_limit: int) -> dict[str, Any]:
    pool_ranks = {path: rank for rank, path in enumerate(record.ranked_paths[:candidate_limit], start=1)}
    found = {path: pool_ranks[path] for path in record.expected_paths if path in pool_ranks}
    missing = [path for path in record.expected_paths if path not in pool_ranks]
    recall = len(found) / len(record.expected_paths) if record.expected_paths else None
    pool = [
        {"rank": rank, "path": path, "id": record.ranked_ids[rank - 1], "score": record.ranked_scores[rank - 1]}
        for rank, path in enumerate(record.ranked_paths[:candidate_limit], start=1)
    ]
    return {
        "case_id": record.case_id,
        "expected_paths": list(record.expected_paths),
        "probe_queries": list(record.probe_queries),
        "pool_size": min(candidate_limit, len(record.ranked_paths)),
        "pool": pool,
        "found": found,
        "missing": missing,
        "recall": recall,
        "bundle_complete": (recall == 1.0) if record.expected_paths else None,
        "wall_seconds": record.wall_seconds,
    }


def print_table(
    records: list[CaseReplayRecord],
    candidate_limit: int,
    query_limit: int,
    k_values: tuple[int, ...],
) -> None:
    print(f"cases={len(records)}  candidate_limit={candidate_limit}  query_limit={query_limit}")
    print(f"pool_recall@{candidate_limit:<3} {micro_recall_at_k(records, candidate_limit):>7.3f}")
    print(f"pool_bundle_complete   {bundle_complete_rate(records, candidate_limit):>7.3f}")
    print()
    print(f"  {'k':>5} {'recall@k':>10} {'bundle_complete@k':>18}")
    for k in sorted(set(k_values) | {candidate_limit}):
        print(f"  {k:>5} {micro_recall_at_k(records, k):>10.3f} {bundle_complete_rate(records, k):>18.3f}")
    mean_wall_seconds = sum(record.wall_seconds for record in records) / max(len(records), 1)
    print(f"\nmean wall-seconds per case: {mean_wall_seconds:.3f}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("report", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--candidate-limit", type=int, default=None)
    parser.add_argument("--k", default=",".join(str(value) for value in DEFAULT_K_VALUES))
    parser.add_argument("--cases", type=int, default=None)
    args = parser.parse_args()

    k_values = tuple(sorted({int(value) for value in args.k.split(",") if value.strip()}))
    if not k_values:
        print("error: --k must contain at least one integer", file=sys.stderr)
        return 1

    report = load_report(args.report)
    rows = report["results"]
    if args.cases is not None:
        rows = rows[: max(args.cases, 0)]
    if not rows:
        print(f"error: no result rows in {args.report}", file=sys.stderr)
        return 1

    config = load_config(args.config)
    started = perf_counter()
    probe_strategy, configured_candidate_limit, vector_store = build_probe_strategy(config)
    try:
        final_limit = max(int(config.evaluation.limit or 1), 1)
        candidate_limit = args.candidate_limit or configured_candidate_limit or final_limit
        query_limit = max(final_limit, candidate_limit, max(k_values), 1)

        records: list[CaseReplayRecord] = []
        for row in rows:
            case_id = str(row.get("case_id") or "")
            if not case_id:
                raise ReplayPoolRecallError("<unknown>", "row is missing 'case_id'")
            query_plan = row.get("query_plan")
            if not isinstance(query_plan, dict):
                raise ReplayPoolRecallError(case_id, "row is missing 'query_plan'")
            probe_queries = extract_probe_queries(query_plan, case_id)
            expected_paths = [str(path) for path in row.get("expected_paths") or []]
            records.append(
                replay_case(
                    probe_strategy,
                    case_id,
                    expected_paths,
                    probe_queries,
                    query_limit,
                    DEFAULT_PROBE_WORKERS,
                )
            )
    finally:
        close_vector_store(vector_store)

    total_wall_seconds = perf_counter() - started
    print_table(records, candidate_limit, query_limit, k_values)

    if args.json_out:
        payload = {
            "report": str(args.report),
            "config": str(args.config),
            "cases": len(records),
            "candidate_limit": candidate_limit,
            "query_limit": query_limit,
            "k_values": list(k_values),
            "pool_recall_at_candidate_limit": micro_recall_at_k(records, candidate_limit),
            "pool_bundle_complete": bundle_complete_rate(records, candidate_limit),
            "recall_at_k": {str(k): micro_recall_at_k(records, k) for k in sorted(set(k_values) | {candidate_limit})},
            "bundle_complete_at_k": {
                str(k): bundle_complete_rate(records, k) for k in sorted(set(k_values) | {candidate_limit})
            },
            "mean_wall_seconds_per_case": sum(record.wall_seconds for record in records) / max(len(records), 1),
            "total_wall_seconds": total_wall_seconds,
            "per_case": [case_detail(record, candidate_limit) for record in records],
        }
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nwrote {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
