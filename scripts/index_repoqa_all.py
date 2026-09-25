#!/usr/bin/env python3
# ruff: noqa: E402, I001
"""Index all 60 repositories from RepoQA benchmark into Qdrant."""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

# Ensure repo root and src/ are in sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from code_diver.cli import scope_relative_repo_artifacts
from code_diver.config import ConfigLoader
from code_diver.services import IndexCollectionResolver
from scripts.benchmark_repoqa import (
    close_vector_store,
    index_repo,
    make_vector_store,
    slugify_repo,
    unpack_repo,
)
from scripts.benchmark_repoqa_agent_litellm import EVAL_REPOS_100

KNOWN_SLUGS: dict[str, str] = {r["repo"]: r["slug"] for r in EVAL_REPOS_100}


def get_repo_slug(repo_name: str) -> str:
    """Return directory slug for repository, respecting known benchmark slugs."""
    return KNOWN_SLUGS.get(repo_name, slugify_repo(repo_name))


def discover_repos(
    benchmarks_dir: Path,
    dataset_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Discover all 60 repositories unpacked under benchmarks_dir/<lang>/<slug>."""
    slug_to_repo: dict[tuple[str, str], str] = {}
    dataset_order: list[tuple[str, str]] = []

    if dataset_path and dataset_path.exists():
        try:
            with gzip.open(dataset_path, "rt", encoding="utf-8") as f:
                ds = json.load(f)
            for lang, entries in ds.items():
                if isinstance(entries, list):
                    for entry in entries:
                        repo = entry.get("repo", "")
                        slug = get_repo_slug(repo)
                        slug_to_repo[(lang, slug)] = repo
                        dataset_order.append((lang, slug))
        except Exception:
            pass

    discovered: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    # First preserve dataset order if available
    for lang, slug in dataset_order:
        target_dir = benchmarks_dir / lang / slug
        if target_dir.is_dir():
            repo_name = slug_to_repo.get((lang, slug), slug)
            discovered.append({
                "repo": repo_name,
                "language": lang,
                "slug": slug,
                "path": target_dir,
            })
            seen.add((lang, slug))

    # Also pick up any additional directories present under benchmarks_dir/<lang>/<slug>
    if benchmarks_dir.exists():
        for lang_dir in sorted(benchmarks_dir.iterdir()):
            if not lang_dir.is_dir() or lang_dir.name.startswith("."):
                continue
            lang = lang_dir.name
            for slug_dir in sorted(lang_dir.iterdir()):
                if not slug_dir.is_dir() or slug_dir.name.startswith("."):
                    continue
                slug = slug_dir.name
                if (lang, slug) in seen:
                    continue
                repo_name = slug_to_repo.get((lang, slug), slug.replace("_", "/", 1))
                discovered.append({
                    "repo": repo_name,
                    "language": lang,
                    "slug": slug,
                    "path": slug_dir,
                })
                seen.add((lang, slug))

    return discovered


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Index all 60 repositories from RepoQA into Qdrant."
    )
    parser.add_argument(
        "--benchmarks-dir",
        type=Path,
        default=REPO_ROOT / ".benchmarks/repoqa",
        help="Base directory containing unpacked repositories.",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=REPO_ROOT / "artifacts/repoqa/repoqa.json.gz",
        help="Path to repoqa.json.gz (fallback if repo needs unpacking).",
    )
    parser.add_argument(
        "--reindex",
        action="store_true",
        default=False,
        help="Force re-indexing even if collection already exists with items.",
    )
    parser.add_argument(
        "--max-input-chars",
        type=int,
        default=1200,
        help="Max input chars for embedding (default: 1200).",
    )
    parser.add_argument(
        "--languages",
        nargs="+",
        default=None,
        help="Optional subset of languages to index (e.g. python cpp). Default: all.",
    )
    parser.add_argument(
        "--repos",
        nargs="+",
        default=None,
        help="Optional subset of repositories or slugs to index (default: all 60).",
    )
    args = parser.parse_args()

    all_repos = discover_repos(args.benchmarks_dir, args.dataset)
    if not all_repos:
        print(f"Error: no unpacked repositories found in {args.benchmarks_dir}", file=sys.stderr)
        return 1

    repos_to_process = all_repos
    if args.languages:
        lang_set = set(args.languages)
        repos_to_process = [r for r in repos_to_process if r["language"] in lang_set]

    if args.repos:
        repo_set = set(args.repos)
        repos_to_process = [
            r for r in repos_to_process
            if r["repo"] in repo_set or r["slug"] in repo_set
        ]
        if not repos_to_process:
            print(f"Error: none of {args.repos} matched discovered repositories", file=sys.stderr)
            return 1

    base_config = ConfigLoader().load(None)

    dataset_cache: dict[str, Any] | None = None

    def get_dataset_entry(lang: str, repo_name: str) -> dict[str, Any] | None:
        nonlocal dataset_cache
        if dataset_cache is None:
            if not args.dataset.exists():
                return None
            with gzip.open(args.dataset, "rt", encoding="utf-8") as f:
                dataset_cache = json.load(f)
        for entry in dataset_cache.get(lang, []):
            if entry.get("repo") == repo_name:
                return entry
        return None

    print(f"Starting Qdrant indexing for {len(repos_to_process)} repositories...")
    print(
        f"Config: symbol_chunks=True, symbol_body=True, max_input_chars={args.max_input_chars}, reindex={args.reindex}\n"
    )

    results: list[dict[str, Any]] = []
    total_start = time.perf_counter()

    for idx, item in enumerate(repos_to_process, 1):
        repo_name = item["repo"]
        lang = item["language"]
        target_dir = item["path"]

        print(f"[{idx:2d}/{len(repos_to_process)}] Processing `{repo_name}` ({lang})...", flush=True)

        # Ensure repo directory is unpacked
        if not target_dir.exists() or not any(target_dir.iterdir()):
            entry = get_dataset_entry(lang, repo_name)
            if entry:
                print(f"  Unpacking `{repo_name}` to {target_dir}...", flush=True)
                unpack_repo(entry, target_dir)
            else:
                print(f"  Error: `{repo_name}` not found in dataset and target dir empty!", file=sys.stderr)
                continue

        # Resolve target Qdrant collection configuration
        target_config = replace(
            base_config,
            root=target_dir.resolve(),
            scanner=replace(
                base_config.scanner,
                symbol_chunks=True,
                line_chunks=False,
                symbol_body=True,
                file_summary_chunks=True,
                file_manifest_chunks=True,
            ),
            embedding=replace(base_config.embedding, max_input_chars=args.max_input_chars),
            cross_encoder_rerank=replace(
                base_config.cross_encoder_rerank,
                url="http://127.0.0.1:18081/v1/rerank",
            ),
        )
        target_config = scope_relative_repo_artifacts(target_config)
        target_config = IndexCollectionResolver().resolve(target_config)

        # Check if already indexed with > 0 items (unless --reindex is passed)
        step_start = time.perf_counter()
        already_indexed = False
        cached_items = 0

        if not args.reindex:
            vs = make_vector_store(target_config)
            try:
                if vs.exists():
                    cached_items = vs.count_items()
                    if cached_items > 0:
                        already_indexed = True
            except Exception:
                already_indexed = False
            finally:
                close_vector_store(vs)

        if already_indexed:
            duration = time.perf_counter() - step_start
            print(f"  [Index] Skipping: collection '{target_config.storage.qdrant.collection}' already exists with {cached_items} items.")
            print(f"  Result: {cached_items} items (Cached) in {duration:.2f}s\n", flush=True)
            results.append({
                "repo": repo_name,
                "language": lang,
                "total_items": cached_items,
                "duration": duration,
                "status": "Cached",
                "collection": target_config.storage.qdrant.collection,
            })
            continue

        # Index repository
        config, idx_time = index_repo(
            target_dir=target_dir,
            base_config=base_config,
            symbol_chunks=True,
            symbol_body=True,
            reindex=args.reindex,
            max_input_chars=args.max_input_chars,
        )
        elapsed_step = time.perf_counter() - step_start

        # Measure item count in Qdrant
        vs = make_vector_store(config)
        total_items = vs.count_items()
        close_vector_store(vs)

        was_reused = idx_time == 0.0
        duration = idx_time if not was_reused else elapsed_step

        status = "Cached" if was_reused else "Indexed"
        print(f"  Result: {total_items} items ({status}) in {duration:.2f}s\n", flush=True)

        results.append({
            "repo": repo_name,
            "language": lang,
            "total_items": total_items,
            "duration": duration,
            "status": status,
            "collection": config.storage.qdrant.collection,
        })

    total_time = time.perf_counter() - total_start

    # Output formatted table
    col_repo = max(max(len(r["repo"]) for r in results), 10)
    col_lang = max(max(len(r["language"]) for r in results), 8)
    col_items = 28  # "Total items indexed in Qdrant"
    col_dur = 26    # "Indexing duration (seconds)"

    header = (
        f"{'#':<3} | {'Repo':<{col_repo}} | {'Language':<{col_lang}} | "
        f"{'Total items indexed in Qdrant':>{col_items}} | {'Indexing duration (seconds)':>{col_dur}}"
    )
    divider = "-" * len(header)
    double_divider = "=" * len(header)

    print("\n" + double_divider)
    print("                      QDRANT INDEXING SUMMARY TABLE")
    print(double_divider)
    print(header)
    print(divider)

    total_items_sum = 0
    total_idx_duration = 0.0

    for idx, r in enumerate(results, 1):
        total_items_sum += r["total_items"]
        total_idx_duration += r["duration"]
        dur_str = f"{r['duration']:.2f}"
        if r["status"] == "Cached":
            dur_str += " (cached)"
        print(
            f"{idx:<3} | {r['repo']:<{col_repo}} | {r['language']:<{col_lang}} | "
            f"{r['total_items']:>{col_items}} | {dur_str:>{col_dur}}"
        )

    print(divider)
    print(
        f"{'Total':<3} | {'':<{col_repo}} | {'':<{col_lang}} | "
        f"{total_items_sum:>{col_items}} | {f'{total_idx_duration:.2f}':>{col_dur}}"
    )
    print(double_divider)
    print(f"Total run time: {total_time:.2f}s across {len(results)} repositories.")

    all_ok = len(results) == len(repos_to_process) and all(r["total_items"] > 0 for r in results)
    if all_ok:
        print("✓ All repositories successfully verified with > 0 indexed items in Qdrant.")
        return 0
    else:
        print("✗ Warning: Some repositories failed or have 0 items.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
