#!/usr/bin/env python3
"""Pre-compute LLM purpose blurbs for all files in the 1065 eval candidate pools.

Two-phase approach:
1. Run H52 retrieval on all queries, collect unique file paths from top-34 candidates
2. Pre-compute purpose blurbs for those files (batched, cached to disk)

Usage:
  # Phase 1: collect unique file paths
  uv run python scripts/precompute_llm_purposes.py collect --config configs/intellij/intellij-h52-summary-head-first.yml --dataset datasets/intellij_eval_1000.answer_sets.jsonl --output /tmp/1065_candidate_paths.json

  # Phase 2: pre-compute blurbs for collected paths
  uv run python scripts/precompute_llm_purposes.py generate --input /tmp/1065_candidate_paths.json

  # Phase 1+2 combined (sequential)
  uv run python scripts/precompute_llm_purposes.py full --config configs/intellij/intellij-h52-summary-head-first.yml --dataset datasets/intellij_eval_1000.answer_sets.jsonl
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.code_diver.config.config_loader import ConfigLoader
from src.code_diver.providers.embedding_provider_builder import make_embedding_provider
from src.code_diver.services.dataset_loader import DatasetLoader
from src.code_diver.store.vector_store_factory import create_vector_store
from src.code_diver.strategies.retrieval_strategy_builder import make_retrieval_strategy
from src.code_diver.reranking import cross_encoder_document_builder as ce_builder

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def collect_candidate_paths(config_path: str, dataset_path: str, output_path: str, limit: int = 0) -> list[str]:
    """Run H52 retrieval on all queries and collect unique file paths from top-34 candidates."""
    config = ConfigLoader().load(Path(config_path))

    # Override the dataset
    config.evaluation.dataset = dataset_path

    # Create vector store
    logger.info("Creating vector store...")
    vector_store = create_vector_store(config)
    metadata = vector_store.metadata()
    provider = make_embedding_provider(config, metadata)

    # Create retrieval strategy
    logger.info("Creating retrieval strategy...")
    plugin_manager = None  # No plugin manager needed for basic retrieval
    strategy = make_retrieval_strategy(config, provider, vector_store)

    # Load dataset
    logger.info("Loading dataset...")
    loader = DatasetLoader()
    cases = loader.load(Path(dataset_path))
    if limit > 0:
        cases = cases[:limit]

    # Run retrieval on each query, collect unique paths
    all_paths: set[str] = set()
    total = len(cases)
    start = time.time()

    for i, case in enumerate(cases):
        query = case.query
        if plugin_manager:
            query = plugin_manager.prepare_query(query)
        # Search with top-34 candidates
        results = strategy.search(query, 34)
        for result in results:
            all_paths.add(result.item.path)
        if (i + 1) % 50 == 0:
            elapsed = time.time() - start
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            logger.info("Processed %d/%d queries (%.0f q/h), %d unique paths, %.1fs elapsed",
                       i + 1, total, rate * 3600, len(all_paths), elapsed)

    elapsed = time.time() - start
    logger.info("Collected %d unique paths from %d queries in %.1fs (%.2f q/s)",
               len(all_paths), total, elapsed, total / elapsed if elapsed > 0 else 0)

    # Save to file
    path_list = sorted(all_paths)
    with open(output_path, 'w') as f:
        json.dump({"paths": path_list, "total_queries": total, "elapsed_seconds": elapsed}, f)
    logger.info("Saved %d paths to %s", len(path_list), output_path)

    return path_list


def generate_purposes(input_path: str) -> dict[str, str | None]:
    """Pre-compute purpose blurbs for all paths in the input file."""
    with open(input_path) as f:
        data = json.load(f)
    paths = data["paths"]
    logger.info("Loaded %d paths from %s", len(paths), input_path)

    # Show current cache stats
    logger.info("Current disk cache has %d entries", len(ce_builder._purpose_disk_cache))

    # Pre-compute blurbs
    start = time.time()
    results = ce_builder.precompute_llm_purposes(paths)
    elapsed = time.time() - start

    # Summary
    success = sum(1 for v in results.values() if v is not None)
    failed = sum(1 for v in results.values() if v is None)
    logger.info("Pre-computed %d purposes in %.1fs (%.2f files/s): %d success, %d failed",
               len(results), elapsed, len(results) / elapsed if elapsed > 0 else 0,
               success, failed)

    return results


def main():
    parser = argparse.ArgumentParser(description="Pre-compute LLM purpose blurbs for 1065 eval")
    subparsers = parser.add_subparsers(dest="command")

    # collect
    collect_parser = subparsers.add_parser("collect", help="Collect unique file paths from retrieval")
    collect_parser.add_argument("--config", required=True, help="H52 config path")
    collect_parser.add_argument("--dataset", required=True, help="Eval dataset path")
    collect_parser.add_argument("--output", default="/tmp/1065_candidate_paths.json", help="Output path")
    collect_parser.add_argument("--limit", type=int, default=0, help="Limit queries (0 = all)")

    # generate
    gen_parser = subparsers.add_parser("generate", help="Pre-compute blurbs for collected paths")
    gen_parser.add_argument("--input", default="/tmp/1065_candidate_paths.json", help="Input path file")

    # full
    full_parser = subparsers.add_parser("full", help="Phase 1 + 2 combined")
    full_parser.add_argument("--config", required=True, help="H52 config path")
    full_parser.add_argument("--dataset", required=True, help="Eval dataset path")
    full_parser.add_argument("--output", default="/tmp/1065_candidate_paths.json", help="Output path")
    full_parser.add_argument("--limit", type=int, default=0, help="Limit queries (0 = all)")

    args = parser.parse_args()

    if args.command == "collect":
        collect_candidate_paths(args.config, args.dataset, args.output, args.limit)
    elif args.command == "generate":
        generate_purposes(args.input)
    elif args.command == "full":
        paths = collect_candidate_paths(args.config, args.dataset, args.output, args.limit)
        generate_purposes(args.output)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()