#!/usr/bin/env python3
"""Dedicated evaluation script for RepoQA benchmark on code-diver.

Evaluates code retrieval performance on the RepoQA benchmark:
1. Unpacks repository files from artifacts/repoqa/repoqa.json.gz into .benchmarks/repoqa/<lang>/<repo_slug>
2. Indexes each repository using code-diver
3. Evaluates needles (functions to retrieve from English descriptions):
   - File Hit@1, Hit@3, Hit@5
   - File MRR
   - Function Line Overlap / Hit (top retrieved chunk overlaps [start_line, end_line])
4. Outputs formatted results table and timing
"""

from __future__ import annotations

import argparse
import contextlib
import gzip
import json
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from code_diver.cli import (
    close_vector_store,
    make_embedding_provider,
    make_indexing_service,
    make_vector_store,
    scope_relative_repo_artifacts,
)
from code_diver.config import AppConfig, ConfigLoader
from code_diver.services import IndexCollectionResolver
from code_diver.strategies.retrieval_strategy_factory import RetrievalStrategyFactory


def slugify_repo(repo_name: str) -> str:
    """Convert 'org/repo' to 'org_repo' safe for directory names."""
    return repo_name.replace("/", "_").replace("-", "_")


def normalize_path(path: str) -> str:
    """Normalize file paths for consistent comparison."""
    p = path.strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.lstrip("/")


def intervals_overlap(s1: int, e1: int, s2: int, e2: int) -> bool:
    """Check if two 1D integer intervals [s1, e1] and [s2, e2] overlap."""
    return max(s1, s2) <= min(e1, e2)


def dedupe_files(paths: list[str]) -> list[str]:
    """Deduplicate file paths preserving rank order."""
    seen: set[str] = set()
    files: list[str] = []
    for p in paths:
        norm = normalize_path(p)
        if norm not in seen:
            seen.add(norm)
            files.append(norm)
    return files


def unpack_repo(repo_entry: dict[str, Any], target_dir: Path, force: bool = False) -> int:
    """Unpack repository files from dataset into target_dir."""
    files_dict: dict[str, str] = repo_entry.get("content", {})
    if not force and target_dir.exists() and any(target_dir.iterdir()):
        return len(files_dict)

    target_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for rel_path, content in files_dict.items():
        dest = target_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        count += 1
    return count


def index_repo(
    target_dir: Path,
    base_config: AppConfig,
    symbol_chunks: bool = True,
    symbol_body: bool = True,
    reindex: bool = False,
) -> tuple[AppConfig, float]:
    """Index repository using code-diver indexing service."""
    config = replace(
        base_config,
        root=target_dir.resolve(),
        scanner=replace(
            base_config.scanner,
            symbol_chunks=symbol_chunks,
            line_chunks=False,
            symbol_body=symbol_body,
            file_summary_chunks=True,
            file_manifest_chunks=True,
        ),
        cross_encoder_rerank=replace(
            base_config.cross_encoder_rerank,
            url="http://127.0.0.1:18081/v1/rerank",
        ),
    )
    config = scope_relative_repo_artifacts(config)
    config = IndexCollectionResolver().resolve(config)

    t0 = time.perf_counter()
    provider = make_embedding_provider(config)
    indexing_service = make_indexing_service(config, progress=False)

    if reindex:
        with contextlib.suppress(Exception):
            indexing_service.vector_store.clear()

    exists = False
    point_count = 0
    try:
        exists = indexing_service.vector_store.exists()
        if exists:
            client = getattr(indexing_service.vector_store, "client", None)
            if client is not None:
                point_count = int(client.count(collection_name=config.storage.qdrant.collection, exact=True).count)
    except Exception:
        exists = False

    index_time = 0.0
    if not exists or point_count == 0 or reindex:
        items = indexing_service.build(target_dir.resolve(), provider=provider)
        index_time = time.perf_counter() - t0
        print(f"  [Index] Indexed {len(items)} items in {index_time:.2f}s -> {config.storage.qdrant.collection}")
    else:
        print(f"  [Index] Reusing existing collection '{config.storage.qdrant.collection}' ({point_count} items)")

    close_vector_store(indexing_service.vector_store)
    return config, index_time


def evaluate_repo(
    repo_name: str,
    lang: str,
    repo_entry: dict[str, Any],
    config: AppConfig,
    strategy_name: str = "vector",
    limit: int = 10,
) -> dict[str, Any]:
    """Evaluate retrieval on all needles for a repository."""
    vector_store = make_vector_store(config)
    provider = make_embedding_provider(config, vector_store.metadata())

    # Ensure hybrid_search does not filter out symbol kinds if hybrid is used
    eval_config = config
    if strategy_name == "hybrid":
        eval_config = replace(config, hybrid_search=replace(config.hybrid_search, vector_kind_limits={}))

    factory = RetrievalStrategyFactory()
    strategy = factory.create(strategy_name, eval_config, provider, vector_store)

    needles = repo_entry.get("needles", [])
    results_detail = []

    file_hit1_list: list[bool] = []
    file_hit3_list: list[bool] = []
    file_hit5_list: list[bool] = []
    file_mrr_list: list[float] = []
    line_overlap1_list: list[bool] = []
    line_overlap3_list: list[bool] = []
    line_overlap5_list: list[bool] = []
    latencies_ms: list[float] = []

    for idx, needle in enumerate(needles):
        query = needle.get("description", "").strip()
        target_file = normalize_path(needle.get("path", ""))
        n_start = int(needle.get("start_line", 0))
        n_end = int(needle.get("end_line", 0))
        func_name = needle.get("name", "")

        t_query_start = time.perf_counter()
        search_results = strategy.search(query, limit=limit)
        latency_ms = (time.perf_counter() - t_query_start) * 1000.0
        latencies_ms.append(latency_ms)

        retrieved_paths = [r.item.path for r in search_results]
        unique_files = dedupe_files(retrieved_paths)

        # File metrics
        hit1 = bool(unique_files and unique_files[0] == target_file)
        hit3 = target_file in unique_files[:3]
        hit5 = target_file in unique_files[:5]
        mrr = (1.0 / (unique_files.index(target_file) + 1)) if target_file in unique_files else 0.0

        file_hit1_list.append(hit1)
        file_hit3_list.append(hit3)
        file_hit5_list.append(hit5)
        file_mrr_list.append(mrr)

        # Function Line Overlap / Hit
        def chunk_overlaps(res_item, target: str, start: int, end: int) -> bool:
            if not res_item:
                return False
            item_path = normalize_path(res_item.path)
            if item_path != target:
                return False
            if res_item.start_line is None or res_item.end_line is None:
                return False
            return intervals_overlap(int(res_item.start_line), int(res_item.end_line), start, end)

        top_chunk_overlap = chunk_overlaps(search_results[0].item, target_file, n_start, n_end) if search_results else False
        overlap_at_3 = any(chunk_overlaps(r.item, target_file, n_start, n_end) for r in search_results[:3])
        overlap_at_5 = any(chunk_overlaps(r.item, target_file, n_start, n_end) for r in search_results[:5])

        line_overlap1_list.append(top_chunk_overlap)
        line_overlap3_list.append(overlap_at_3)
        line_overlap5_list.append(overlap_at_5)

        results_detail.append({
            "needle_index": idx,
            "function": func_name,
            "target_file": target_file,
            "lines": [n_start, n_end],
            "file_hit1": hit1,
            "file_hit3": hit3,
            "file_hit5": hit5,
            "file_mrr": mrr,
            "line_overlap1": top_chunk_overlap,
            "line_overlap3": overlap_at_3,
            "line_overlap5": overlap_at_5,
            "latency_ms": latency_ms,
            "top_retrieved": [
                {
                    "path": r.item.path,
                    "kind": r.item.metadata.get("index_kind"),
                    "lines": [r.item.start_line, r.item.end_line],
                    "score": round(float(r.score), 4),
                }
                for r in search_results[:3]
            ],
        })

    close_vector_store(vector_store)

    n_count = len(needles) or 1
    return {
        "repo": repo_name,
        "language": lang,
        "needles_count": len(needles),
        "file_hit1": sum(file_hit1_list) / n_count,
        "file_hit3": sum(file_hit3_list) / n_count,
        "file_hit5": sum(file_hit5_list) / n_count,
        "file_mrr": sum(file_mrr_list) / n_count,
        "line_overlap1": sum(line_overlap1_list) / n_count,
        "line_overlap3": sum(line_overlap3_list) / n_count,
        "line_overlap5": sum(line_overlap5_list) / n_count,
        "mean_latency_ms": sum(latencies_ms) / n_count,
        "needles": results_detail,
    }


def print_summary_table(repo_results: list[dict[str, Any]], strategy: str) -> None:
    """Print a clean Markdown table summarizing benchmark results."""
    print(f"\n### RepoQA Retrieval Benchmark Results (Strategy: `{strategy}`)\n")
    headers = [
        "Repository",
        "Language",
        "Needles",
        "File Hit@1",
        "File Hit@3",
        "File Hit@5",
        "File MRR",
        "Line Overlap@1",
        "Line Overlap@3",
        "Avg Latency",
    ]
    header_line = "| " + " | ".join(headers) + " |"
    sep_line = "| " + " | ".join(["---"] * len(headers)) + " |"
    print(header_line)
    print(sep_line)

    total_needles = sum(r["needles_count"] for r in repo_results) or 1
    weighted_hit1 = sum(r["file_hit1"] * r["needles_count"] for r in repo_results) / total_needles
    weighted_hit3 = sum(r["file_hit3"] * r["needles_count"] for r in repo_results) / total_needles
    weighted_hit5 = sum(r["file_hit5"] * r["needles_count"] for r in repo_results) / total_needles
    weighted_mrr = sum(r["file_mrr"] * r["needles_count"] for r in repo_results) / total_needles
    weighted_line1 = sum(r["line_overlap1"] * r["needles_count"] for r in repo_results) / total_needles
    weighted_line3 = sum(r["line_overlap3"] * r["needles_count"] for r in repo_results) / total_needles
    avg_latency = sum(r["mean_latency_ms"] * r["needles_count"] for r in repo_results) / total_needles

    for r in repo_results:
        row = [
            f"`{r['repo']}`",
            r["language"],
            str(r["needles_count"]),
            f"{r['file_hit1']:.1%}",
            f"{r['file_hit3']:.1%}",
            f"{r['file_hit5']:.1%}",
            f"{r['file_mrr']:.3f}",
            f"{r['line_overlap1']:.1%}",
            f"{r['line_overlap3']:.1%}",
            f"{r['mean_latency_ms']:.1f} ms",
        ]
        print("| " + " | ".join(row) + " |")

    overall_row = [
        "**OVERALL (Mean)**",
        "-",
        f"**{total_needles}**",
        f"**{weighted_hit1:.1%}**",
        f"**{weighted_hit3:.1%}**",
        f"**{weighted_hit5:.1%}**",
        f"**{weighted_mrr:.3f}**",
        f"**{weighted_line1:.1%}**",
        f"**{weighted_line3:.1%}**",
        f"**{avg_latency:.1f} ms**",
    ]
    print("| " + " | ".join(overall_row) + " |")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate code-diver on RepoQA benchmark.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("artifacts/repoqa/repoqa.json.gz"),
        help="Path to repoqa.json.gz dataset.",
    )
    parser.add_argument(
        "--repos",
        nargs="+",
        default=["psf/black", "google/gson"],
        help="Repositories to evaluate (e.g. psf/black google/gson).",
    )
    parser.add_argument(
        "--benchmarks-dir",
        type=Path,
        default=Path(".benchmarks/repoqa"),
        help="Root directory for unpacked corpora.",
    )
    parser.add_argument(
        "--strategy",
        type=str,
        default="vector",
        help="Retrieval strategy (e.g. vector, hybrid, graph_file, cross_encoder_rerank).",
    )
    parser.add_argument(
        "--symbol-chunks",
        action="store_true",
        default=True,
        help="Enable symbol chunks during indexing (required for function line overlap).",
    )
    parser.add_argument(
        "--no-symbol-chunks",
        dest="symbol_chunks",
        action="store_false",
        help="Disable symbol chunks (file-level retrieval only).",
    )
    parser.add_argument(
        "--reindex",
        action="store_true",
        default=False,
        help="Force re-indexing even if collection already exists.",
    )
    parser.add_argument(
        "--force-unpack",
        action="store_true",
        default=False,
        help="Force re-unpacking files from archive.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of retrieved results per query.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write benchmark results JSON.",
    )

    args = parser.parse_args()

    if not args.dataset.exists():
        print(f"Error: dataset file not found at {args.dataset}", file=sys.stderr)
        return 1

    print(f"Loading RepoQA dataset from {args.dataset}...")
    with gzip.open(args.dataset, "rt", encoding="utf-8") as f:
        dataset = json.load(f)

    # Index dataset by repo name: repo -> (lang, entry)
    repo_map: dict[str, tuple[str, dict[str, Any]]] = {}
    for lang, repos in dataset.items():
        if isinstance(repos, list):
            for entry in repos:
                repo_name = entry.get("repo")
                if repo_name:
                    repo_map[repo_name] = (lang, entry)

    selected_repos = args.repos
    missing = [r for r in selected_repos if r not in repo_map]
    if missing:
        print(f"Error: Repositories not found in dataset: {missing}", file=sys.stderr)
        print(f"Available repos: {list(repo_map.keys())}", file=sys.stderr)
        return 1

    base_config = ConfigLoader().load(None)

    all_results = []
    total_start = time.perf_counter()

    for repo_name in selected_repos:
        lang, entry = repo_map[repo_name]
        slug = slugify_repo(repo_name)
        target_dir = args.benchmarks_dir / lang / slug

        print(f"\nProcessing `{repo_name}` ({lang}):")
        file_count = unpack_repo(entry, target_dir, force=args.force_unpack)
        print(f"  [Corpus] {file_count} files in {target_dir}")

        config, idx_time = index_repo(
            target_dir=target_dir,
            base_config=base_config,
            symbol_chunks=args.symbol_chunks,
            symbol_body=True,
            reindex=args.reindex,
        )

        print(f"  [Eval] Running {len(entry.get('needles', []))} queries with strategy='{args.strategy}'...")
        eval_result = evaluate_repo(
            repo_name=repo_name,
            lang=lang,
            repo_entry=entry,
            config=config,
            strategy_name=args.strategy,
            limit=args.limit,
        )
        eval_result["index_time_s"] = idx_time
        all_results.append(eval_result)

        print(f"  -> File Hit@1: {eval_result['file_hit1']:.1%}, Hit@3: {eval_result['file_hit3']:.1%}, Hit@5: {eval_result['file_hit5']:.1%}")
        print(f"  -> File MRR:   {eval_result['file_mrr']:.3f}")
        print(f"  -> Line Overlap@1: {eval_result['line_overlap1']:.1%}, Overlap@3: {eval_result['line_overlap3']:.1%}")
        print(f"  -> Mean Latency:  {eval_result['mean_latency_ms']:.1f} ms")

    total_time = time.perf_counter() - total_start

    print_summary_table(all_results, strategy=args.strategy)
    print(f"Total benchmark wall-clock time: {total_time:.2f}s")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "strategy": args.strategy,
            "symbol_chunks": args.symbol_chunks,
            "limit": args.limit,
            "total_time_s": total_time,
            "repositories": all_results,
        }
        args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Saved results to {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
