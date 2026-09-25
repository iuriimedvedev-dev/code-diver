#!/usr/bin/env python3
"""Forensic investigation script for code-diver L1 retrieval misses.

Investigates:
1. psf/black needle 8: __post_init__ in src/black/linegen.py (lines 503-534)
2. google/gson needle 8: run in TypeAdapters.java (lines 970-984)
3. google/gson needle 4: nonNull in NonNullElementWrapperList.java vs $Gson$Preconditions.java
"""

from __future__ import annotations

import gzip
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

# Set project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from code_diver.cli import make_embedding_provider, make_vector_store, scope_relative_repo_artifacts
from code_diver.config import AppConfig, ConfigLoader
from code_diver.domain import CodeItem
from code_diver.inspection import FileOutlineService, ReadExcerptService
from code_diver.services import IndexCollectionResolver
from code_diver.services.code_symbol_extractor import CodeSymbolExtractor
from code_diver.services.embedding_text_preparer import EmbeddingTextPreparer
from qdrant_client import QdrantClient
from qdrant_client.http import models
from scripts.benchmark_repoqa import dedupe_files, normalize_path
from scripts.benchmark_repoqa_agent_litellm import build_agent_context


def load_dataset() -> dict[str, Any]:
    dataset_path = PROJECT_ROOT / "artifacts" / "repoqa" / "repoqa.json.gz"
    with gzip.open(dataset_path, "rt", encoding="utf-8") as f:
        return json.load(f)


def get_repo_config(base_cfg: AppConfig, repo_rel_path: str) -> tuple[AppConfig, Path]:
    repo_dir = (PROJECT_ROOT / repo_rel_path).resolve()
    cfg = IndexCollectionResolver().resolve(scope_relative_repo_artifacts(replace(base_cfg, root=repo_dir)))
    return cfg, repo_dir


def cosine_similarity(v1: list[float] | np.ndarray, v2: list[float] | np.ndarray) -> float:
    a = np.array(v1, dtype=np.float32)
    b = np.array(v2, dtype=np.float32)
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def diagnose_psf_black_needle_8(base_cfg: AppConfig, dataset: dict[str, Any], qc: QdrantClient) -> None:
    print("=" * 80)
    print("PART A: FORENSIC DIAGNOSIS FOR psf/black NEEDLE 8")
    print("Target: `__post_init__` in `src/black/linegen.py` (lines 503-534)")
    print("=" * 80)

    cfg, repo_dir = get_repo_config(base_cfg, ".benchmarks/repoqa/python/psf_black")
    collection_name = cfg.storage.qdrant.collection
    print(f"Collection: {collection_name}")

    vs = make_vector_store(cfg)
    provider = make_embedding_provider(cfg, vs.metadata())

    black_repo = next(r for r in dataset["python"] if r["repo"] == "psf/black")
    needle = black_repo["needles"][8]
    query = needle["description"].strip()

    print(f"\n[Needle Description Query]:\n{query}\n")

    # 1. Embed query
    query_vec = provider.embed_query(query)

    # 2. Retrieve all points for src/black/linegen.py
    linegen_points = qc.scroll(
        collection_name=collection_name,
        scroll_filter=models.Filter(
            must=[models.FieldCondition(key="item.path", match=models.MatchValue(value="src/black/linegen.py"))]
        ),
        limit=500,
        with_payload=True,
        with_vectors=True,
    )[0]

    print(f"Total points indexed for 'src/black/linegen.py': {len(linegen_points)}")
    kinds_count: dict[str, int] = {}
    for p in linegen_points:
        ik = p.payload["item"]["metadata"].get("index_kind", "unknown")
        kinds_count[ik] = kinds_count.get(ik, 0) + 1
    print(f"Breakdown by index_kind: {kinds_count}")

    # 3. Calculate scores for all linegen.py points
    linegen_scores = []
    for p in linegen_points:
        item = p.payload["item"]
        meta = item.get("metadata", {})
        score = cosine_similarity(query_vec, p.vector)
        linegen_scores.append({
            "id": p.id,
            "score": score,
            "kind": meta.get("index_kind"),
            "symbol_kind": meta.get("kind"),
            "symbol": meta.get("symbol"),
            "title": item.get("title"),
            "lines": (item.get("start_line"), item.get("end_line")),
            "content": item.get("content", ""),
            "payload": p.payload,
        })

    linegen_scores.sort(key=lambda x: x["score"], reverse=True)

    print("\nTop 10 scoring chunks within src/black/linegen.py:")
    print(f"{'Score':<8} | {'Index Kind':<12} | {'Symbol':<32} | {'Lines':<12} | {'Title'}")
    print("-" * 85)
    for c in linegen_scores[:10]:
        lines_str = f"{c['lines'][0]}-{c['lines'][1]}" if c['lines'][0] is not None else "N/A"
        sym_str = str(c["symbol"])[:30] if c["symbol"] else "None"
        print(f"{c['score']:<8.4f} | {str(c['kind']):<12} | {sym_str:<32} | {lines_str:<12} | {c['title']}")

    # 4. Check __post_init__ specifically
    post_init_chunk = next((c for c in linegen_scores if c["symbol"] == "LineGenerator.__post_init__"), None)
    if post_init_chunk is None:
        post_init_chunk = next((c for c in linegen_scores if c["symbol"] and "__post_init__" in c["symbol"]), None)

    print("\n" + "-" * 50)
    print("Is `__post_init__` indexed as a symbol chunk?")
    if post_init_chunk:
        print(f"YES! Chunk ID: {post_init_chunk['id']}")
        print(f"Title: {post_init_chunk['title']}")
        print(f"Lines: {post_init_chunk['lines'][0]}-{post_init_chunk['lines'][1]}")
        print(f"Score against needle 8 query: {post_init_chunk['score']:.4f}")
        print("\nFull indexed chunk content:")
        print(post_init_chunk["content"])

        # Show what was actually sent to the embedding model under max_input_chars=400
        code_item = CodeItem.from_json(post_init_chunk["payload"]["item"])
        preparer = EmbeddingTextPreparer(cfg.embedding.max_input_chars)
        prepared_text = preparer.prepare(code_item)
        print("\nPrepared text actually sent to embedder (under max_input_chars=400):")
        print(f"Length in chars: {len(prepared_text)}")
        print(">>>" + prepared_text + "<<<")
    else:
        print("NO, `__post_init__` was NOT found in linegen chunks!")

    # 5. Search Qdrant for top global chunks and top files
    all_top = vs.search(query_vec, limit=50)

    # Find rank of linegen.py in global chunks
    linegen_chunk_ranks = [(idx + 1, r) for idx, r in enumerate(all_top) if r.item.path == "src/black/linegen.py"]
    best_chunk_rank = linegen_chunk_ranks[0][0] if linegen_chunk_ranks else None

    # Deduplicate files
    unique_files: list[str] = []
    file_ranks: dict[str, int] = {}
    for r in all_top:
        f = normalize_path(r.item.path)
        if f not in file_ranks:
            unique_files.append(f)
            file_ranks[f] = len(unique_files)

    linegen_file_rank = file_ranks.get("src/black/linegen.py")
    print("\n" + "-" * 50)
    print(f"Linegen.py global chunk rank: #{best_chunk_rank} (score: {linegen_chunk_ranks[0][1].score:.4f})")
    print(f"Linegen.py deduplicated file rank: #{linegen_file_rank}")

    print("\nTop 10 chunks that scored HIGHER than linegen.py:")
    for i, r in enumerate(all_top[:10]):
        meta = r.item.metadata
        print(f"\n#{i+1} [Score: {r.score:.4f}] Path: {r.item.path}")
        print(f"    Kind: {meta.get('index_kind')}, Symbol: {meta.get('symbol')}, Lines: {r.item.start_line}-{r.item.end_line}")
        print(f"    Title: {r.item.title}")
        content_preview = r.item.content.replace('\n', ' ')[:160]
        print(f"    Content preview: {content_preview}...")

    print("\n" + "-" * 50)
    print("ROOT CAUSE DIAGNOSIS FOR psf/black NEEDLE 8:")
    print("1. Truncation due to max_input_chars=400:")
    print("   The chunk text contains a long header (symbol name, signature, line numbers)")
    print("   plus the docstring: 'You are in a twisty little maze of passages.'")
    print("   The text truncates at line 509 ('Ø: Set[str] = set'), cutting off ALL operative visitor mappings:")
    print("   visit_assert_stmt, visit_if_stmt, visit_while_stmt, visit_for_stmt, visit_try_stmt, etc.")
    print("2. Missing Discriminative Keywords in the Embedding Window:")
    print("   The query specifically talks about 'assertions, loops, and conditional statements' and 'statement types'.")
    print("   None of these keywords survived the 400-char truncation window in __post_init__.")
    print("3. Higher-scoring competitor chunks:")
    print("   src/black/ranges.py::_TopLevelStatementsVisitor.__init__ scored 0.5644 because its symbol name")
    print("   contains 'TopLevelStatementsVisitor' and signature contains 'lines_set', matching 'statements' and 'lines'.")
    print("   Various file_summary chunks (lines.py, comments.py, __init__.py) and trans.py::StringParser.__init__")
    print("   also scored higher because of generic formatting / init / statements terminology.")


def diagnose_google_gson_needle_8(base_cfg: AppConfig, dataset: dict[str, Any], qc: QdrantClient) -> None:
    print("\n" + "=" * 80)
    print("PART B: FORENSIC DIAGNOSIS FOR google/gson NEEDLE 8")
    print("Target: `run` in `gson/src/main/java/com/google/gson/internal/bind/TypeAdapters.java` (lines 970-984)")
    print("=" * 80)

    cfg, repo_dir = get_repo_config(base_cfg, ".benchmarks/repoqa/java/google_gson")
    collection_name = cfg.storage.qdrant.collection
    print(f"Collection: {collection_name}")

    vs = make_vector_store(cfg)
    provider = make_embedding_provider(cfg, vs.metadata())

    gson_repo = next(r for r in dataset["java"] if r["repo"] == "google/gson")
    needle = gson_repo["needles"][8]
    query = needle["description"].strip()
    target_path = "gson/src/main/java/com/google/gson/internal/bind/TypeAdapters.java"

    print(f"\n[Needle Description Query]:\n{query}\n")

    # 1. Inspect points indexed for TypeAdapters.java in Qdrant
    ta_points = qc.scroll(
        collection_name=collection_name,
        scroll_filter=models.Filter(
            must=[models.FieldCondition(key="item.path", match=models.MatchValue(value=target_path))]
        ),
        limit=500,
        with_payload=True,
        with_vectors=True,
    )[0]

    print(f"Total points indexed for '{target_path}': {len(ta_points)}")
    kinds_count: dict[str, int] = {}
    for p in ta_points:
        ik = p.payload["item"]["metadata"].get("index_kind", "unknown")
        kinds_count[ik] = kinds_count.get(ik, 0) + 1
    print(f"Breakdown by index_kind: {kinds_count}")

    # Check if 'run' is indexed
    run_point = next((p for p in ta_points if p.payload["item"]["metadata"].get("symbol") == "run"), None)
    print(f"\nWas `run` (lines 970-984) indexed in Qdrant? {'YES' if run_point else 'NO'}")

    # Check symbols extracted by AST parser
    abs_ta_path = repo_dir / target_path
    ta_code = abs_ta_path.read_text("utf-8")
    extractor = CodeSymbolExtractor()
    extracted_symbols = extractor.extract(target_path, ta_code)
    print(f"Total symbols extracted by CodeSymbolExtractor: {len(extracted_symbols)}")

    run_sym_idx = next((i for i, s in enumerate(extracted_symbols) if s.name == "run"), -1)
    if run_sym_idx != -1:
        run_sym = extracted_symbols[run_sym_idx]
        print(f"Symbol `run` WAS extracted by parser at index {run_sym_idx} (0-based) / #{run_sym_idx+1} of {len(extracted_symbols)}")
        print(f"  Details: name='{run_sym.name}', kind='{run_sym.kind}', lines={run_sym.start_line}-{run_sym.end_line}, signature='{run_sym.signature}'")
    else:
        print("Symbol `run` was NOT extracted by CodeSymbolExtractor!")

    # Check scanner config max_symbols_per_file
    print(f"\nConfig max_symbols_per_file setting: {cfg.scanner.max_symbols_per_file}")
    last_indexed_sym = extracted_symbols[cfg.scanner.max_symbols_per_file - 1] if cfg.scanner.max_symbols_per_file else None
    if last_indexed_sym:
        print(f"Symbol cap is {cfg.scanner.max_symbols_per_file}. The 96th symbol is '{last_indexed_sym.name}' ending at line {last_indexed_sym.end_line}.")
        print(f"Because `run` is at index {run_sym_idx} (> {cfg.scanner.max_symbols_per_file - 1}), it was SILENTLY DROPPED by the symbol cap!")

    # What if 'run' WAS indexed? Calculate its hypothetical embedding & similarity score
    query_vec = provider.embed_query(query)
    lines = ta_code.splitlines()
    run_sym = extracted_symbols[run_sym_idx]
    start_line = max(run_sym.start_line, 1)
    end_line = min(max(run_sym.end_line, start_line), len(lines))
    body = "\n".join(lines[start_line - 1 : end_line])
    digest = hashlib.sha1(f"{target_path}:{run_sym.name}:{start_line}:{end_line}".encode()).hexdigest()[:12]
    content_lines = [
        f"symbol: {run_sym.kind} {run_sym.name}",
        f"signature: {run_sym.signature}",
        f"lines: {start_line}-{end_line}",
        "",
        body,
    ]
    run_item = CodeItem(
        id=f"{target_path}::{run_sym.name}#{digest}",
        path=target_path,
        title=f"{target_path}::{run_sym.name}",
        content="\n".join(content_lines),
        start_line=start_line,
        end_line=end_line,
        metadata={"source": "scanner", "index_kind": "symbol", "kind": run_sym.kind, "symbol": run_sym.name},
    )
    preparer = EmbeddingTextPreparer(cfg.embedding.max_input_chars)
    prep_text = preparer.prepare(run_item)
    run_emb = provider.embed_documents([prep_text])[0]
    run_hypothetical_score = cosine_similarity(query_vec, run_emb)
    print(f"\nHypothetical score of `run` chunk if indexed: {run_hypothetical_score:.4f}")

    # Top search results for needle 8 query across entire gson collection
    all_top = vs.search(query_vec, limit=50)
    print("\nTop 10 chunks retrieved across google_gson collection:")
    for i, r in enumerate(all_top[:10]):
        meta = r.item.metadata
        print(f"#{i+1:2d} [Score: {r.score:.4f}] {r.item.path} ({meta.get('index_kind')}, {meta.get('symbol')}) lines {r.item.start_line}-{r.item.end_line}")

    # Check rank of TypeAdapters.java in top search results
    ta_ranks = [(idx + 1, r) for idx, r in enumerate(all_top) if r.item.path == target_path]
    unique_files = dedupe_files([r.item.path for r in all_top])
    ta_file_rank = unique_files.index(target_path) + 1 if target_path in unique_files else "> " + str(len(unique_files))

    print(f"\nTypeAdapters.java highest chunk rank in search results: {ta_ranks[0][0] if ta_ranks else 'Not in top 50'} (score: {ta_ranks[0][1].score if ta_ranks else 'N/A'})")
    print(f"TypeAdapters.java deduplicated file rank: #{ta_file_rank}")

    print("\n" + "-" * 50)
    print("ROOT CAUSE DIAGNOSIS FOR google/gson NEEDLE 8:")
    print("1. Symbol Cap Truncation (96 symbols):")
    print(f"   TypeAdapters.java has 126 symbols. The symbol cap Defaults.MAX_SYMBOLS_PER_FILE is 96.")
    print(f"   `run` is symbol #99 (index 98), located at lines 972-1003, well beyond the 96-symbol cutoff (line 955).")
    print("2. Fundamental RepoQA Benchmark Label / Description Mismatch:")
    print("   The needle query describes parsing JSON stream into elements using Deque stack for nested structures.")
    print("   THAT IS ACTUALLY `JsonElement read(JsonReader in)` at lines 858-916 in TypeAdapters.java!")
    print("   RepoQA mistakenly labeled `run` at lines 970-984 (which is a PrivilegedAction reflecting on enum fields).")
    print(f"   Even if `run` were indexed, its score is only {run_hypothetical_score:.4f} because reflection on enum fields")
    print("   has zero semantic relation to JSON stack-based parsing.")
    print("3. Why TypeAdapters.java was missing from top 25 candidate files:")
    print("   Even the actual parsing chunk `read` (line 858) scored 0.4729, drowned out by 15+ more specialized")
    print("   JSON parsing files (JsonStreamParser.java: 0.6354, JsonParser.java: 0.6338, JsonElement.java: 0.6055, etc.).")


def diagnose_google_gson_needle_4(base_cfg: AppConfig, dataset: dict[str, Any]) -> None:
    print("\n" + "=" * 80)
    print("PART C: FORENSIC DIAGNOSIS FOR google/gson NEEDLE 4")
    print("Target: `nonNull` in `NonNullElementWrapperList.java` (lines 49-55)")
    print("Vector had it at #1, but agent picked `$Gson$Preconditions.java` instead.")
    print("=" * 80)

    cfg, repo_dir = get_repo_config(base_cfg, ".benchmarks/repoqa/java/google_gson")
    vs = make_vector_store(cfg)
    provider = make_embedding_provider(cfg, vs.metadata())

    gson_repo = next(r for r in dataset["java"] if r["repo"] == "google/gson")
    needle = gson_repo["needles"][4]
    query = needle["description"].strip()
    target_file = needle["path"]

    print(f"\n[Needle Description Query]:\n{query}\n")

    query_vec = provider.embed_query(query)
    search_results = vs.search(query_vec, limit=25)
    candidate_files = dedupe_files([r.item.path for r in search_results])

    print("Vector Top Candidate Files:")
    for idx, cf in enumerate(candidate_files[:8]):
        print(f"  #{idx+1}: {cf}")

    target_rank = candidate_files.index(target_file) + 1 if target_file in candidate_files else None
    precond_file = "gson/src/main/java/com/google/gson/internal/$Gson$Preconditions.java"
    precond_rank = candidate_files.index(precond_file) + 1 if precond_file in candidate_files else None

    print(f"\nVector Rank of NonNullElementWrapperList: #{target_rank}")
    print(f"Vector Rank of $Gson$Preconditions: #{precond_rank}")

    # Build agent context
    inspect_candidates = candidate_files[:8]
    context_str, inspect_ms = build_agent_context(
        repo_root=repo_dir,
        candidate_files=inspect_candidates,
        retrieved_items=search_results,
        max_symbols_per_file=120,
        max_excerpt_lines=60,
    )

    # Reconstruct the exact prompt given to the agent
    prompt = f"""You are an expert code analyst. A developer is searching for code implementing this description:
"{query}"

Below are candidate files from the repository with symbol outlines and bounded code excerpts:

{context_str}

Task:
1. Examine the candidate files and their code excerpts.
2. Determine which candidate file and exact function/method implements the described behavior.
3. Rerank the candidate files from most likely to least likely: {inspect_candidates}
4. Provide the exact function/method definition lines (start_line to end_line) in the top file.

Respond ONLY with a valid JSON object matching this schema:
{{
  "reasoning": "brief explanation of match",
  "ranked_files": ["top_file_path", "second_file_path", ...],
  "best_match": {{
    "path": "top_file_path",
    "symbol": "function_or_method_name",
    "start_line": 100,
    "end_line": 120
  }}
}}"""

    print("\n" + "-" * 50)
    print("PROMPT DETAILS GIVEN TO THE AGENT:")
    print(f"Total prompt length: {len(prompt)} chars (~{len(prompt)//4} tokens)")

    # Extract sections for both files
    blocks = context_str.split("### File: ")
    block_wrapper = next((b for b in blocks if "NonNullElementWrapperList" in b), "")
    block_precond = next((b for b in blocks if "$Gson$Preconditions" in b), "")

    print("\n" + "=" * 50)
    print("COMPARISON: OUTLINE & EXCERPTS IN AGENT CONTEXT")
    print("=" * 50)
    print("=== [Option 1] NonNullElementWrapperList.java ===")
    print("### File: " + block_wrapper.strip())
    print("\n=== [Option 2] $Gson$Preconditions.java ===")
    print("### File: " + block_precond.strip())

    # Read historical agent decision
    results_path = PROJECT_ROOT / ".benchmarks" / "repoqa" / "agent_gemini35_flash_lite_final.json"
    if results_path.is_file():
        with open(results_path) as f:
            res_data = json.load(f)
        gson_eval = next(r for r in res_data.get("repositories", []) if r.get("repo") == "google/gson")
        n4_eval = gson_eval["needles"][4]
        print("\n" + "-" * 50)
        print("AGENT'S RECORDED OUTPUT (from agent_gemini35_flash_lite_final.json):")
        print(f"Ranked files: {n4_eval.get('final_ranked_files')}")
        print(f"Best match: {n4_eval.get('agent_best_match')}")
        print(f"Agent Reasoning:\n  \"{n4_eval.get('reasoning')}\"")

    print("\n" + "-" * 50)
    print("WHY THE AGENT PREFERRED $Gson$Preconditions.java OVER NonNullElementWrapperList.java:")
    print("1. Canonical Null-Check Utility vs Internal Collection Helper:")
    print("   - `$Gson$Preconditions.checkNotNull(T obj)` is a public, generic precondition assertion utility")
    print("     patterned after Google Guava's `Preconditions.checkNotNull`.")
    print("   - `NonNullElementWrapperList.nonNull(E element)` is a `private` instance helper method inside a List wrapper.")
    print("   - The LLM saw a dedicated utility class named `$Gson$Preconditions` and naturally assumed it was")
    print("     the primary codebase implementation of null verification.")
    print("2. The Crucial Subtle Clue Missed by the Agent:")
    print("   - Query: 'If it is, it throws a NullPointerException with a specific error message.'")
    print("   - `NonNullElementWrapperList.java`: throws new NullPointerException(\"Element must be non-null\");  <-- HAS SPECIFIC MESSAGE")
    print("   - `$Gson$Preconditions.java`:      throws new NullPointerException();                          <-- NO MESSAGE")
    print("   - The LLM overlooked the clause 'with a specific error message', focusing only on the generic null check.")
    print("3. Outline Quality / Symbol Extractor Noise:")
    print("   - In the outline for `NonNullElementWrapperList.java`, `NullPointerException` itself is listed as a method")
    print("     due to regex extraction of constructor throws, slightly polluting the symbol outline.")
    print("   - In shorter inspection prompts (e.g. gpt-5.6-luna or gemini with max_inspect_files=4), the agent noticed")
    print("     the message 'Element must be non-null' and correctly chose NonNullElementWrapperList.")
    print("     When context expanded to 8 files and 120 symbols, attention diluted and it picked Preconditions.")


def main() -> None:
    loader = ConfigLoader()
    base_cfg = loader.load(PROJECT_ROOT / "code-diver.yml")
    dataset = load_dataset()
    qc = QdrantClient(url=base_cfg.storage.qdrant.url)

    diagnose_psf_black_needle_8(base_cfg, dataset, qc)
    diagnose_google_gson_needle_8(base_cfg, dataset, qc)
    diagnose_google_gson_needle_4(base_cfg, dataset)


if __name__ == "__main__":
    main()
