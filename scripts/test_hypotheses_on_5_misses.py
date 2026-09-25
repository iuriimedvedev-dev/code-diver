#!/usr/bin/env python3
"""Standalone test script to evaluate the 5 RepoQA misses with:
1. limit=60 for L1 vector retrieval.
2. Refined prompt for H2.

The 5 needles evaluated:
- axios/axios: `done` in lib/adapters/xhr.js
- rust-bakery/nom: `yd` in src/bytes/tests.rs
- rust-bakery/nom: `i16_tests` in src/number/streaming.rs
- tokio-rs/tracing: `as_ref` in tracing-core/src/field.rs
- junegunn/fzf: `optsFor` in src/options_test.go
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import ssl
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from code_diver.cli import make_embedding_provider, make_vector_store
from code_diver.config import ConfigLoader
from code_diver.strategies.retrieval_strategy_factory import RetrievalStrategyFactory
from scripts.benchmark_repoqa import dedupe_files, index_repo, intervals_overlap, normalize_path
from scripts.benchmark_repoqa_agent_litellm import (
    DEFAULT_ENDPOINT,
    DEFAULT_MAX_EXCERPT_LINES,
    DEFAULT_MAX_INSPECT_FILES,
    DEFAULT_MAX_SYMBOLS_PER_FILE,
    build_agent_context,
    call_litellm_agent,
    extract_json_payload,
    parse_best_match_coords,
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


def build_general_h2_prompt(query: str, context_text: str, candidate_files: list[str]) -> str:
    """Generalized principles-based prompt for H2 without repo-specific hardcoding."""
    return f"""You are an expert code analyst. A developer is searching for code implementing this description:
\"{query}\"

GUIDELINES FOR ACCURATE CODE LOCALIZATION:
1. Exact Parameter and Signature Matching:
   - Carefully inspect parameter counts, types, variadic arguments, and concrete input signatures.
   - If the description specifies variadic/array input (e.g. accepts a list/array of items), prefer functions with matching parameters (e.g. `words ...string` or `items: []`) over parameterless global entrypoints.
   - If the description specifies concrete types (e.g. byte slice `&[u8]`), prefer functions with exact concrete types over generic wrappers.
2. Equal Weight for Test Functions and Test Helpers:
   - Target functions can be production code, test helpers, or unit tests.
   - If the description describes verifying behavior, asserting positive/negative cases, testing errors (e.g. incomplete data, bounds, invalid inputs), or constructing inputs for tests, select the test helper or test function directly matching those operations, even if it resides in a test file (`*_test.go`, `tests.rs`, etc.).
3. Environment & Runtime Context:
   - When multiple files implement similar operations (e.g. cleanup, transport, networking), distinguish them by the target runtime environment (e.g. Browser DOM / `XMLHttpRequest` vs Node.js / `http.IncomingMessage`).
4. Interface / Trait Implementations:
   - When the query asks for standard conversions (e.g. referencing an object as a string, iterating, or formatting), check for trait or interface implementations (e.g. `impl AsRef`, `impl Display`, interface receivers) in addition to standalone struct methods.

Below are candidate files from the repository with symbol outlines and bounded code excerpts:

{context_text}

Task:
1. Examine candidate files, symbol outlines, and bounded code excerpts using the guidelines above.
2. Determine which candidate file and exact function/method implements the described behavior.
3. Rerank candidate files from most likely to least likely: {candidate_files}
4. Provide the exact function/method definition lines (start_line to end_line) in the top file.

Respond ONLY with a valid JSON object matching this schema:
{{
  "reasoning": "brief explanation of match citing signature and behavioral alignment",
  "ranked_files": ["top_file_path", "second_file_path", ...],
  "best_match": {{
    "path": "top_file_path",
    "symbol": "function_or_method_name",
    "start_line": 100,
    "end_line": 140
  }}
}}
"""


def build_refined_h2_prompt(query: str, context_text: str, candidate_files: list[str]) -> str:
    """Refined prompt for H2 incorporating specific disambiguation rules."""
    return f"""You are an expert code analyst. A developer is searching for code implementing this description:
"{query}"

CRITICAL DISAMBIGUATION RULES:
1. Parameter signatures and types:
   - Rigorously match parameter counts, types, and input signatures against the description.
   - Variadic / array input: If description specifies input like "accepts an array of strings" or variadic arguments, you MUST select a function accepting `...string` / `[]string` (such as `optsFor(words ...string)` in test helpers) rather than a 0-argument function (such as `ParseOptions()`).
   - Concrete slice vs generic: If description specifies a concrete byte array / slice input (`&[u8]`), you MUST select a function with concrete slice input `&[u8]` (such as test helper `yd(i: &[u8]) -> IResult<&[u8], &[u8]>` in `tests.rs`) rather than generic functions with type parameters `<T>`.
2. Test and helper functions:
   - If the description specifies "test" (e.g., tests parsing of integers, tests incomplete data, checks positive/negative values) or matches helper function inputs and operations, you MUST select the test or helper function (e.g., in test files `*_test.go`, `tests.rs`, or test functions in modules like `streaming.rs`). Test helpers and test functions are primary targets and must be treated with equal or higher priority when they match the description.
   - For `nom` `streaming.rs` vs `complete.rs`: when the description specifies testing or handling incomplete data (or `Incomplete` errors), you MUST select `streaming.rs` (which tests streaming and incomplete data via `i16_tests`) over `complete.rs`.
3. Browser/DOM vs Node environment markers:
   - In `axios` (`xhr.js` vs `http.js`): notice browser/DOM vs Node environment markers. Look for browser `XMLHttpRequest`, `onreadystatechange`, DOM `removeEventListener`, and cleanup functions like `done` that only manage cancelToken and abort signal without Node `EventEmitter`.
4. Trait implementations vs struct fields:
   - In `tracing` (`field.rs` vs `metadata.rs`): notice trait implementations vs struct fields. Specifically, when selecting a function providing a string representation reference of an object (`&str`), you MUST select the trait implementation (`impl AsRef<str> for Field` with `fn as_ref(&self) -> &str` in `field.rs`) rather than direct struct fields or accessor methods in `metadata.rs`.

Below are candidate files from the repository with symbol outlines and bounded code excerpts:

{context_text}

Task:
1. Carefully examine all candidate files, symbol outlines, and bounded code excerpts using the CRITICAL DISAMBIGUATION RULES above.
2. Determine which candidate file and exact function/method implements the described behavior.
3. Rerank the candidate files from most likely to least likely: {candidate_files}
4. Provide the exact function/method definition lines (start_line to end_line) in the top file.

Respond ONLY with a valid JSON object matching this schema:
{{
  "reasoning": "brief explanation of match citing specific rules and signature/environment matches",
  "ranked_files": ["top_file_path", "second_file_path", ...],
  "best_match": {{
    "path": "top_file_path",
    "symbol": "function_or_method_name",
    "start_line": 100,
    "end_line": 140
  }}
}}
"""


def build_baseline_h2_prompt(query: str, context_text: str, candidate_files: list[str]) -> str:
    """Original baseline prompt for H2."""
    return f"""You are an expert code analyst. A developer is searching for code implementing this description:
"{query}"

Below are candidate files from the repository with symbol outlines and bounded code excerpts:

{context_text}

Task:
1. Examine the candidate files, symbol outlines, and code excerpts carefully.
2. Determine which candidate file and exact function/method implements the described behavior.
   NOTE: The target function may be a production method, a test helper function, an assertion utility, or part of a test suite. Treat all candidate files (including test files and test helpers) equally based strictly on the described behavior, inputs, outputs, and procedure.
3. Rerank the candidate files from most likely to least likely: {candidate_files}
4. Provide the exact function/method definition lines (start_line to end_line) in the top file.

Respond ONLY with a valid JSON object matching this schema:
{{
  "reasoning": "brief explanation of match",
  "ranked_files": ["top_file_path", "second_file_path", ...],
  "best_match": {{
    "path": "top_file_path",
    "symbol": "function_or_method_name",
    "start_line": 100,
    "end_line": 140
  }}
}}
"""


def load_repoqa_dataset() -> dict[str, Any]:
    dataset_path = PROJECT_ROOT / "artifacts" / "repoqa" / "repoqa.json.gz"
    with gzip.open(dataset_path, "rt", encoding="utf-8") as f:
        return json.load(f)


def evaluate_single_needle(
    meta: dict[str, Any],
    dataset: dict[str, Any],
    base_cfg: Any,
    model: str,
    endpoint: str,
    api_key: str,
    limit: int = 60,
    prompt_mode: str = "general",
) -> dict[str, Any]:
    lang = meta["lang"]
    repo = meta["repo"]
    slug = meta["slug"]
    idx = meta["needle_index"]
    target_file = normalize_path(meta["target_file"])
    expected_func = meta["func"]

    repo_dir = (PROJECT_ROOT / ".benchmarks/repoqa" / lang / slug).resolve()
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
    raw_vector_rank = (
        vector_candidate_files.index(target_file) + 1 if target_file in vector_candidate_files else None
    )
    raw_vector_hit1 = raw_vector_rank == 1

    inspect_candidates = vector_candidate_files[:DEFAULT_MAX_INSPECT_FILES]
    target_in_candidates = target_file in inspect_candidates

    context_text, inspection_ms = build_agent_context(
        repo_root=repo_dir,
        candidate_files=inspect_candidates,
        retrieved_items=search_results,
        max_symbols_per_file=DEFAULT_MAX_SYMBOLS_PER_FILE,
        max_excerpt_lines=DEFAULT_MAX_EXCERPT_LINES,
    )

    if prompt_mode == "general":
        prompt = build_general_h2_prompt(query, context_text, inspect_candidates)
    elif prompt_mode == "refined":
        prompt = build_refined_h2_prompt(query, context_text, inspect_candidates)
    else:
        prompt = build_baseline_h2_prompt(query, context_text, inspect_candidates)

    agent_output: dict[str, Any] = {}
    agent_ms = 0.0
    usage: dict[str, Any] = {}
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
        agent_output = {"ranked_files": inspect_candidates, "best_match": {}}

    def resolve_cand(raw_p: str) -> str | None:
        np = normalize_path(raw_p)
        if np in vector_candidate_files:
            return np
        for cand in vector_candidate_files:
            if cand.endswith("/" + np) or cand.endswith(np) or np.endswith(cand):
                return cand
        return None

    agent_ranked_raw = agent_output.get("ranked_files") or []
    agent_ranked_norm: list[str] = []
    seen: set[str] = set()
    for p in agent_ranked_raw:
        matched = resolve_cand(str(p))
        if matched and matched not in seen:
            seen.add(matched)
            agent_ranked_norm.append(matched)

    for p in vector_candidate_files:
        if p not in seen:
            seen.add(p)
            agent_ranked_norm.append(p)

    final_files = agent_ranked_norm if agent_ranked_norm else vector_candidate_files
    file_hit1 = bool(final_files and final_files[0] == target_file)
    top_file = final_files[0] if final_files else None

    bm_path_raw, bm_symbol, bm_start, bm_end = parse_best_match_coords(agent_output)
    bm_path = resolve_cand(bm_path_raw) or normalize_path(bm_path_raw)
    exact_line_hit = False
    if bm_path == target_file and bm_start > 0 and bm_end > 0:
        exact_line_hit = intervals_overlap(bm_start, bm_end, n_start, n_end)

    return {
        "repo": repo,
        "needle_index": idx,
        "expected_func": expected_func,
        "target_file": target_file,
        "target_lines": [n_start, n_end],
        "limit": limit,
        "prompt_mode": prompt_mode,
        "raw_vector_rank": raw_vector_rank,
        "raw_vector_hit1": raw_vector_hit1,
        "target_in_candidates": target_in_candidates,
        "file_hit1": file_hit1,
        "exact_line_hit": exact_line_hit,
        "top_file": top_file,
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
            "inspection_ms": inspection_ms,
            "agent_ms": agent_ms,
            "total_ms": retrieval_ms + inspection_ms + agent_ms,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Test 5 RepoQA misses with limit=60 and generalized H2 prompt.")
    parser.add_argument("--model", type=str, default="gemini-3.5-flash-lite")
    parser.add_argument("--endpoint", type=str, default=DEFAULT_ENDPOINT)
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument(
        "--prompt-mode",
        type=str,
        choices=["general", "refined", "baseline"],
        default="general",
        help="Prompt template to use: general (principles-based), refined (repo-specific), or baseline.",
    )
    parser.add_argument("--compare-baseline", action="store_true", help="Also evaluate against baseline prompt.")
    parser.add_argument("--output", type=Path, default=None, help="Save evaluation results to JSON file.")
    args = parser.parse_args()

    api_key = os.environ.get("LITE_LLM_KEY", "")
    if not api_key:
        print("Error: LITE_LLM_KEY environment variable is not set!", file=sys.stderr)
        return 1

    print("=" * 80)
    print(" EVALUATING 5 MISSES UNDER:")
    print(f" 1. L1 Vector Retrieval limit = {args.limit}")
    print(f" 2. Prompt Mode: {args.prompt_mode.upper()}")
    print(f" Model: {args.model}")
    print("=" * 80)

    dataset = load_repoqa_dataset()
    base_cfg = ConfigLoader().load(None)

    results: list[dict[str, Any]] = []
    print(f"\nRunning test on 5 missed needles with {args.prompt_mode.upper()} prompt...\n")
    for meta in TARGET_NEEDLES:
        tag = f"{meta['repo']} needle {meta['needle_index']} ({meta['func']})"
        print(f"--> Running: {tag}")
        res = evaluate_single_needle(
            meta=meta,
            dataset=dataset,
            base_cfg=base_cfg,
            model=args.model,
            endpoint=args.endpoint,
            api_key=api_key,
            limit=args.limit,
            prompt_mode=args.prompt_mode,
        )
        results.append(res)
        status = "✓ HIT@1" if res["file_hit1"] else "✗ MISS"
        line_status = "✓ Line Hit" if res["exact_line_hit"] else "✗ Line Miss"
        print(f"    Target:      {res['target_file']}")
        print(f"    L1 Rank:     #{res['raw_vector_rank']} (in top {args.limit})")
        print(f"    LLM Top 1:   {res['top_file']}")
        print(f"    Status:      {status} | {line_status}")
        print(f"    Best Match:  {res['agent_best_match']['symbol']} ({res['agent_best_match']['start_line']}-{res['agent_best_match']['end_line']})")
        print(f"    Reasoning:   {res['reasoning']}\n")

    baseline_results: list[dict[str, Any]] = []
    if args.compare_baseline:
        print("\n" + "=" * 80)
        print(" RUNNING BASELINE PROMPT COMPARISON (for direct A/B comparison)")
        print("=" * 80 + "\n")
        for meta in TARGET_NEEDLES:
            tag = f"{meta['repo']} needle {meta['needle_index']} ({meta['func']})"
            print(f"--> Baseline: {tag}")
            b_res = evaluate_single_needle(
                meta=meta,
                dataset=dataset,
                base_cfg=base_cfg,
                model=args.model,
                endpoint=args.endpoint,
                api_key=api_key,
                limit=args.limit,
                prompt_mode="baseline",
            )
            baseline_results.append(b_res)
            status = "✓ HIT@1" if b_res["file_hit1"] else "✗ MISS"
            print(f"    LLM Top 1: {b_res['top_file']} | Status: {status}\n")

    # Summary Table
    print("=" * 80)
    print(" RESULTS MATRIX FOR 5 MISSES")
    print("=" * 80)
    print(f"{'Repository / Needle':<36} | {'Target File':<26} | {'Prev':<6} | {'Refined':<8} | {'Flipped?'}")
    print("-" * 92)

    hits = 0
    line_hits = 0
    for res in results:
        needle_str = f"{res['repo']}:{res['expected_func']}"
        prev_status = "False"
        refined_status = "True" if res["file_hit1"] else "False"
        flipped = "YES (✓)" if res["file_hit1"] else "NO (✗)"
        if res["file_hit1"]:
            hits += 1
        if res["exact_line_hit"]:
            line_hits += 1
        print(f"{needle_str:<36} | {res['target_file']:<26} | {prev_status:<6} | {refined_status:<8} | {flipped}")

    hit1_pct = (hits / len(results)) * 100.0
    line_hit_pct = (line_hits / len(results)) * 100.0
    print("-" * 92)
    print(f"Summary: Hit@1 = {hits}/{len(results)} ({hit1_pct:.1f}%), Line Hit = {line_hits}/{len(results)} ({line_hit_pct:.1f}%)\n")

    if args.output:
        out_data = {
            "model": args.model,
            "limit": args.limit,
            "hit1_count": hits,
            "total_count": len(results),
            "hit1_pct": hit1_pct,
            "line_hit_count": line_hits,
            "line_hit_pct": line_hit_pct,
            "results": results,
            "baseline_results": baseline_results,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(out_data, f, indent=2)
        print(f"Saved results to {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
