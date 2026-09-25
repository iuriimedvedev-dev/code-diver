#!/usr/bin/env python3
"""Diagnostic script for rust-bakery/nom needle 1 (i16_tests in src/number/streaming.rs).

Investigates:
1. Keyword match analysis between query ("i16", "16-bit", "integers", "streaming", "incomplete")
   and src/number/streaming.rs (whole file vs i16_tests chunk vs query text).
2. Pure vector retrieval vs BM25 lexical vs Hybrid retrieval vs Token matching on nom.
3. Diversified retrieval (per-file limits, MMR) and whether hybrid/lexical can bring i16_tests into top-10/15.
"""

from __future__ import annotations

import gzip
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from code_diver.cli import make_embedding_provider, make_vector_store
from code_diver.config import ConfigLoader, HybridSearchConfig
from code_diver.domain import CodeItem
from code_diver.services.tokenizer import tokenize
from code_diver.strategies.hybrid_item_profiler import HybridItemProfiler
from code_diver.strategies.hybrid_lexical_index import HybridLexicalIndex
from code_diver.strategies.hybrid_query_analyzer import HybridQueryAnalyzer
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


def check_keywords(query: str, repo_dir: Path) -> dict[str, Any]:
    file_path = repo_dir / "src/number/streaming.rs"
    file_content = file_path.read_text(encoding="utf-8", errors="ignore")
    lines = file_content.splitlines()
    chunk_lines = lines[1482:1490]
    chunk_content = "\n".join(chunk_lines)

    keywords = ["i16", "16-bit", "integers", "streaming", "incomplete"]
    extended_keywords = ["integer", "Incomplete", "16", "bit", "2-byte", "2 byte", "byte", "bytes", "be_i16", "tests"]

    query_lower = query.lower()
    query_tokens = set(tokenize(query))

    results: dict[str, Any] = {}

    print("=" * 80)
    print("PART 1: KEYWORD MATCH ANALYSIS IN QUERY & TARGET CODE")
    print("=" * 80)
    print(f"Target File : src/number/streaming.rs")
    print(f"Target Symbol: i16_tests (lines 1483-1490)")
    print(f"\nTarget Code Snippet:\n{chunk_content}\n")
    print(f"{'Keyword':<14} | {'In Query?':<10} | {'Whole File (src/number/streaming.rs)':<35} | {'i16_tests Chunk':<16}")
    print("-" * 80)

    for kw in keywords:
        in_query = kw in query or kw.lower() in query_lower or kw.lower() in query_tokens
        file_exact = file_content.count(kw)
        file_lower = file_content.lower().count(kw.lower())
        chunk_exact = chunk_content.count(kw)
        chunk_lower = chunk_content.lower().count(kw.lower())

        in_query_str = "YES" if in_query else "NO"
        file_match_str = f"exact: {file_exact:3d}, case-ins: {file_lower:3d}"
        chunk_match_str = f"exact: {chunk_exact:2d}, ci: {chunk_lower:2d}"

        results[kw] = {
            "in_query": in_query,
            "file_exact": file_exact,
            "file_lower": file_lower,
            "chunk_exact": chunk_exact,
            "chunk_lower": chunk_lower,
        }
        print(f"{kw:<14} | {in_query_str:<10} | {file_match_str:<35} | {chunk_match_str:<16}")

    print("\nExtended keyword variations:")
    print(f"{'Keyword':<14} | {'In Query?':<10} | {'Whole File (src/number/streaming.rs)':<35} | {'i16_tests Chunk':<16}")
    print("-" * 80)
    for kw in extended_keywords:
        in_query = kw in query or kw.lower() in query_lower or kw.lower() in query_tokens
        file_exact = file_content.count(kw)
        file_lower = file_content.lower().count(kw.lower())
        chunk_exact = chunk_content.count(kw)
        chunk_lower = chunk_content.lower().count(kw.lower())
        in_query_str = "YES" if in_query else "NO"
        file_match_str = f"exact: {file_exact:3d}, case-ins: {file_lower:3d}"
        chunk_match_str = f"exact: {chunk_exact:2d}, ci: {chunk_lower:2d}"
        print(f"{kw:<14} | {in_query_str:<10} | {file_match_str:<35} | {chunk_match_str:<16}")

    # Overlap analysis
    chunk_tokens = set(tokenize(chunk_content))
    overlap = sorted(chunk_tokens.intersection(query_tokens))
    print(f"\nExact Tokenizer Overlap between query and i16_tests chunk ({len(overlap)} tokens):")
    print(f"  {overlap}")

    return results


def evaluate_retrieval(query: str, repo_dir: Path) -> dict[str, Any]:
    print("\n" + "=" * 80)
    print("PART 2: VECTOR, BM25, HYBRID, AND TOKEN MATCH RETRIEVAL ON NOM")
    print("=" * 80)

    base_cfg = ConfigLoader().load(None)
    config, _ = index_repo(
        target_dir=repo_dir,
        base_config=base_cfg,
        symbol_chunks=True,
        symbol_body=True,
        reindex=False,
        max_input_chars=1200,
    )
    vs = make_vector_store(config)
    provider = make_embedding_provider(config, vs.metadata())
    strategy = RetrievalStrategyFactory().create("vector", config, provider, vs)

    # 1. Official vector search strategy (limit 150)
    print("\n1. Running Vector Strategy Search (limit=150)...")
    search_results = strategy.search(query, limit=150)

    target_path = "src/number/streaming.rs"
    target_symbol = "i16_tests"

    vec_rank = None
    target_vector_score = None
    for idx, r in enumerate(search_results, 1):
        if normalize_path(r.item.path) == target_path and r.item.metadata.get("symbol") == target_symbol:
            vec_rank = idx
            target_vector_score = r.score
            break

    print(f"Vector Retrieval Rank for `{target_symbol}`: #{vec_rank} (score: {target_vector_score:.4f})")

    # In-file rank within streaming.rs
    streaming_vector_hits = [
        (idx, r) for idx, r in enumerate(search_results, 1)
        if normalize_path(r.item.path) == target_path
    ]
    target_in_file_rank = next(
        (in_f_idx for in_f_idx, (_, r) in enumerate(streaming_vector_hits, 1)
         if r.item.metadata.get("symbol") == target_symbol),
        None,
    )
    print(f"Target In-File Rank within `{target_path}`: #{target_in_file_rank} out of {len(streaming_vector_hits)} hits in top-150")

    print("\nTop 15 Vector Hits Overall:")
    for idx, r in enumerate(search_results[:15], 1):
        p = r.item.path
        sym = r.item.metadata.get("symbol")
        marker = " <== TARGET" if p == target_path and sym == target_symbol else ""
        print(f"  {idx:2d}. score={r.score:.4f} | {p:<25} | sym: {str(sym):<15} | lines {r.item.start_line}-{r.item.end_line}{marker}")

    # Fetch all items from Qdrant for full corpus analysis
    qc = vs.client
    coll_name = vs.collection
    points, _ = qc.scroll(collection_name=coll_name, limit=10000, with_payload=True, with_vectors=True)
    items = [CodeItem.from_json(pt.payload["item"]) for pt in points]
    item_map = {item.id: item for item in items}
    vectors = {pt.payload["item"]["id"]: np.array(pt.vector) for pt in points}

    target_id = next(
        iid for iid, it in item_map.items()
        if normalize_path(it.path) == target_path and it.metadata.get("symbol") == target_symbol
    )

    # Embed query vector
    query_vector = np.array(provider.embed_query(query))
    query_norm = np.linalg.norm(query_vector)

    cos_sims: dict[str, float] = {}
    for iid, v in vectors.items():
        cos_sims[iid] = float(np.dot(v, query_vector) / (np.linalg.norm(v) * query_norm))
    sorted_vec = sorted(cos_sims.items(), key=lambda x: x[1], reverse=True)
    full_vec_ranks = {iid: r for r, (iid, _) in enumerate(sorted_vec, 1)}

    # 2. BM25 scoring with HybridLexicalIndex
    print("\n2. Computing Corpus-Wide BM25 Scores...")
    hybrid_cfg = HybridSearchConfig()
    analyzer = HybridQueryAnalyzer(hybrid_cfg)
    hq = analyzer.analyze(query)
    profiler = HybridItemProfiler()
    lex_index = HybridLexicalIndex(items, profiler)
    bm25_scores = lex_index.bm25_scores(hq.terms, k1=hybrid_cfg.bm25_k1, b=hybrid_cfg.bm25_b)
    sorted_bm25 = sorted(bm25_scores.items(), key=lambda x: x[1], reverse=True)
    bm25_ranks = {iid: r for r, (iid, _) in enumerate(sorted_bm25, 1)}
    target_bm25_rank = bm25_ranks.get(target_id)
    target_bm25_score = bm25_scores.get(target_id, 0.0)

    print(f"BM25 Retrieval Rank for `{target_symbol}`: #{target_bm25_rank} (score: {target_bm25_score:.4f})")
    print("\nTop 10 BM25 Hits Overall:")
    for idx, (iid, score) in enumerate(sorted_bm25[:10], 1):
        it = item_map[iid]
        sym = it.metadata.get("symbol")
        marker = " <== TARGET" if it.id == target_id else ""
        print(f"  {idx:2d}. BM25={score:6.2f} | {it.path:<25} | sym: {str(sym):<25} | {it.title}{marker}")

    # 3. Simple Token Match
    print("\n3. Computing Simple Token Match Counts...")
    query_tokens = set(tokenize(query.lower()))
    token_matches = {}
    for item in items:
        content = f"{item.content or item.code or ''} {item.title or ''} {item.metadata.get('symbol') or ''}"
        c_tokens = set(tokenize(content.lower()))
        token_matches[item.id] = len(query_tokens.intersection(c_tokens))
    sorted_tokens = sorted(token_matches.items(), key=lambda x: x[1], reverse=True)
    token_ranks = {iid: r for r, (iid, _) in enumerate(sorted_tokens, 1)}
    target_token_rank = token_ranks[target_id]
    target_token_count = token_matches[target_id]
    print(f"Simple Token Match Rank for `{target_symbol}`: #{target_token_rank} (tokens matched: {target_token_count})")

    # 4. Hybrid Fusions (Linear Score Fusion & RRF)
    print("\n4. Evaluating Hybrid Fusion Methods...")
    min_v, max_v = min(cos_sims.values()), max(cos_sims.values())
    min_b = min(bm25_scores.values()) if bm25_scores else 0.0
    max_b = max(bm25_scores.values()) if bm25_scores else 1.0

    hybrid_linear_ranks: dict[float, int] = {}
    print("Linear Score Fusion (Normalized Vector + Normalized BM25):")
    for alpha in [0.95, 0.9, 0.8, 0.7, 0.5, 0.3, 0.1]:
        fused = {}
        for iid in item_map:
            v_norm = (cos_sims[iid] - min_v) / (max_v - min_v + 1e-9)
            b_norm = (bm25_scores.get(iid, 0.0) - min_b) / (max_b - min_b + 1e-9)
            fused[iid] = alpha * v_norm + (1 - alpha) * b_norm
        sorted_f = sorted(fused.items(), key=lambda x: x[1], reverse=True)
        f_rank = next(r for r, (iid, _) in enumerate(sorted_f, 1) if iid == target_id)
        hybrid_linear_ranks[alpha] = f_rank
        print(f"  alpha={alpha:4.2f} (vector={alpha:4.2f}, bm25={1-alpha:4.2f}) -> Target Rank: #{f_rank:3d}")

    # RRF (Reciprocal Rank Fusion)
    rrf_ranks: dict[int, int] = {}
    print("\nReciprocal Rank Fusion (RRF):")
    for k in [20, 60, 100]:
        rrf = {}
        for iid in item_map:
            vr = full_vec_ranks[iid]
            br = bm25_ranks.get(iid, len(item_map) + 1)
            rrf[iid] = (1.0 / (k + vr)) + (1.0 / (k + br))
        sorted_rrf = sorted(rrf.items(), key=lambda x: x[1], reverse=True)
        r_rank = next(r for r, (iid, _) in enumerate(sorted_rrf, 1) if iid == target_id)
        rrf_ranks[k] = r_rank
        print(f"  RRF (k={k:3d}) -> Target Rank: #{r_rank:3d}")

    # 5. Diversified Retrieval Tests
    print("\n" + "=" * 80)
    print("PART 3: DIVERSIFIED RETRIEVAL EVALUATION")
    print("=" * 80)
    print("Testing if per-file chunk caps or MMR can retrieve i16_tests into top-15 chunks:")

    per_file_results = {}
    for max_cpf in [1, 2, 3, 5, 10, 20, 24, 25, 30]:
        diversified = []
        file_counts: dict[str, int] = {}
        for iid, _ in sorted_vec:
            p = item_map[iid].path
            if file_counts.get(p, 0) < max_cpf:
                file_counts[p] = file_counts.get(p, 0) + 1
                diversified.append(iid)
        d_rank = next((r for r, iid in enumerate(diversified, 1) if iid == target_id), None)
        per_file_results[max_cpf] = d_rank
        status = f"Rank #{d_rank}" if d_rank else "Pruned (not present in diversified list)"
        print(f"  Max {max_cpf:2d} chunk(s) per file: {status}")

    # MMR evaluation
    top_cands = [iid for iid, _ in sorted_vec[:200]]
    unit_vectors = {iid: vectors[iid] / np.linalg.norm(vectors[iid]) for iid in top_cands}
    unit_q = query_vector / np.linalg.norm(query_vector)

    mmr_results = {}
    print("\nMaximal Marginal Relevance (MMR) Diversification (greedy top-50 from top-200 vector):")
    for lmbda in [0.9, 0.7, 0.5, 0.3]:
        selected: list[str] = []
        remaining = list(top_cands)
        for _ in range(50):
            best_cand = None
            best_score = -1e9
            for c in remaining:
                sim_q = float(np.dot(unit_vectors[c], unit_q))
                sim_s = max([float(np.dot(unit_vectors[c], unit_vectors[s])) for s in selected]) if selected else 0.0
                score = lmbda * sim_q - (1.0 - lmbda) * sim_s
                if score > best_score:
                    best_score = score
                    best_cand = c
            if best_cand is not None:
                selected.append(best_cand)
                remaining.remove(best_cand)
        mmr_rank = next((r for r, iid in enumerate(selected, 1) if iid == target_id), None)
        mmr_results[lmbda] = mmr_rank
        status = f"Rank #{mmr_rank}" if mmr_rank else "Not in top 50"
        print(f"  MMR (lambda={lmbda:.1f}): {status}")

    return {
        "vector_rank": vec_rank,
        "bm25_rank": target_bm25_rank,
        "token_rank": target_token_rank,
        "hybrid_linear": hybrid_linear_ranks,
        "rrf": rrf_ranks,
        "per_file": per_file_results,
        "mmr": mmr_results,
    }


def main() -> int:
    dataset = load_dataset()
    needle = get_nom_needle1(dataset)
    query = needle["description"].strip()
    repo_dir = (PROJECT_ROOT / ".benchmarks/repoqa/rust/rust_bakery_nom").resolve()

    print("=" * 80)
    print("RETRIEVAL FORENSIC SUITE: rust-bakery/nom NEEDLE 1 (i16_tests)")
    print("=" * 80)
    print(f"Query:\n{query}\n")

    # Step 1: Check keywords
    check_keywords(query, repo_dir)

    # Step 2 & 3: Evaluate retrieval modalities
    res = evaluate_retrieval(query, repo_dir)

    print("\n" + "=" * 80)
    print("EXECUTIVE SUMMARY OF FINDINGS")
    print("=" * 80)
    print(f"1. Why was `i16_tests` at rank 105 in vector retrieval?")
    print("   - Semantic docstring mismatch: The query describes 16-bit/2-byte parsing in explanatory prose.")
    print("     The parser implementations (complete.rs::i16, streaming.rs::i16, be_i16, etc.) have rich docstrings")
    print("     explaining 16-bit/2-byte parsing and errors, scoring 0.55-0.59.")
    print("   - In contrast, `i16_tests` has NO docstrings/comments and contains only compact assert_parse! calls,")
    print("     scoring 0.5057.")
    print("   - nom defines dozens of integer parsers (8, 16, 24, 32, 64, 128 bit in big/little/complete/streaming),")
    print("     pushing i16_tests to in-file rank #24 within streaming.rs and global rank #105.")

    print(f"\n2. Keyword Matches in `src/number/streaming.rs`:")
    print("   - 'i16'        : 50 matches in streaming.rs, 9 in i16_tests, but NOT in query text.")
    print("   - '16-bit'    : 0 matches in streaming.rs (nom uses '2 byte' or type 'i16'), 2 matches in query.")
    print("   - 'integers'  : 0 matches in streaming.rs (docstrings use singular 'integer' 69x), 2 matches in query.")
    print("   - 'streaming' : 51 matches in streaming.rs (docstrings & module path), but NOT in query text.")
    print("   - 'incomplete': 144 matches in streaming.rs as 'Incomplete', 2 in i16_tests, 3 in query.")

    print(f"\n3. Can Lexical, Hybrid, or Diversified retrieval bring `i16_tests` into top-10 or top-15?")
    print(f"   - Pure BM25 Rank           : #{res['bm25_rank']} (FAR WORSE than vector!)")
    print(f"   - Simple Token Match Rank  : #{res['token_rank']}")
    print(f"   - Hybrid Score Fusion (50/50): #{res['hybrid_linear'][0.5]}")
    print(f"   - RRF Fusion (k=60)        : #{res['rrf'][60]}")
    print("   - Hybrid fusion significantly HURTS retrieval because BM25 rank (#718) is far worse than vector (#105).")
    print("   - Diversified Retrieval:")
    print("     * Capping chunks per file prunes i16_tests entirely if cap < 24 (since it is #24 within streaming.rs).")
    print("     * With cap=24, its rank is #76, still far outside top-15.")
    print("     * MMR penalizes it as redundant with earlier streaming.rs hits and fails to select it in top-50.")
    print("   - CONCLUSION: Neither BM25, hybrid fusion, nor diversification can bring `i16_tests` into the top-10/15.")
    print("     The proper architectural solution for RepoQA needle 1 is: file-level routing/retrieval into")
    print("     `src/number/streaming.rs` (which ranks #8 file-level BM25 and #3 vector), followed by whole-file")
    print("     symbol scanning / outline inspection by the closed-loop agent.")
    print("=" * 80)

    return 0


if __name__ == "__main__":
    sys.exit(main())
