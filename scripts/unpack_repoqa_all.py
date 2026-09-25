#!/usr/bin/env python3
"""Unpack all 60 repositories across all 6 languages from artifacts/repoqa/repoqa.json.gz into .benchmarks/repoqa/<lang>/<slug>."""

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

from scripts.benchmark_repoqa import slugify_repo, unpack_repo
from scripts.benchmark_repoqa_agent_litellm import EVAL_REPOS_100

KNOWN_SLUGS: dict[str, str] = {r["repo"]: r["slug"] for r in EVAL_REPOS_100}


def get_repo_slug(repo_name: str) -> str:
    """Return directory slug for repository, respecting known benchmark slugs."""
    return KNOWN_SLUGS.get(repo_name, slugify_repo(repo_name))


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
        description="Unpack all 60 repositories from RepoQA into .benchmarks/repoqa/<lang>/<slug>"
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
        "--languages",
        nargs="+",
        default=None,
        help="Optional subset of languages to unpack (e.g. python java). Default is all.",
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

    # Collect entries to process
    repos_to_unpack: list[tuple[str, dict]] = []
    for lang, repos in dataset.items():
        if args.languages and lang not in args.languages:
            continue
        if isinstance(repos, list):
            for entry in repos:
                repos_to_unpack.append((lang, entry))

    print(
        f"Unpacking {len(repos_to_unpack)} repositories across "
        f"{len({lang for lang, _ in repos_to_unpack})} language(s) into {args.benchmarks_dir}...\n"
    )
    print(f"{'#':<4} {'Language':<12} {'Repository':<32} {'Slug':<32} {'Files':<8} {'Status':<8}")
    print("-" * 102)

    errors: list[str] = []
    total_files = 0

    for idx, (lang, entry) in enumerate(repos_to_unpack, 1):
        repo_name = entry.get("repo", "unknown")
        slug = get_repo_slug(repo_name)
        target_dir = args.benchmarks_dir / lang / slug

        try:
            expected_count = len(entry.get("content", {}))
            unpack_repo(entry, target_dir, force=args.force)
            disk_count = count_repo_files(target_dir)

            if disk_count != expected_count:
                errors.append(
                    f"{repo_name}: file count mismatch (expected {expected_count}, found {disk_count} on disk)"
                )
                status = f"MISMATCH ({disk_count}/{expected_count})"
            else:
                status = "OK"

            total_files += disk_count
            print(f"{idx:<4} {lang:<12} {repo_name:<32} {slug:<32} {disk_count:<8} {status:<8}")

        except Exception as e:
            errors.append(f"{repo_name}: {e}")
            print(f"{idx:<4} {lang:<12} {repo_name:<32} {slug:<32} {'-':<8} {'ERROR':<8}")

    print("-" * 102)
    if errors:
        print(f"\nCompleted with {len(errors)} error(s):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"\nAll {len(repos_to_unpack)} repositories successfully unpacked and verified!")
    print(f"Total files unpacked across all repos: {total_files}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
