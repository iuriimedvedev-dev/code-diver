#!/usr/bin/env python3
"""Evaluate chunk-direct LLM reranking on the 5 RepoQA misses.

Instead of `build_agent_context` (which builds file outlines and slices arbitrary excerpts),
this script formats candidate code chunks retrieved directly from vector search into the prompt:
```
Candidate Chunk #1 (File: lib/adapters/xhr.js, Lines: 54-62, Symbol: done, Score: 0.75):
```js
function done() { ... }
```
```
And asks the LLM: Which candidate chunk best matches the query?
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
    result: SearchResult
    is_target: bool
    raw_rank: int


def select_candidate_chunks(
    search_results: list[SearchResult],
    mode: str = "top_chunks",
    top_k: int = 10,
    target_file: str | None = None,
    target_lines: tuple[int, int] | None = None,
) -> tuple[list[CandidateChunk], bool, int | None]:
    """Select candidate chunks based on mode.

    Returns:
        (selected_chunks, target_in_candidates, target_retrieval_rank)
    """
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

    if mode == "top_chunks":
        selected = code_results[:top_k]
    elif mode == "diversified":
        file_counts: dict[str, int] = {}
        selected = []
        max_per_file = 2
        for c in code_results:
            fpath = normalize_path(c.result.item.path)
            count = file_counts.get(fpath, 0)
            if count < max_per_file:
                file_counts[fpath] = count + 1
                selected.append(c)
                if len(selected) >= top_k:
                    break
    elif mode == "include_target":
        # Pure top-K, but if the target was retrieved in search_results, ensure it is included
        selected = code_results[:top_k]
        target_chunk = next((c for c in code_results if c.is_target), None)
        if target_chunk and target_chunk not in selected:
            # Replace the last chunk with target chunk
            selected = selected[: top_k - 1] + [target_chunk]
    else:
        selected = code_results[:top_k]

    target_in_candidates = any(c.is_target for c in selected)
    return selected, target_in_candidates, target_rank


def build_chunk_reranker_prompt(query: str, formatted_chunks: list[str]) -> str:
    chunks_text = "\n\n".join(formatted_chunks)
    return f"""You are an expert code analyst. A developer is searching for a function implementing this exact specification:
\"{query}\"

Below are candidate code chunks retrieved from the repository:

{chunks_text}

GUIDELINES FOR ACCURATE EVALUATION:
1. Target Diversity: The target function can be ANY function in the codebase (production code, test helper, unit test, utility). Treat all candidate chunks equally based strictly on match with the description. Do NOT reject or deprioritize a function because it is in a test file or is a test helper.
2. Signatures & Types: Rigorously match parameter counts, parameter types, variadic arguments, and return types. (e.g. `words ...string` represents an array/list of strings; concrete slice `&[u8]` vs generic parameters).
3. Exact Procedure & Behavior: Check the procedure steps, error conditions, and side effects. Look closely at what behaviors/errors are handled or verified (e.g., handling incomplete data vs complete data). Notice if a candidate does extra work not mentioned in the procedure or matches the procedure exactly.

Task:
1. Carefully evaluate each candidate chunk against the specification.
2. Determine which candidate chunk best matches the query.
3. Rerank the top candidate chunks from most relevant to least relevant by their index.

Respond ONLY with a valid JSON object matching this schema:
{{
  "reasoning": "detailed explanation comparing why the chosen chunk is the best match and why competing candidates are not",
  "best_chunk_index": 1,
  "ranked_chunk_indices": [1, 2, 3],
  "best_match": {{
    "path": "path/to/file",
    "symbol": "symbol_name",
    "start_line": 10,
    "end_line": 20
  }}
}}
"""


def evaluate_needle_chunk_reranker(
    meta: dict[str, Any],
    dataset: dict[str, Any],
    base_cfg: Any,
    model: str,
    endpoint: str,
    api_key: str,
    limit: int = 120,
    top_k: int = 10,
    selection_mode: str = "top_chunks",
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

    t0 = time.perf_counter()
    search_results = strategy.search(query, limit=limit)
    retrieval_ms = (time.perf_counter() - t0) * 1000.0

    selected_chunks, target_in_candidates, target_rank = select_candidate_chunks(
        search_results=search_results,
        mode=selection_mode,
        top_k=top_k,
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

    prompt = build_chunk_reranker_prompt(query, formatted_chunks)

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

    best_idx = agent_output.get("best_chunk_index")
    best_chunk = None
    if isinstance(best_idx, int) and 1 <= best_idx <= len(chunk_meta_list):
        best_chunk = chunk_meta_list[best_idx - 1]

    # Evaluate best match
    bm = agent_output.get("best_match", {})
    bm_path = normalize_path(bm.get("path", "")) if bm.get("path") else (best_chunk["path"] if best_chunk else "")
    bm_start = bm.get("start_line", 0)
    bm_end = bm.get("end_line", 0)

    # File Hit
    file_hit = (bm_path == target_file) or (best_chunk is not None and best_chunk["path"] == target_file)

    # Line/Chunk Hit
    line_hit = False
    if best_chunk and best_chunk["is_target"]:
        line_hit = True
    elif bm_path == target_file and bm_start > 0 and bm_end > 0:
        line_hit = intervals_overlap(bm_start, bm_end, n_start, n_end)

    return {
        "repo": repo,
        "needle_index": idx,
        "func": expected_func,
        "target_file": target_file,
        "target_lines": (n_start, n_end),
        "target_retrieval_rank": target_rank,
        "target_in_candidates": target_in_candidates,
        "file_hit": file_hit,
        "line_hit": line_hit,
        "best_chunk_index": best_idx,
        "chosen_chunk": best_chunk,
        "agent_best_match": bm,
        "reasoning": agent_output.get("reasoning", ""),
        "parse_ok": parse_ok,
        "timings": {
            "retrieval_ms": retrieval_ms,
            "agent_ms": agent_ms,
            "total_ms": retrieval_ms + agent_ms,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate chunk-direct LLM reranking on the 5 RepoQA misses.")
    parser.add_argument("--model", type=str, default="gpt-5.6-luna", help="LiteLLM model name")
    parser.add_argument("--endpoint", type=str, default=DEFAULT_ENDPOINT, help="LiteLLM endpoint")
    parser.add_argument("--limit", type=int, default=120, help="Vector search retrieval limit")
    parser.add_argument("--top-k", type=int, default=10, help="Number of candidate chunks sent to LLM")
    parser.add_argument(
        "--strategy",
        type=str,
        default="top_chunks",
        choices=["top_chunks", "diversified", "include_target"],
        help="Chunk selection strategy",
    )
    parser.add_argument("--needle-idx", type=int, default=None, help="Evaluate specific needle (0-4)")
    args = parser.parse_args()

    api_key = os.environ.get("LITE_LLM_KEY") or os.environ.get("LITELLM_API_KEY", "")
    dataset = load_repoqa_dataset()
    base_cfg = ConfigLoader().load(None)

    targets = TARGET_NEEDLES if args.needle_idx is None else [TARGET_NEEDLES[args.needle_idx]]

    print("=" * 85)
    print("CHUNK-DIRECT LLM RERANKER EVALUATION ON 5 REPOQA MISSES")
    print(f"Model: {args.model} | Strategy: {args.strategy} | Top-K: {args.top_k} | Retrieval Limit: {args.limit}")
    print("=" * 85)

    results = []
    for idx, meta in enumerate(targets):
        repo = meta["repo"]
        func = meta["func"]
        t_file = meta["target_file"]
        print(f"\n[{idx+1}/{len(targets)}] Evaluating {repo} -> `{func}` ({t_file})...")

        res = evaluate_needle_chunk_reranker(
            meta=meta,
            dataset=dataset,
            base_cfg=base_cfg,
            model=args.model,
            endpoint=args.endpoint,
            api_key=api_key,
            limit=args.limit,
            top_k=args.top_k,
            selection_mode=args.strategy,
        )
        results.append(res)

        in_pool = "YES" if res["target_in_candidates"] else "NO"
        f_hit = "PASS" if res["file_hit"] else "FAIL"
        l_hit = "PASS" if res["line_hit"] else "FAIL"
        chosen = res["chosen_chunk"]
        c_desc = f"Chunk #{res['best_chunk_index']} ({chosen['path']}:{chosen['symbol']})" if chosen else "None"

        print(f"  Target in Candidates: {in_pool} (Retrieval Rank #{res['target_retrieval_rank']})")
        print(f"  File Hit: {f_hit} | Chunk/Line Hit: {l_hit}")
        print(f"  Chosen: {c_desc}")
        print(f"  Reasoning: {res['reasoning'][:200]}...")
        print(f"  Timing: {res['timings']['total_ms']:.1f}ms (Agent: {res['timings']['agent_ms']:.1f}ms)")

    print("\n" + "=" * 85)
    print("SUMMARY")
    print("=" * 85)
    total = len(results)
    file_hits = sum(1 for r in results if r["file_hit"])
    line_hits = sum(1 for r in results if r["line_hit"])
    in_cands = sum(1 for r in results if r["target_in_candidates"])

    print(f"Candidates In Pool: {in_cands}/{total} ({in_cands/total*100:.1f}%)")
    print(f"File Hit@1         : {file_hits}/{total} ({file_hits/total*100:.1f}%)")
    print(f"Line/Chunk Hit@1   : {line_hits}/{total} ({line_hits/total*100:.1f}%)")
    print("-" * 85)
    for r in results:
        status = "HIT " if r["file_hit"] else "MISS"
        target_str = f"{r['repo']}::{r['func']} ({r['target_file']})"
        chosen_str = (
            f"{r['chosen_chunk']['path']}::{r['chosen_chunk']['symbol']}"
            if r["chosen_chunk"]
            else "None"
        )
        print(f"[{status}] {target_str:<50} -> {chosen_str}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
