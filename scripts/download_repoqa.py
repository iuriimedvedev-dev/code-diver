#!/usr/bin/env python3
"""Download RepoQA dataset and inspect repositories and needle samples."""

from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import ssl
import sys
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_URL = (
    "https://github.com/evalplus/repoqa_release/releases/download/2024-06-23/repoqa-2024-06-23.json.gz"
)
DEFAULT_OUTPUT = Path("artifacts/repoqa/repoqa.json.gz")


def get_ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    try:
        return ssl.create_default_context()
    except Exception:
        return ssl._create_unverified_context()


def download_file(url: str, dest_path: Path, force: bool = False) -> int:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if dest_path.exists() and not force:
        size = dest_path.stat().st_size
        if size > 0:
            print(f"File already exists at {dest_path} ({size:,} bytes). Skipping download (use --force to overwrite).")
            return size

    print(f"Downloading from: {url}")
    print(f"Saving to: {dest_path}")
    ctx = get_ssl_context()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; code-diver/1.0)"})

    tmp_path = dest_path.with_suffix(".tmp")
    try:
        with urllib.request.urlopen(req, context=ctx) as response, open(tmp_path, "wb") as out_file:
            shutil.copyfileobj(response, out_file, length=64 * 1024)
        tmp_path.replace(dest_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    file_size = dest_path.stat().st_size
    print(f"Downloaded successfully: {file_size:,} bytes ({file_size / (1024 * 1024):.2f} MB)")
    return file_size


def inspect_dataset(data_path: Path) -> None:
    print(f"\n--- Loading and Verifying {data_path} ---")
    with gzip.open(data_path, "rt", encoding="utf-8") as f:
        data: dict[str, list[dict[str, Any]]] = json.load(f)

    languages = list(data.keys())
    print(f"Dataset languages: {languages}")

    # Extract repositories for python and java
    python_repos = [repo_entry["repo"] for repo_entry in data.get("python", [])]
    java_repos = [repo_entry["repo"] for repo_entry in data.get("java", [])]

    print("\n=== Python Repositories ({} repos) ===".format(len(python_repos)))
    for idx, repo in enumerate(python_repos, 1):
        print(f"  {idx:2d}. {repo}")

    print("\n=== Java Repositories ({} repos) ===".format(len(java_repos)))
    for idx, repo in enumerate(java_repos, 1):
        print(f"  {idx:2d}. {repo}")

    # Total needles
    needle_counts: dict[str, int] = {}
    total_needles = 0
    for lang, repos in data.items():
        count = sum(len(repo_entry.get("needles", [])) for repo_entry in repos)
        needle_counts[lang] = count
        total_needles += count

    print("\n=== Needle Counts by Language ===")
    for lang, count in needle_counts.items():
        print(f"  {lang:<12}: {count:4d} needles ({len(data[lang])} repos)")
    print(f"  {'-'*24}")
    print(f"  {'Total':<12}: {total_needles:4d} needles across all {len(languages)} languages")
    py_java_total = needle_counts.get("python", 0) + needle_counts.get("java", 0)
    print(f"  {'Python+Java':<12}: {py_java_total:4d} needles")

    # Sample needle inspection
    sample_needle: dict[str, Any] | None = None
    sample_repo: str = ""
    sample_lang: str = ""

    if data.get("python") and data["python"][0].get("needles"):
        sample_lang = "python"
        sample_repo = data["python"][0]["repo"]
        sample_needle = data["python"][0]["needles"][0]
    elif total_needles > 0:
        for lang, repos in data.items():
            for repo_entry in repos:
                if repo_entry.get("needles"):
                    sample_lang = lang
                    sample_repo = repo_entry["repo"]
                    sample_needle = repo_entry["needles"][0]
                    break
            if sample_needle:
                break

    print("\n=== Sample Needle Inspection ===")
    if sample_needle:
        print(f"Language : {sample_lang}")
        print(f"Repo     : {sample_repo}")
        print(f"Function : {sample_needle.get('name')}")
        print(f"Path     : {sample_needle.get('path')}")
        print(f"Lines    : {sample_needle.get('start_line')} - {sample_needle.get('end_line')}")
        print("Description:")
        print(f"  {sample_needle.get('description')}")
        print("\nFull Needle Sample JSON:")
        print(json.dumps(sample_needle, indent=2))
    else:
        print("No needles found in dataset.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Download RepoQA benchmark dataset and inspect contents.")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"Download URL (default: {DEFAULT_URL})")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Destination path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument("--force", action="store_true", help="Force re-download even if destination exists.")
    args = parser.parse_args()

    file_size = download_file(args.url, args.output, force=args.force)
    if file_size <= 0:
        print("Error: Downloaded file is empty.", file=sys.stderr)
        return 1

    inspect_dataset(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
