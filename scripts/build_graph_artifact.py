"""Rebuild a graph artifact from the repository WITHOUT re-embedding anything.

Why this exists: `code-diver index` builds the graph as a side effect of indexing, so the
only supported way to change graph settings is to re-embed the whole corpus. For a 150k-item
monorepo that is hours of GPU for a product the embedding model never sees -- the graph
builder consumes scanner items (paths, content, symbols) and nothing else.

The scanner is the same factory the CLI uses, so the item ids this produces match the ids
already in the vector store as long as the scanner config matches. Ids derive from path and
line span, not content, so head-truncation changes do not break the correspondence.

The derived `.file-graph-catalog.json` is NOT written here: `GraphFileRetrievalStrategy`
regenerates it on first query whenever it is older than the artifact.

Usage:
    build_graph_artifact.py --config CONFIG_YML --out ARTIFACT_JSON
                            [--reference-edges/--no-reference-edges]
                            [--ast/--no-ast] [--call-edges/--no-call-edges]
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path
from time import perf_counter

from code_diver.cli import make_codebase_scanner
from code_diver.config import ConfigLoader
from code_diver.graph import CodeGraphBuilder, CodeGraphStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference-edges", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--ast", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--call-edges", action=argparse.BooleanOptionalAction, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.out.exists():
        raise SystemExit(f"refusing to overwrite existing {args.out}")

    config = ConfigLoader().load(args.config)
    graph = config.graph
    ast_enabled = graph.ast_enabled if args.ast is None else args.ast
    reference_edges = (
        graph.reference_edges_enabled if args.reference_edges is None else args.reference_edges
    )
    call_edges = graph.call_edges_enabled if args.call_edges is None else args.call_edges

    print(f"config     : {args.config}", file=sys.stderr)
    print(f"root       : {config.root}", file=sys.stderr)
    print(f"ast={ast_enabled} references={reference_edges} calls={call_edges}", file=sys.stderr)

    started = perf_counter()
    items = make_codebase_scanner(config).scan(Path(config.root))
    print(f"scanned    : {len(items)} items in {perf_counter() - started:.1f}s", file=sys.stderr)

    started = perf_counter()
    built = CodeGraphBuilder(
        ast_enabled=ast_enabled,
        reference_edges_enabled=reference_edges,
        call_edges_enabled=call_edges,
    ).build(Path(config.root), items)
    print(f"built      : {len(built.edges)} edges in {perf_counter() - started:.1f}s", file=sys.stderr)

    kinds = collections.Counter(edge.kind for edge in built.edges)
    for kind, count in kinds.most_common():
        print(f"  {kind:<18} {count}")
    cross_file = sum(
        1
        for edge in built.edges
        if built.items[edge.source].path != built.items[edge.target].path
    )
    print(f"  {'cross-file total':<18} {cross_file}")

    CodeGraphStore(args.out).save(built)
    print(f"\nwrote {args.out} ({args.out.stat().st_size / 1e6:.1f} MB)")
    if not cross_file:
        print("WARNING: no cross-file edges -- file-level adjacency will be empty")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
