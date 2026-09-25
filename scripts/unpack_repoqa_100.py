#!/usr/bin/env python3
"""Unpack all 10 repositories from EVAL_REPOS_100 into .benchmarks/repoqa/<lang>/<slug>."""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

# Ensure repo root is in sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.benchmark_repoqa import unpack_repo
from scripts.benchmark_repoqa_agent_litellm import EVAL_REPOS_100


def count_repo_files(repo_dir: Path) -> int:
    """Count non-hidden files in repository directory."""
    if not repo_dir.exists():
        return 0
    return sum(
        1
        for p in repo_dir.rglob("*")
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(repo_dir).parts)
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Unpack EVAL_REPOS_100 into .benchmarks/repoqa/<lang>/<slug>"
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=REPO_ROOT / "artifacts/repoqa/repoqa.json.gz",
        help="Path to repoqa.json.gz dataset file.",
    )
    parser.add_argument(
        "--benchmarks-dir",
        type=Path,
        default=REPO_ROOT / ".benchmarks/repoqa",
        help="Target base directory for unpacked repositories.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Force re-unpacking files even if directory already exists.",
    )
    args = parser.parse_args()

    if not args.dataset.exists():
        print(f"Error: dataset file not found at {args.dataset}", file=sys.stderr)
        return 1

    print(f"Loading RepoQA dataset from {args.dataset}...")
    with gzip.open(args.dataset, "rt", encoding="utf-8") as f:
        dataset = json.load(f)

    # Index dataset by (lang, repo_name)
    dataset_index: dict[tuple[str, str], dict] = {}
    for lang, repos in dataset.items():
        if isinstance(repos, list):
            for entry in repos:
                repo_name = entry.get("repo")
                if repo_name:
                    dataset_index[(lang, repo_name)] = entry

    print(f"Unpacking {len(EVAL_REPOS_100)} repositories into {args.benchmarks_dir}...\n")
    print(f"{'#':<3} {'Language':<12} {'Repository':<26} {'Slug':<22} {'Files':<8} {'Status':<8}")
    print("-" * 85)

    errors = []
    total_files = 0

    for idx, item in enumerate(EVAL_REPOS_100, 1):
        lang = item["language"]
        repo_name = item["repo"]
        slug = item["slug"]
        target_dir = args.benchmarks_dir / lang / slug

        entry = dataset_index.get((lang, repo_name))
        if not entry:
            errors.append(f"{repo_name} ({lang}): Not found in dataset")
            print(f"{idx:<3} {lang:<12} {repo_name:<26} {slug:<22} {'-':<8} {'MISSING':<8}")
            continue

        try:
            expected_count = len(entry.get("content", {}))
            unpacked_count = unpack_repo(entry, target_dir, force=args.force)
            disk_count = count_repo_files(target_dir)

            if disk_count != expected_count:
                errors.append(
                    f"{repo_name}: file count mismatch (expected {expected_count}, found {disk_count} on disk)"
                )
                status = f"MISMATCH ({disk_count}/{expected_count})"
            else:
                status = "OK"

            total_files += disk_count
            print(f"{idx:<3} {lang:<12} {repo_name:<26} {slug:<22} {disk_count:<8} {status:<8}")

        except Exception as e:
            errors.append(f"{repo_name}: {e}")
            print(f"{idx:<3} {lang:<12} {repo_name:<26} {slug:<22} {'-':<8} {'ERROR':<8}")

    print("-" * 85)
    if errors:
        print(f"\nCompleted with {len(errors)} error(s):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"\nAll {len(EVAL_REPOS_100)} repositories successfully unpacked and verified!")
    print(f"Total files unpacked across all repos: {total_files}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
