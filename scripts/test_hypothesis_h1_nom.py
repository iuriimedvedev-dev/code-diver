#!/usr/bin/env python3
"""Test Hypothesis H1 on rust-bakery/nom needle 1 (i16_tests in src/number/streaming.rs).

1. Loads nom config & vector store.
2. Queries vector strategy with limit=60.
3. Compares standard deduplication vs diversified deduplication.
4. Checks if src/number/streaming.rs appears in candidates and its rank.
"""

from __future__ import annotations

import gzip
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from code_diver.cli import make_embedding_provider, make_vector_store
from code_diver.config import ConfigLoader
from code_diver.strategies.retrieval_strategy_factory import RetrievalStrategyFactory
from scripts.benchmark_repoqa import dedupe_files, index_repo, normalize_path


def load_dataset() -> dict[str, Any]:
    dataset_path = PROJECT_ROOT / "artifacts" / "repoqa" / "repoqa.json.gz"
    with gzip.open(dataset_path, "rt", encoding="utf-8") as f:
        return json.load(f)


def get_nom_needle1(dataset: dict[str, Any]) -> dict[str, Any]:
    for repo in dataset.get("rust", []):
        if repo.get("repo") == "rust-bakery/nom":
            return repo["needles"][1]
    raise ValueError("rust-bakery/nom needle 1 not found in dataset")


def select_diversified_candidates(search_results: list[Any], max_chunks_per_file: int = 3, max_files: int = 8) -> list[str]:
    file_counts: dict[str, int] = {}
    candidates: list[str] = []
    for r in search_results:
        fpath = normalize_path(r.item.path)
        count = file_counts.get(fpath, 0)
        if count < max_chunks_per_file:
            file_counts[fpath] = count + 1
            if fpath not in candidates:
                candidates.append(fpath)
                if len(candidates) >= max_files:
                    break
    return candidates


def main() -> None:
    # 1. Load nom needle 1 metadata
    dataset = load_dataset()
    needle = get_nom_needle1(dataset)
    query = needle["description"].strip()
    target_file = normalize_path(needle["path"])
    target_symbol = needle.get("name")

    print("=" * 80)
    print("HYPOTHESIS H1 TEST: rust-bakery/nom needle 1")
    print("=" * 80)
    print(f"Target File  : {target_file}")
    print(f"Target Symbol: {target_symbol}")
    print(f"Query (first 100 chars): {query[:100]}...\n")

    # 1. Load nom config & vector store
    nom_dir = (PROJECT_ROOT / ".benchmarks/repoqa/rust/rust_bakery_nom").resolve()
    base_cfg = ConfigLoader().load(None)
    config, _ = index_repo(
        target_dir=nom_dir,
        base_config=base_cfg,
        symbol_chunks=True,
        symbol_body=True,
        reindex=False,
        max_input_chars=1200,
    )
    vs = make_vector_store(config)
    provider = make_embedding_provider(config, vs.metadata())
    strategy = RetrievalStrategyFactory().create("vector", config, provider, vs)

    # 2. Query vector strategy with limit=60
    limit = 60
    search_results = strategy.search(query, limit=limit)
    print(f"Retrieved {len(search_results)} search results with limit={limit}.\n")

    # Raw chunk inspection for target file
    matching_chunks = [
        (idx + 1, r)
        for idx, r in enumerate(search_results)
        if normalize_path(r.item.path) == target_file
    ]
    if matching_chunks:
        first_chunk_rank, first_chunk = matching_chunks[0]
        print(f"Target file `{target_file}` first appears at chunk rank: #{first_chunk_rank}")
        print(f"  First matching chunk: score={first_chunk.score:.4f}, title={getattr(first_chunk.item, 'title', '')}, lines={first_chunk.item.start_line}-{first_chunk.item.end_line}")
        print(f"  Total chunks for target in top {limit}: {len(matching_chunks)}")
    else:
        print(f"Target file `{target_file}` did NOT appear in top {limit} raw chunks!")

    # Distribution of files in top 60 chunks
    chunk_counts = Counter(normalize_path(r.item.path) for r in search_results)
    print("\nChunk distribution by file in top 60:")
    for fpath, cnt in chunk_counts.most_common():
        marker = " <-- TARGET" if fpath == target_file else ""
        print(f"  {fpath:30s}: {cnt:2d} chunks{marker}")

    # 3. Compare Standard Deduplication vs Diversified Deduplication
    std_candidates_all = dedupe_files([r.item.path for r in search_results])
    std_candidates_top8 = std_candidates_all[:8]

    div_candidates_top8 = select_diversified_candidates(
        search_results, max_chunks_per_file=3, max_files=8
    )

    print("\n" + "=" * 80)
    print("3. COMPARISON: Standard Deduplication vs Diversified Deduplication")
    print("=" * 80)
    print("\nStandard Deduplication (Top 8 files):")
    for idx, fpath in enumerate(std_candidates_top8, 1):
        marker = " <-- TARGET" if fpath == target_file else ""
        print(f"  Rank #{idx}: {fpath}{marker}")

    print("\nDiversified Deduplication (max_chunks_per_file=3, max_files=8):")
    for idx, fpath in enumerate(div_candidates_top8, 1):
        marker = " <-- TARGET" if fpath == target_file else ""
        print(f"  Rank #{idx}: {fpath}{marker}")

    # 4. Answers to prompt questions
    std_rank = std_candidates_top8.index(target_file) + 1 if target_file in std_candidates_top8 else None
    div_rank = div_candidates_top8.index(target_file) + 1 if target_file in div_candidates_top8 else None

    print("\n" + "=" * 80)
    print("4. SUMMARY & VERIFICATION")
    print("=" * 80)
    print(f"Does `{target_file}` appear in standard candidates (top 8)? {target_file in std_candidates_top8} (Rank: #{std_rank})")
    print(f"Does `{target_file}` appear in diversified candidates (top 8)? {target_file in div_candidates_top8} (Rank: #{div_rank})")

    # Also check what happens at limit=25 (the default limit)
    res_25 = search_results[:25]
    std_25 = dedupe_files([r.item.path for r in res_25])[:8]
    div_25 = select_diversified_candidates(res_25, max_chunks_per_file=3, max_files=8)
    print(f"\nFor comparison with limit=25:")
    print(f"  Standard candidates (limit=25):    {std_25}")
    print(f"  Diversified candidates (limit=25): {div_25}")
    print(f"  Target in limit=25? {target_file in std_25}")


if __name__ == "__main__":
    main()
