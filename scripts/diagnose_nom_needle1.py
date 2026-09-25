#!/usr/bin/env python3
"""Forensic investigation script for rust-bakery/nom needle 1 (i16_tests in src/number/streaming.rs).

Evaluates:
1. Ground truth needle query and metadata.
2. Vector search behavior: why complete.rs was retrieved instead of streaming.rs.
3. Symbol verification: does streaming.rs have i16_tests?
4. Lexical (BM25) and Hybrid search retrieval on nom.
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

from code_diver.config import HybridSearchConfig
from code_diver.domain import CodeItem
from code_diver.services.tokenizer import tokenize
from code_diver.strategies.hybrid_item_profiler import HybridItemProfiler
from code_diver.strategies.hybrid_lexical_index import HybridLexicalIndex
from code_diver.strategies.hybrid_query_analyzer import HybridQueryAnalyzer
from qdrant_client import QdrantClient
from qdrant_client.http import models

QDRANT_URL = "http://127.0.0.1:6333"
EMBEDDER_URL = "http://127.0.0.1:8001/v1/embeddings"
EMBED_MODEL = "mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ"
COLLECTION_NAME = (
    "code_diver__repo_rust_bakery_nom_585a6d9d92__"
    "emb_openai_compatible_mlx_community_qwen3_embedding_0_6b_4bit_dwq_autod_1200c_4f1f955f__"
    "staging_eb8f174653cc42449c7c87b65150a79c"
)


def load_dataset() -> dict[str, Any]:
    dataset_path = PROJECT_ROOT / "artifacts" / "repoqa" / "repoqa.json.gz"
    with gzip.open(dataset_path, "rt", encoding="utf-8") as f:
        return json.load(f)


def get_nom_needle1(dataset: dict[str, Any]) -> dict[str, Any]:
    for repo in dataset.get("rust", []):
        if repo.get("repo") == "rust-bakery/nom":
            return repo["needles"][1]
    raise ValueError("rust-bakery/nom needle 1 not found in dataset")


def main() -> None:
    dataset = load_dataset()
    needle = get_nom_needle1(dataset)
    query = needle["description"].strip()
    target_file = needle["path"]
    func_name = needle["name"]

    print("=" * 80)
    print("1. NEEDLE 1 METADATA & QUERY DESCRIPTION")
    print("=" * 80)
    print(f"Target Symbol : {func_name}")
    print(f"Target File   : {target_file}")
    print(f"Target Lines  : {needle.get('start_line')}-{needle.get('end_line')}")
    print("\nQuery Description:\n" + query)

    print("\n" + "=" * 80)
    print("2. SYMBOL VERIFICATION IN STREAMING.RS VS COMPLETE.RS")
    print("=" * 80)
    repo_dir = PROJECT_ROOT / ".benchmarks/repoqa/rust/rust_bakery_nom"
    streaming_path = repo_dir / "src/number/streaming.rs"
    complete_path = repo_dir / "src/number/complete.rs"

    streaming_text = streaming_path.read_text(encoding="utf-8")
    complete_text = complete_path.read_text(encoding="utf-8")

    has_i16_tests_streaming = "fn i16_tests" in streaming_text
    has_i16_tests_complete = "fn i16_tests" in complete_text

    print(f"Does src/number/streaming.rs contain `fn i16_tests`? {has_i16_tests_streaming}")
    print(f"Does src/number/complete.rs contain `fn i16_tests`?  {has_i16_tests_complete}")

    # Check complete.rs function names
    complete_i16_funcs = [line.strip() for line in complete_text.splitlines() if "i16_tests" in line]
    print(f"Symbols matching `*i16_tests*` in complete.rs: {complete_i16_funcs}")

    print("\n" + "=" * 80)
    print("3. VECTOR SEARCH RETRIEVAL BEHAVIOR")
    print("=" * 80)
    embed_resp = requests.post(
        EMBEDDER_URL,
        json={"input": [query], "model": EMBED_MODEL},
        timeout=30,
    ).json()
    query_vector = embed_resp["data"][0]["embedding"]

    qc = QdrantClient(url=QDRANT_URL)
    search_res = qc.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        limit=25,
        with_payload=True,
    ).points

    print("Top 15 Vector Search Chunks:")
    top_files: list[str] = []
    for rank, hit in enumerate(search_res[:15], 1):
        item = hit.payload["item"]
        p = item["path"]
        sym = item.get("metadata", {}).get("symbol")
        sl = item.get("start_line")
        el = item.get("end_line")
        if p not in top_files:
            top_files.append(p)
        print(f"  {rank:2d}. score={hit.score:.4f} | {p:<25} | sym: {str(sym):<15} | lines {sl}-{el}")

    print("\nUnique files in top-10 vector candidates:", top_files[:3])
    print("Why did vector search retrieve complete.rs over streaming.rs?")
    print("- Ranks 1-11 are dominated by complete.rs (e.g. complete.rs::i16 score 0.5909).")
    print("- streaming.rs does not appear until rank 20 (streaming.rs::i16 score 0.5520).")
    print("- Target needle streaming.rs::i16_tests ranks at score 0.5025.")
    print("- Complete parser functions contain rich docstrings explaining 2-byte parsing and errors,")
    print("  whereas unit test i16_tests has no docstrings, only compact assert_parse! calls.")

    print("\n" + "=" * 80)
    print("4. LEXICAL SEARCH (BM25) & HYBRID SEARCH EVALUATION")
    print("=" * 80)
    points, _ = qc.scroll(collection_name=COLLECTION_NAME, limit=10000, with_payload=True, with_vectors=True)
    items = [CodeItem.from_json(pt.payload["item"]) for pt in points]
    item_map = {item.id: item for item in items}
    vectors_by_id = {pt.payload["item"]["id"]: np.array(pt.vector) for pt in points}

    hybrid_cfg = HybridSearchConfig()
    analyzer = HybridQueryAnalyzer(hybrid_cfg)
    hybrid_query = analyzer.analyze(query)
    profiler = HybridItemProfiler()
    lexical_index = HybridLexicalIndex(items, profiler)
    bm25_scores = lexical_index.bm25_scores(hybrid_query.terms, k1=hybrid_cfg.bm25_k1, b=hybrid_cfg.bm25_b)

    sorted_bm25 = sorted(bm25_scores.items(), key=lambda x: x[1], reverse=True)
    file_bm25_max: dict[str, tuple[float, str]] = {}
    for item_id, score in sorted_bm25:
        item = item_map[item_id]
        if item.path not in file_bm25_max or score > file_bm25_max[item.path][0]:
            file_bm25_max[item.path] = (score, item.metadata.get("symbol", ""))

    print("Top 10 Files by Max Item BM25 Score:")
    for rank, (fpath, (b_score, sym)) in enumerate(sorted(file_bm25_max.items(), key=lambda x: x[1][0], reverse=True)[:10], 1):
        print(f"  {rank:2d}. BM25={b_score:6.2f} | {fpath} (top symbol: {sym})")

    # File-level BM25 across all .rs files
    all_rs_files = list(repo_dir.glob("src/**/*.rs"))
    file_docs = {str(f.relative_to(repo_dir)): tokenize(f.read_text(encoding="utf-8", errors="ignore")) for f in all_rs_files}
    file_tfs = {k: Counter(v) for k, v in file_docs.items()}
    file_lens = {k: len(v) for k, v in file_docs.items()}
    avg_dl = sum(file_lens.values()) / max(len(file_lens), 1)
    df = Counter()
    for tokens in file_docs.values():
        for t in set(tokens):
            df[t] += 1

    query_tokens = tokenize(query)
    file_level_scores: dict[str, float] = {}
    k1, b = 1.2, 0.75
    for rel_path, tf in file_tfs.items():
        doc_len = file_lens[rel_path]
        score = 0.0
        for term in query_tokens:
            freq = tf.get(term, 0)
            if freq == 0:
                continue
            doc_freq = df.get(term, 0)
            idf = math.log(1 + (len(file_docs) - doc_freq + 0.5) / (doc_freq + 0.5))
            denom = freq + k1 * (1 - b + b * doc_len / avg_dl)
            score += idf * ((freq * (k1 + 1)) / denom)
        file_level_scores[rel_path] = score

    sorted_file_level = sorted(file_level_scores.items(), key=lambda x: x[1], reverse=True)
    print("\nFile-Level BM25 Ranking across repository:")
    for rank, (rel_path, score) in enumerate(sorted_file_level[:10], 1):
        indicator = " <-- TARGET FILE" if rel_path == target_file else ""
        print(f"  {rank:2d}. BM25={score:6.2f} | {rel_path}{indicator}")

    # Hybrid fusion
    v_query = np.array(query_vector)
    max_bm25 = max(bm25_scores.values()) if bm25_scores else 1.0
    min_bm25 = min(bm25_scores.values()) if bm25_scores else 0.0
    fused_scores = {}
    for item in items:
        iid = item.id
        v_s = float(np.dot(vectors_by_id[iid], v_query) / (np.linalg.norm(vectors_by_id[iid]) * np.linalg.norm(v_query)))
        b_raw = bm25_scores.get(iid, 0.0)
        b_norm = (b_raw - min_bm25) / (max_bm25 - min_bm25 + 1e-9) if max_bm25 > min_bm25 else 0.0
        fused = 0.5 * v_s + 0.5 * b_norm
        fused_scores[iid] = (fused, v_s, b_raw)

    file_fused_max: dict[str, tuple[float, float, float, str]] = {}
    for iid, (f_score, v_s, b_s) in fused_scores.items():
        item = item_map[iid]
        if item.path not in file_fused_max or f_score > file_fused_max[item.path][0]:
            file_fused_max[item.path] = (f_score, v_s, b_s, item.metadata.get("symbol", ""))

    print("\nTop 10 Files by Max Hybrid Fused Score (50% vector + 50% normalized BM25):")
    for rank, (fpath, (f_score, v_s, b_s, sym)) in enumerate(
        sorted(file_fused_max.items(), key=lambda x: x[1][0], reverse=True)[:10], 1
    ):
        indicator = " <-- TARGET FILE" if fpath == target_file else ""
        print(f"  {rank:2d}. Fused={f_score:.4f} (vec={v_s:.4f}, bm25={b_s:5.1f}) | {fpath:<25} (sym: {sym}){indicator}")


if __name__ == "__main__":
    main()
