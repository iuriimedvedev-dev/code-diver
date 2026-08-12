"""Rewrite an answer-eval report with probe queries that name nonexistent paths removed.

The query planner spends a quarter of its probe slots on `site:`-style path hints, and in
the champion report 78% of those name a path or directory that is not in the repository at
all. Whether that *costs* pool recall is a separate question from whether it happens, so
this script produces the input for a paired replay: same cases, same surviving probes, only
the invented-path slots dropped.

`replay_pool_recall.py` reads probe queries out of `query_plan.queries`, so filtering the
report and replaying the copy keeps the measurement honest -- no retrieval code is touched
and no LLM is called. Cases never lose every probe (asserted below), because an empty plan
would silently change what is being compared.

Usage:
    filter_hallucinated_path_probes.py REPORT --graph ARTIFACT --out FILTERED [--report-json SUMMARY]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

# `site:src/foo/` , `src/foo/bar.py` , `apps/*/thing.md` -- anything with a slash in it.
PATH_PATTERN = re.compile(r"(?:site:)?((?:[\w.\-*]+/)+[\w.\-*]*)")


class FilterProbesError(RuntimeError):
    pass


def load_known_paths(artifact: Path) -> tuple[set[str], set[str]]:
    """Return (file paths, directory prefixes) present in the graph artifact."""
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    items = payload.get("graph", {}).get("items")
    if not isinstance(items, dict) or not items:
        raise FilterProbesError(f"{artifact} has no graph.items")
    files = {item["path"] for item in items.values()}
    directories: set[str] = set()
    for path in files:
        parts = path.split("/")
        for index in range(1, len(parts)):
            directories.add("/".join(parts[:index]))
    return files, directories


def path_candidates(query: str) -> list[str]:
    return [
        match.group(1).rstrip("/")
        for match in PATH_PATTERN.finditer(query)
        if "/" in match.group(1)
    ]


def names_a_real_path(candidate: str, files: set[str], directories: set[str]) -> bool:
    if "*" not in candidate:
        return candidate in files or candidate in directories
    glob = re.compile("^" + re.escape(candidate).replace("\\*", "[^/]*") + "$")
    return any(glob.match(path) for path in files) or any(glob.match(path) for path in directories)


def invents_a_path(query: str, files: set[str], directories: set[str]) -> bool:
    """True when the query names paths and none of them exist.

    A query is kept when *any* candidate resolves: a probe that pairs one real path with
    one typo is still steering retrieval somewhere real, and dropping it would confound
    the arm with a second change.
    """
    candidates = path_candidates(query)
    if not candidates:
        return False
    return not any(names_a_real_path(candidate, files, directories) for candidate in candidates)


def strip_invented_paths(query: str, files: set[str], directories: set[str]) -> str:
    """Remove only the path tokens that name nothing, keeping the rest of the query text.

    `src/qa/ evaluation dataset execution` invents a directory but its remaining words are
    ordinary useful query terms. Dropping the whole probe throws those away too, which
    confounds "the invented path misleads retrieval" with "the probe's words were needed".
    """
    kept: list[str] = []
    for token in query.split():
        candidates = path_candidates(token)
        if candidates and not any(names_a_real_path(candidate, files, directories) for candidate in candidates):
            continue
        kept.append(token)
    # `a/b.py OR c/d.py` collapses to a bare `OR` once both operands go. Those connectives
    # only existed to join the removed paths, and leaving them turns the probe into a
    # near-empty query -- a second change on top of the one being tested.
    substantive = [token for token in kept if token.upper() not in {"OR", "AND", "NOT"}]
    return " ".join(substantive)


def query_text(entry: Any) -> str:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        return str(entry.get("query", ""))
    raise FilterProbesError(f"unsupported query_plan.queries item type: {type(entry).__name__}")


def filter_report(
    report: dict[str, Any],
    files: set[str],
    directories: set[str],
    mode: str,
) -> dict[str, Any]:
    results = report.get("results")
    if not isinstance(results, list) or not results:
        raise FilterProbesError("report has no non-empty `results` list")
    dropped_total = 0
    kept_total = 0
    rewritten_total = 0
    emptied: list[str] = []
    for case in results:
        case_id = case.get("case_id", "<unknown>")
        queries = case.get("query_plan", {}).get("queries")
        if not isinstance(queries, list) or not queries:
            raise FilterProbesError(f"{case_id}: query_plan.queries is missing or empty")
        kept: list[str] = []
        for entry in queries:
            original = query_text(entry)
            if not invents_a_path(original, files, directories):
                kept.append(original)
                continue
            if mode == "drop":
                dropped_total += 1
                continue
            # A probe that was nothing but an invented path has no words left to keep.
            stripped = strip_invented_paths(original, files, directories)
            if stripped:
                rewritten_total += 1
                kept.append(stripped)
            else:
                dropped_total += 1
        kept_total += len(kept)
        if not kept:
            emptied.append(case_id)
        case["query_plan"]["queries"] = kept
    if emptied:
        raise FilterProbesError(
            f"{len(emptied)} case(s) would lose every probe, which is a different experiment: {emptied[:5]}"
        )
    report["probe_filter"] = {
        "mode": mode,
        "dropped_slots": dropped_total,
        "rewritten_slots": rewritten_total,
        "kept_slots": kept_total,
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("report", type=Path, help="answer-eval report to filter")
    parser.add_argument("--graph", type=Path, required=True, help="graph artifact naming the real paths")
    parser.add_argument("--out", type=Path, required=True, help="where to write the filtered report")
    parser.add_argument(
        "--mode",
        choices=("drop", "strip"),
        default="drop",
        help="drop the whole probe, or strip only its invented path tokens",
    )
    args = parser.parse_args()

    if args.out.exists():
        raise FilterProbesError(f"refusing to overwrite {args.out}")
    files, directories = load_known_paths(args.graph)
    report = json.loads(args.report.read_text(encoding="utf-8"))
    filtered = filter_report(report, files, directories, args.mode)
    args.out.write_text(json.dumps(filtered), encoding="utf-8")
    stats = filtered["probe_filter"]
    print(
        f"mode={stats['mode']} dropped={stats['dropped_slots']} "
        f"rewritten={stats['rewritten_slots']} kept={stats['kept_slots']}"
    )
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
