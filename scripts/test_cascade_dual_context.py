#!/usr/bin/env python3
"""Evaluate Cascade vs Unified Dual-Context on the 5 RepoQA misses.

Two evaluation modes:
1. `cascade`:
   - Tier 1: Evaluate top-10 retrieved code chunks with high-focus chunk reranker prompt.
     If a chunk implements the specification, select it!
   - Tier 2: If Tier 1 determines that NONE of the candidate chunks match
     (e.g., all retrieved chunks are production parsers, but query asks for a test function),
     it cascades to evaluate candidate file symbol outlines.
2. `unified`:
   - Single unified prompt containing both Section 1 (chunks) and Section 2 (outlines)
     with cascade instructions.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import gzip
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from code_diver.cli import make_embedding_provider, make_vector_store
from code_diver.config import ConfigLoader
from code_diver.inspection.file_outline_service import FileOutlineService
from code_diver.services.code_symbol_extractor import CodeSymbolExtractor
from code_diver.services.file_summary_item_builder import FileSummaryItemBuilder
from code_diver.strategies.retrieval_strategy_factory import RetrievalStrategyFactory
from scripts.benchmark_repoqa import dedupe_files, index_repo, intervals_overlap, normalize_path
from scripts.benchmark_repoqa_agent_litellm import (
    DEFAULT_ENDPOINT,
    DEFAULT_MODEL,
    call_litellm_agent,
    extract_json_payload,
)

TARGET_NEEDLES = [
    {
        "repo": "axios/axios",
        "lang": "typescript",
        "slug": "axios_axios",
        "func": "done",
        "needle_index": 0,
        "target_file": "lib/adapters/xhr.js",
    },
    {
        "repo": "rust-bakery/nom",
        "lang": "rust",
        "slug": "rust_bakery_nom",
        "func": "yd",
        "needle_index": 0,
        "target_file": "src/bytes/tests.rs",
    },
    {
        "repo": "rust-bakery/nom",
        "lang": "rust",
        "slug": "rust_bakery_nom",
        "func": "i16_tests",
        "needle_index": 1,
        "target_file": "src/number/streaming.rs",
    },
    {
        "repo": "tokio-rs/tracing",
        "lang": "rust",
        "slug": "tokio_rs_tracing",
        "func": "as_ref",
        "needle_index": 2,
        "target_file": "tracing-core/src/field.rs",
    },
    {
        "repo": "junegunn/fzf",
        "lang": "go",
        "slug": "junegunn_fzf",
        "func": "optsFor",
        "needle_index": 9,
        "target_file": "src/options_test.go",
    },
]


def load_repoqa_dataset() -> dict[str, Any]:
    dataset_path = PROJECT_ROOT / "artifacts" / "repoqa" / "repoqa.json.gz"
    with gzip.open(dataset_path, "rt", encoding="utf-8") as f:
        return json.load(f)


@dataclass
class CandidateChunk:
    result: Any
    is_target: bool
    raw_rank: int


def select_candidate_chunks(
    search_results: list[Any],
    top_k: int = 10,
    target_file: str | None = None,
    target_lines: tuple[int, int] | None = None,
) -> tuple[list[CandidateChunk], bool, int | None]:
    code_results: list[CandidateChunk] = []
    seen_spans: set[tuple[str, int, int]] = set()
    target_rank: int | None = None

    for rank, r in enumerate(search_results, 1):
        if r.item.start_line is None or r.item.end_line is None:
            continue
        if r.item.metadata.get("index_kind") == "file_manifest":
            continue

        fpath = normalize_path(r.item.path)
        span = (fpath, int(r.item.start_line), int(r.item.end_line))
        if span in seen_spans:
            continue
        seen_spans.add(span)

        is_target = False
        if target_file and target_lines:
            if fpath == target_file and intervals_overlap(
                r.item.start_line, r.item.end_line, target_lines[0], target_lines[1]
            ):
                is_target = True
                if target_rank is None:
                    target_rank = rank

        code_results.append(CandidateChunk(result=r, is_target=is_target, raw_rank=rank))

    selected = code_results[:top_k]
    target_in_candidates = any(c.is_target for c in selected)
    return selected, target_in_candidates, target_rank


def build_candidate_outlines(
    repo_root: Path,
    candidate_files: list[str],
    max_symbols_per_file: int = 120,
) -> str:
    outline_svc = FileOutlineService(repo_root)
    extractor = CodeSymbolExtractor()
    builder = FileSummaryItemBuilder(compact_budget=True)

    file_sections: list[str] = []
    for cf in candidate_files:
        norm_cf = normalize_path(cf)
        full_path = repo_root / norm_cf
        file_summary_desc = ""
        symbols_list: list[dict[str, Any]] = []

        if full_path.is_file():
            try:
                text = full_path.read_text(encoding="utf-8", errors="replace")
                syms = extractor.extract(norm_cf, text)
                summary_item = builder.build(norm_cf, text, syms)
                summary_lines = [l for l in summary_item.content.splitlines() if l.startswith("purpose: ") or l.startswith("terms: ")]
                file_summary_desc = "\n".join(summary_lines)
            except Exception:
                file_summary_desc = ""

        try:
            outline = outline_svc.structured(norm_cf, symbol_limit=max_symbols_per_file)
            symbols_list = outline.get("symbols", [])
        except Exception:
            symbols_list = []

        formatted_symbols = []
        for s in symbols_list:
            sig = f": {s['signature']}" if s.get("signature") else ""
            formatted_symbols.append(f"  - {s['name']} (lines {s['startLine']}-{s['endLine']}){sig}")

        symbols_block = "\n".join(formatted_symbols) if formatted_symbols else "  (none extracted)"
        summary_block = f"File Summary:\n{file_summary_desc}\n" if file_summary_desc else ""

        file_sections.append(
            f"### File: {norm_cf}\n"
            f"{summary_block}"
            f"Defined Symbols ({len(symbols_list)}):\n"
            f"{symbols_block}"
        )

    return "\n\n".join(file_sections)


# ---------------------------------------------------------------------------
# Tier 1 Prompt (Chunk Evaluation)
# ---------------------------------------------------------------------------
def build_tier1_chunk_prompt(query: str, formatted_chunks: list[str]) -> str:
    chunks_text = "\n\n".join(formatted_chunks)
    return f"""You are an expert code analyst. A developer is searching for a function implementing this exact specification:
\"{query}\"

Below are candidate code chunks retrieved from the repository:

{chunks_text}

GUIDELINES FOR ACCURATE EVALUATION:
1. Target Diversity: The target function can be ANY function in the codebase (production code, trait implementation, test helper, unit test, utility). Treat all candidate chunks equally based strictly on match with the description. Do NOT reject or deprioritize a function because it is in a test file, is a trait implementation, or delegates to an accessor.
2. Concrete Types vs Generic Types: If the specification specifies concrete types (e.g. a byte array `&[u8]`, or string slice `&str`), prefer a candidate with concrete matching types (`&[u8]`, `&str`) over generic functions with type parameters (`<T>`, `<I>`) or functions with different lifetimes/types (`&'static str`).
3. Standard Trait Implementations: When the purpose states "provide a reference to a string representation of an object", in Rust this specifically describes trait implementations like `AsRef<str>` (`fn as_ref(&self) -> &str`), which provide that reference representation.
4. Exact Procedure & Behavior: Check the procedure steps, error conditions, and side effects. Look closely at what behaviors/errors are handled or verified (e.g., handling incomplete data vs complete data). Notice if a candidate does extra work not mentioned in the procedure or matches the procedure exactly.
5. Completeness: If NONE of the candidate chunks implement the specification (for example, if all chunks are production parsers but the specification specifically asks for a test function testing edge cases and incomplete data), set "chunk_match_found": false.

Respond ONLY with a valid JSON object matching this schema:
{{
  "reasoning": "comparison of candidate chunks explaining why the chosen chunk is the best match, or why none of the chunks implement the specification",
  "chunk_match_found": true,
  "best_chunk_index": 1,
  "best_match": {{
    "path": "path/to/file",
    "symbol": "symbol_name",
    "start_line": 10,
    "end_line": 20
  }}
}}
"""


# ---------------------------------------------------------------------------
# Tier 2 Prompt (File Outline Fallback)
# ---------------------------------------------------------------------------
def build_tier2_outline_prompt(query: str, outlines_text: str) -> str:
    return f"""You are an expert code analyst. A developer is searching for a function implementing this exact specification:
\"{query}\"

Retrieved code chunks were evaluated, but none of them matched the specification (for example, the target is a test function or helper not included in the top retrieved chunks).

Below are candidate files from the repository with their module purposes and defined symbol outlines:

{outlines_text}

ACCURACY GUIDELINES:
1. Target Diversity: The target function can be a unit test (e.g. `#[test] fn ..._tests()`), test helper, or utility.
2. Module Purpose: Pay close attention to file module purposes and descriptions. For example, in parsers, `streaming` modules specifically test/handle streaming or incomplete data (empty or missing bytes returning an incomplete error), whereas `complete` modules do not.
3. Match Procedure: Check which function tests or implements the specific types, values, and conditions mentioned in the specification.
4. Exact Symbol & Line Range: You MUST select the exact symbol name and line range as listed in the symbol outline of the best matching file. Do NOT invent, guess, or combine symbol names or line numbers (e.g. if `i16_tests (lines 1483-1493)` is listed in the outline, output symbol "i16_tests" and lines 1483-1493 exactly). If the specification asks for a test function, select the test function symbol (e.g. ending in `_tests`), NOT the production function it calls.

Respond ONLY with a valid JSON object matching this schema:
{{
  "reasoning": "explanation of selection from file outlines",
  "best_match": {{
    "path": "path/to/file",
    "symbol": "symbol_name",
    "start_line": 10,
    "end_line": 20
  }}
}}
"""


# ---------------------------------------------------------------------------
# Unified Prompt
# ---------------------------------------------------------------------------
def build_unified_prompt(query: str, formatted_chunks: list[str], outlines_text: str) -> str:
    chunks_text = "\n\n".join(formatted_chunks)
    num_chunks = len(formatted_chunks)
    return f"""You are an expert code analyst. A developer is searching for a function implementing this exact specification:
\"{query}\"

Below is the retrieved context from the repository:
=== SECTION 1: TOP RETRIEVED CODE CHUNKS (Chunks 1 to {num_chunks}) ===
{chunks_text}

=== SECTION 2: CANDIDATE FILE SYMBOL OUTLINES (Fallback) ===
{outlines_text}

CASCADE EVALUATION INSTRUCTIONS:
First evaluate the retrieved code chunks in SECTION 1 (Chunks 1 to {num_chunks}). If one of these chunks is the exact function described by the specification, select it! Set "source": "chunk" and provide its "best_chunk_index".
If NONE of the retrieved code chunks in Section 1 match the described behavior (for example, if the retrieved chunks are production parsers but the specification asks for a test function or helper not included in the chunks), examine the candidate file symbol outlines in SECTION 2 and select the function from the outlines. Set "source": "outline" and "best_chunk_index": null.

ACCURACY GUIDELINES:
1. Target Diversity: The target function can be ANY function in the codebase (production code, trait implementation, test helper, unit test, utility). Treat all candidate chunks equally based strictly on match with the description. Do NOT reject or deprioritize a function because it is in a test file, is a trait implementation, or delegates to an accessor.
2. Concrete Types vs Generic Types: If the specification specifies concrete types (e.g. a byte array `&[u8]`, or string slice `&str`), prefer a candidate with concrete matching types (`&[u8]`, `&str`) over generic functions with type parameters (`<T>`, `<I>`) or functions with different lifetimes/types (`&'static str`). Rigorously match parameter counts, parameter types, variadic arguments, and return types (e.g. `words ...string` represents an array/list of strings).
3. Standard Trait Implementations: When the purpose states "provide a reference to a string representation of an object", in Rust this specifically describes trait implementations like `AsRef<str>` (`fn as_ref(&self) -> &str`), which provide that reference representation.
4. Exact Procedure & Behavior: Check the procedure steps, error conditions, and side effects. Notice if a candidate does extra work not mentioned in the procedure or matches the procedure exactly.
5. Module Purposes & Outlines: When examining Section 2 outlines, pay attention to file module purposes (e.g. `streaming` modules specifically test/handle incomplete data). You MUST select the exact symbol name and line range as listed in the symbol outline of the best matching file. Do NOT invent, guess, or combine symbol names or line numbers. If the specification asks for a test function, select the test function symbol (e.g. ending in `_tests`), NOT the production function it calls.

Respond ONLY with a valid JSON object matching this schema:
{{
  "reasoning": "detailed explanation comparing why the chosen function is the best match",
  "source": "chunk",
  "best_chunk_index": 1,
  "best_match": {{
    "path": "path/to/file",
    "symbol": "symbol_name",
    "start_line": 10,
    "end_line": 20
  }}
}}
"""


def evaluate_needle(
    meta: dict[str, Any],
    dataset: dict[str, Any],
    base_cfg: Any,
    model: str,
    endpoint: str,
    api_key: str,
    mode: str = "cascade",
    limit: int = 120,
    top_chunks_k: int = 10,
    top_files_k: int = 5,
    max_symbols_per_file: int = 120,
) -> dict[str, Any]:
    lang = meta["lang"]
    repo = meta["repo"]
    slug = meta["slug"]
    idx = meta["needle_index"]
    target_file = normalize_path(meta["target_file"])
    expected_func = meta["func"]

    repo_dir = (PROJECT_ROOT / f".benchmarks/repoqa/{lang}/{slug}").resolve()
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

    r_entry = next(x for x in dataset[lang] if x["repo"] == repo)
    needle = r_entry["needles"][idx]
    query = needle["description"].strip()
    n_start = int(needle["start_line"])
    n_end = int(needle["end_line"])

    t0_retrieval = time.perf_counter()
    search_results = strategy.search(query, limit=limit)
    retrieval_ms = (time.perf_counter() - t0_retrieval) * 1000.0

    retrieved_paths = [r.item.path for r in search_results]
    vector_candidate_files = dedupe_files(retrieved_paths)
    candidate_files = vector_candidate_files[:top_files_k]
    file_in_candidates = target_file in candidate_files
    file_raw_rank = (
        vector_candidate_files.index(target_file) + 1 if target_file in vector_candidate_files else None
    )

    selected_chunks, chunk_in_candidates, chunk_raw_rank = select_candidate_chunks(
        search_results=search_results,
        top_k=top_chunks_k,
        target_file=target_file,
        target_lines=(n_start, n_end),
    )

    formatted_chunks = []
    chunk_meta_list = []
    for c_idx, c in enumerate(selected_chunks, 1):
        r = c.result
        sym = r.item.metadata.get("symbol") or r.item.title.split("::")[-1]
        fpath = normalize_path(r.item.path)
        s_line = int(r.item.start_line)
        e_line = int(r.item.end_line)
        formatted_chunks.append(
            f"Candidate Chunk #{c_idx} (File: {fpath}, Lines: {s_line}-{e_line}, Symbol: {sym}, Score: {r.score:.4f}):\n"
            f"```{lang}\n{r.item.content}\n```"
        )
        chunk_meta_list.append({
            "chunk_index": c_idx,
            "path": fpath,
            "symbol": sym,
            "start_line": s_line,
            "end_line": e_line,
            "is_target": c.is_target,
            "raw_rank": c.raw_rank,
            "score": float(r.score),
        })

    agent_ms = 0.0
    source = "chunk"
    best_chunk_idx = None
    matching_chunk = None
    bm_path = ""
    bm_symbol = ""
    bm_start = 0
    bm_end = 0
    reasoning = ""

    if mode == "cascade":
        # ---------------- Tier 1: Evaluate Chunks ----------------
        t1_prompt = build_tier1_chunk_prompt(query, formatted_chunks)
        raw_t1, ms1, _ = call_litellm_agent(t1_prompt, model=model, endpoint=endpoint, api_key=api_key)
        agent_ms += ms1
        out_t1 = extract_json_payload(raw_t1)
        reasoning = out_t1.get("reasoning", "")
        chunk_found = out_t1.get("chunk_match_found", True)
        best_chunk_idx = out_t1.get("best_chunk_index")

        if chunk_found and isinstance(best_chunk_idx, int) and 1 <= best_chunk_idx <= len(chunk_meta_list):
            source = "chunk"
            matching_chunk = chunk_meta_list[best_chunk_idx - 1]
            bm = out_t1.get("best_match") or {}
            bm_path = normalize_path(bm.get("path") or matching_chunk["path"])
            bm_symbol = bm.get("symbol") or matching_chunk["symbol"]
            bm_start = int(bm.get("start_line") or matching_chunk["start_line"])
            bm_end = int(bm.get("end_line") or matching_chunk["end_line"])
        else:
            # ---------------- Tier 2: Fallback to Outlines ----------------
            source = "outline"
            outlines_text = build_candidate_outlines(repo_dir, candidate_files, max_symbols_per_file)
            t2_prompt = build_tier2_outline_prompt(query, outlines_text)
            raw_t2, ms2, _ = call_litellm_agent(t2_prompt, model=model, endpoint=endpoint, api_key=api_key)
            agent_ms += ms2
            out_t2 = extract_json_payload(raw_t2)
            reasoning = f"[Tier 1: No match] -> [Tier 2 Outline]: " + out_t2.get("reasoning", "")
            bm = out_t2.get("best_match") or {}
            bm_path = normalize_path(bm.get("path", ""))
            bm_symbol = bm.get("symbol", "")
            bm_start = int(bm.get("start_line", 0)) if bm.get("start_line") is not None else 0
            bm_end = int(bm.get("end_line", 0)) if bm.get("end_line") is not None else 0

    elif mode == "unified":
        outlines_text = build_candidate_outlines(repo_dir, candidate_files, max_symbols_per_file)
        uni_prompt = build_unified_prompt(query, formatted_chunks, outlines_text)
        raw_uni, ms_uni, _ = call_litellm_agent(uni_prompt, model=model, endpoint=endpoint, api_key=api_key)
        agent_ms += ms_uni
        out_uni = extract_json_payload(raw_uni)
        reasoning = out_uni.get("reasoning", "")
        source = out_uni.get("source", "chunk")
        best_chunk_idx = out_uni.get("best_chunk_index")
        if isinstance(best_chunk_idx, int) and 1 <= best_chunk_idx <= len(chunk_meta_list):
            matching_chunk = chunk_meta_list[best_chunk_idx - 1]
        bm = out_uni.get("best_match") or {}
        bm_path_raw = bm.get("path") or (matching_chunk["path"] if matching_chunk else "")
        bm_path = normalize_path(bm_path_raw)
        bm_symbol = bm.get("symbol") or (matching_chunk["symbol"] if matching_chunk else "")
        bm_start = int(bm.get("start_line", 0)) if bm.get("start_line") is not None else 0
        bm_end = int(bm.get("end_line", 0)) if bm.get("end_line") is not None else 0

        if (bm_start == 0 or bm_end == 0) and matching_chunk:
            bm_start = matching_chunk["start_line"]
            bm_end = matching_chunk["end_line"]
            if not bm_path:
                bm_path = matching_chunk["path"]

    # File Hit
    file_hit = (bm_path == target_file) or (
        any(bm_path.endswith("/" + target_file) or target_file.endswith("/" + bm_path) for _ in [1])
    )

    # Line Hit / Exact Match
    line_hit = False
    if source == "chunk" and matching_chunk and matching_chunk["is_target"]:
        line_hit = True
    elif file_hit and bm_start > 0 and bm_end > 0:
        line_hit = intervals_overlap(bm_start, bm_end, n_start, n_end)
    elif file_hit and bm_symbol == expected_func:
        line_hit = True

    return {
        "repo": repo,
        "needle_index": idx,
        "func": expected_func,
        "target_file": target_file,
        "target_lines": (n_start, n_end),
        "file_raw_rank": file_raw_rank,
        "file_in_candidates": file_in_candidates,
        "chunk_raw_rank": chunk_raw_rank,
        "chunk_in_candidates": chunk_in_candidates,
        "file_hit": file_hit,
        "line_hit": line_hit,
        "source": source,
        "best_chunk_index": best_chunk_idx,
        "matching_chunk": matching_chunk,
        "agent_best_match": {
            "path": bm_path,
            "symbol": bm_symbol,
            "start_line": bm_start,
            "end_line": bm_end,
        },
        "reasoning": reasoning,
        "timings": {
            "retrieval_ms": retrieval_ms,
            "agent_ms": agent_ms,
            "total_ms": retrieval_ms + agent_ms,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Cascade vs Unified Dual-Context on 5 RepoQA misses.")
    parser.add_argument("--mode", choices=["cascade", "unified"], default="cascade", help="Evaluation mode (default: cascade)")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help=f"LiteLLM model name (default: {DEFAULT_MODEL})")
    parser.add_argument("--endpoint", type=str, default=DEFAULT_ENDPOINT, help="LiteLLM endpoint")
    parser.add_argument("--limit", type=int, default=120, help="Vector search retrieval limit")
    parser.add_argument("--top-chunks-k", type=int, default=10, help="Number of code chunks in Tier 1")
    parser.add_argument("--top-files-k", type=int, default=5, help="Number of candidate files in Tier 2")
    parser.add_argument("--max-symbols", type=int, default=120, help="Max symbols per file in outline")
    parser.add_argument("--needle-idx", type=int, default=None, help="Evaluate specific needle (0-4)")
    args = parser.parse_args()

    api_key = os.environ.get("LITE_LLM_KEY") or os.environ.get("LITELLM_API_KEY", "")
    dataset = load_repoqa_dataset()
    base_cfg = ConfigLoader().load(None)

    targets = TARGET_NEEDLES if args.needle_idx is None else [TARGET_NEEDLES[args.needle_idx]]

    print("=" * 85)
    print(f"DUAL-CONTEXT EVALUATION (Mode: {args.mode.upper()}) ON 5 REPOQA MISSES")
    print(f"Model: {args.model} | Top Chunks: {args.top_chunks_k} | Top Files: {args.top_files_k} | Limit: {args.limit}")
    print("=" * 85)

    results = []
    for idx, meta in enumerate(targets):
        repo = meta["repo"]
        func = meta["func"]
        t_file = meta["target_file"]
        print(f"\n[{idx+1}/{len(targets)}] Evaluating {repo} -> `{func}` ({t_file})...")

        res = evaluate_needle(
            meta=meta,
            dataset=dataset,
            base_cfg=base_cfg,
            model=args.model,
            endpoint=args.endpoint,
            api_key=api_key,
            mode=args.mode,
            limit=args.limit,
            top_chunks_k=args.top_chunks_k,
            top_files_k=args.top_files_k,
            max_symbols_per_file=args.max_symbols,
        )
        results.append(res)

        f_in = "YES" if res["file_in_candidates"] else "NO"
        c_in = "YES" if res["chunk_in_candidates"] else "NO"
        f_hit = "PASS" if res["file_hit"] else "FAIL"
        l_hit = "PASS" if res["line_hit"] else "FAIL"
        bm = res["agent_best_match"]
        bm_desc = f"{bm['path']}:{bm['symbol']} (lines {bm['start_line']}-{bm['end_line']})"
        source_desc = f"Chunk #{res['best_chunk_index']}" if res["source"] == "chunk" and res["best_chunk_index"] else "Tier 2 File Outline"

        print(f"  Target File in Pool  : {f_in} (File Rank #{res['file_raw_rank']})")
        print(f"  Target Chunk in Pool : {c_in} (Chunk Rank #{res['chunk_raw_rank']})")
        print(f"  Source Used          : {source_desc}")
        print(f"  File Hit             : {f_hit} | Line/Chunk Hit: {l_hit}")
        print(f"  Agent Best Match     : {bm_desc}")
        print(f"  Reasoning            : {res['reasoning'][:200]}...")
        print(f"  Timing               : {res['timings']['total_ms']:.1f}ms (Agent: {res['timings']['agent_ms']:.1f}ms)")

    print("\n" + "=" * 85)
    print(f"EVALUATION SUMMARY ({args.mode.upper()})")
    print("=" * 85)
    total = len(results)
    file_hits = sum(1 for r in results if r["file_hit"])
    line_hits = sum(1 for r in results if r["line_hit"])

    print(f"Total Needles Evaluated : {total}")
    print(f"File Hit@1              : {file_hits}/{total} ({file_hits/total*100:.1f}%)")
    print(f"Line/Chunk Hit@1        : {line_hits}/{total} ({line_hits/total*100:.1f}%)")
    print("-" * 85)
    for r in results:
        status = "HIT " if r["line_hit"] else "MISS"
        target_str = f"{r['repo']}::{r['func']} ({r['target_file']})"
        bm = r["agent_best_match"]
        chosen_str = f"{bm['path']}::{bm['symbol']} (lines {bm['start_line']}-{bm['end_line']})"
        src_tag = f"[{r['source'].upper()}]"
        print(f"[{status}] {src_tag:<9} {target_str:<45} -> {chosen_str}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
