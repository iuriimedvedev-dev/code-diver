#!/usr/bin/env python3
"""Evaluate Dual Context (Candidate File Outlines + Top Retrieved Code Chunks) on the 5 RepoQA misses.

Dual Context structure:
PART 1: Top Candidate Files with their symbol outlines and file summaries.
PART 2: Top Retrieved Code Chunks with their code, line numbers, and file paths.

Prompt asks LLM:
Which function / code chunk in the repository best matches the specification?
Returns:
- best_file
- best_symbol
- start_line / end_line
- best_chunk_index (if one of the retrieved code chunks in PART 2 matches)
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


def build_dual_context(
    repo_root: Path,
    candidate_files: list[str],
    selected_chunks: list[CandidateChunk],
    lang: str,
    max_symbols_per_file: int = 120,
) -> tuple[str, list[dict[str, Any]]]:
    outline_svc = FileOutlineService(repo_root)
    extractor = CodeSymbolExtractor()
    summary_builder = FileSummaryItemBuilder(compact_budget=True)

    # PART 1: Top Candidate Files with outlines and summaries
    part1_sections: list[str] = []
    for cf in candidate_files:
        norm_cf = normalize_path(cf)
        full_path = repo_root / norm_cf
        file_summary_desc = ""
        symbols_list: list[dict[str, Any]] = []

        if full_path.is_file():
            try:
                text = full_path.read_text(encoding="utf-8", errors="replace")
                syms = extractor.extract(norm_cf, text)
                summary_item = summary_builder.build(norm_cf, text, syms)
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

        part1_sections.append(
            f"### File: {norm_cf}\n"
            f"{summary_block}"
            f"Defined Symbols ({len(symbols_list)}):\n"
            f"{symbols_block}"
        )

    part1_text = "=== PART 1: TOP CANDIDATE FILES & SYMBOL OUTLINES ===\n\n" + "\n\n".join(part1_sections)

    # PART 2: Top Retrieved Code Chunks
    part2_sections: list[str] = []
    chunk_meta_list: list[dict[str, Any]] = []
    for c_idx, c in enumerate(selected_chunks, 1):
        r = c.result
        sym = r.item.metadata.get("symbol") or r.item.title.split("::")[-1]
        fpath = normalize_path(r.item.path)
        s_line = int(r.item.start_line)
        e_line = int(r.item.end_line)
        part2_sections.append(
            f"Chunk #{c_idx} (File: {fpath}, Lines: {s_line}-{e_line}, Symbol: {sym}, Score: {r.score:.4f}):\n"
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

    part2_text = "=== PART 2: TOP RETRIEVED CODE CHUNKS ===\n\n" + "\n\n".join(part2_sections)

    full_context = f"{part1_text}\n\n{part2_text}"
    return full_context, chunk_meta_list


def build_dual_context_prompt(query: str, dual_context: str) -> str:
    return f"""You are an expert code analyst. A developer is searching for a function implementing this exact specification:
\"{query}\"

Below is the dual context retrieved from the repository:
- PART 1 lists the top candidate files, their high-level summaries, and all symbols/functions defined within them with their line spans.
- PART 2 displays the actual source code of the top retrieved code chunks.

{dual_context}

GUIDELINES FOR ACCURATE EVALUATION:
1. Target Diversity: The target function can be ANY function in the codebase (production code, test helper, unit test, utility). Treat all functions equally based strictly on match with the description. Do NOT reject or deprioritize a function because it is in a test file or is a test helper.
2. Signatures & Types: Rigorously match parameter counts, parameter types, variadic arguments, and return types. (e.g. `words ...string` represents an array/list of strings; concrete slice `&[u8]` vs generic parameters).
3. Exact Procedure & Behavior: Check the procedure steps, error conditions, and side effects. Look closely at what behaviors/errors are handled or verified (e.g., handling incomplete data vs complete data). Notice if a candidate does extra work not mentioned in the procedure or matches the procedure exactly.
4. Locating the Match:
   - If the best match is one of the code chunks in PART 2, reference its chunk index and coordinates.
   - If the best match is defined in PART 1 (e.g., a function in the symbol outline whose code chunk was not in the top chunks), select its file, symbol name, and line numbers from PART 1.

Task:
1. Carefully evaluate all candidates in PART 1 and PART 2 against the specification.
2. Determine which candidate file and exact function/method best matches the query.
3. If the matching function corresponds to one of the chunks in PART 2, specify `matching_chunk_index` (integer), otherwise `null`.

Respond ONLY with a valid JSON object matching this schema:
{{
  "reasoning": "detailed explanation comparing why the chosen function is the best match and why competing candidates are not",
  "matching_chunk_index": 1,
  "best_match": {{
    "path": "path/to/file",
    "symbol": "symbol_name",
    "start_line": 10,
    "end_line": 20
  }}
}}
"""


def evaluate_needle_dual_context(
    meta: dict[str, Any],
    dataset: dict[str, Any],
    base_cfg: Any,
    model: str,
    endpoint: str,
    api_key: str,
    limit: int = 120,
    top_chunks_k: int = 8,
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

    t0_context = time.perf_counter()
    dual_context, chunk_meta_list = build_dual_context(
        repo_root=repo_dir,
        candidate_files=candidate_files,
        selected_chunks=selected_chunks,
        lang=lang,
        max_symbols_per_file=max_symbols_per_file,
    )
    context_build_ms = (time.perf_counter() - t0_context) * 1000.0

    prompt = build_dual_context_prompt(query, dual_context)

    agent_output: dict[str, Any] = {}
    agent_ms = 0.0
    parse_ok = True
    try:
        raw_text, agent_ms, usage = call_litellm_agent(
            prompt=prompt,
            model=model,
            endpoint=endpoint,
            api_key=api_key,
        )
        agent_output = extract_json_payload(raw_text)
    except Exception as exc:
        parse_ok = False
        print(f"    [Agent Error] {repo} needle {idx}: {exc}")
        agent_output = {}

    matching_chunk_idx = agent_output.get("matching_chunk_index")
    matching_chunk = None
    if isinstance(matching_chunk_idx, int) and 1 <= matching_chunk_idx <= len(chunk_meta_list):
        matching_chunk = chunk_meta_list[matching_chunk_idx - 1]

    bm = agent_output.get("best_match", {})
    bm_path_raw = bm.get("path") or (matching_chunk["path"] if matching_chunk else "")
    bm_path = normalize_path(bm_path_raw)
    bm_symbol = bm.get("symbol") or (matching_chunk["symbol"] if matching_chunk else "")
    bm_start = int(bm.get("start_line", 0)) if bm.get("start_line") is not None else 0
    bm_end = int(bm.get("end_line", 0)) if bm.get("end_line") is not None else 0

    # Fallback to chunk coordinates if best_match lines were missing but matching_chunk was specified
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
    if matching_chunk and matching_chunk["is_target"]:
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
        "matching_chunk_index": matching_chunk_idx,
        "matching_chunk": matching_chunk,
        "agent_best_match": {
            "path": bm_path,
            "symbol": bm_symbol,
            "start_line": bm_start,
            "end_line": bm_end,
        },
        "reasoning": agent_output.get("reasoning", ""),
        "parse_ok": parse_ok,
        "timings": {
            "retrieval_ms": retrieval_ms,
            "context_ms": context_build_ms,
            "agent_ms": agent_ms,
            "total_ms": retrieval_ms + context_build_ms + agent_ms,
        },
        "context_chars": len(dual_context),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Dual Context LLM reranker on the 5 RepoQA misses.")
    parser.add_argument("--model", type=str, default="gemini-3.5-flash-lite", help="LiteLLM model name")
    parser.add_argument("--endpoint", type=str, default=DEFAULT_ENDPOINT, help="LiteLLM endpoint")
    parser.add_argument("--limit", type=int, default=120, help="Vector search retrieval limit")
    parser.add_argument("--top-chunks-k", type=int, default=8, help="Number of code chunks in PART 2")
    parser.add_argument("--top-files-k", type=int, default=5, help="Number of candidate files in PART 1")
    parser.add_argument("--max-symbols", type=int, default=120, help="Max symbols per file in outline")
    parser.add_argument("--needle-idx", type=int, default=None, help="Evaluate specific needle (0-4)")
    args = parser.parse_args()

    api_key = os.environ.get("LITE_LLM_KEY") or os.environ.get("LITELLM_API_KEY", "")
    dataset = load_repoqa_dataset()
    base_cfg = ConfigLoader().load(None)

    targets = TARGET_NEEDLES if args.needle_idx is None else [TARGET_NEEDLES[args.needle_idx]]

    print("=" * 85)
    print("DUAL CONTEXT (FILE OUTLINES + TOP CODE CHUNKS) EVALUATION ON 5 MISSES")
    print(f"Model: {args.model} | Top Files: {args.top_files_k} | Top Chunks: {args.top_chunks_k} | Limit: {args.limit}")
    print("=" * 85)

    results = []
    for idx, meta in enumerate(targets):
        repo = meta["repo"]
        func = meta["func"]
        t_file = meta["target_file"]
        print(f"\n[{idx+1}/{len(targets)}] Evaluating {repo} -> `{func}` ({t_file})...")

        res = evaluate_needle_dual_context(
            meta=meta,
            dataset=dataset,
            base_cfg=base_cfg,
            model=args.model,
            endpoint=args.endpoint,
            api_key=api_key,
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
        chunk_desc = f"Chunk #{res['matching_chunk_index']}" if res["matching_chunk_index"] else "PART 1 Outline"

        print(f"  Target File in Pool  : {f_in} (File Rank #{res['file_raw_rank']})")
        print(f"  Target Chunk in Pool : {c_in} (Chunk Rank #{res['chunk_raw_rank']})")
        print(f"  Source Used          : {chunk_desc}")
        print(f"  File Hit             : {f_hit} | Chunk/Line Hit: {l_hit}")
        print(f"  Agent Best Match     : {bm_desc}")
        print(f"  Reasoning            : {res['reasoning'][:200]}...")
        print(f"  Context Size         : {res['context_chars']} chars")
        print(f"  Timing               : {res['timings']['total_ms']:.1f}ms (Agent: {res['timings']['agent_ms']:.1f}ms)")

    print("\n" + "=" * 85)
    print("DUAL CONTEXT EVALUATION SUMMARY")
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
        print(f"[{status}] {target_str:<50} -> {chosen_str}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
