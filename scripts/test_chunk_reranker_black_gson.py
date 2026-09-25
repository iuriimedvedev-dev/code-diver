#!/usr/bin/env python3
"""Verify chunk-direct LLM reranking on the standard 20 needles from psf/black and google/gson.

Uses Gemini 3.5 Flash Lite via LiteLLM to evaluate candidate code chunks
retrieved directly from vector search.
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

from code_diver.cli import close_vector_store, make_embedding_provider, make_vector_store
from code_diver.config import ConfigLoader
from code_diver.strategies.retrieval_strategy_factory import RetrievalStrategyFactory
from scripts.benchmark_repoqa import dedupe_files, index_repo, intervals_overlap, normalize_path
from scripts.benchmark_repoqa_agent_litellm import (
    DEFAULT_ENDPOINT,
    call_litellm_agent,
    extract_json_payload,
)

EVAL_REPOS = [
    {"repo": "psf/black", "language": "python", "slug": "psf_black"},
    {"repo": "google/gson", "language": "java", "slug": "google_gson"},
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
    mode: str = "top_chunks",
    top_k: int = 10,
    target_file: str | None = None,
    target_lines: tuple[int, int] | None = None,
) -> tuple[list[CandidateChunk], bool, int | None]:
    """Select candidate code chunks based on retrieval order or diversification."""
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
        selected = code_results[:top_k]
        target_chunk = next((c for c in code_results if c.is_target), None)
        if target_chunk and target_chunk not in selected:
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


def compute_line_iou(s1: int, e1: int, s2: int, e2: int) -> float:
    inter = max(0, min(e1, e2) - max(s1, s2) + 1)
    if inter == 0:
        return 0.0
    union = (e1 - s1 + 1) + (e2 - s2 + 1) - inter
    return inter / union if union > 0 else 0.0


def evaluate_single_needle(
    repo: str,
    lang: str,
    idx: int,
    needle: dict[str, Any],
    strategy: Any,
    model: str,
    endpoint: str,
    api_key: str,
    limit: int = 120,
    top_k: int = 10,
    selection_mode: str = "top_chunks",
) -> dict[str, Any]:
    target_file = normalize_path(needle["path"])
    expected_func = needle.get("name") or "unknown"
    query = needle["description"].strip()
    n_start = int(needle["start_line"])
    n_end = int(needle["end_line"])

    t0 = time.perf_counter()
    search_results = strategy.search(query, limit=limit)
    retrieval_ms = (time.perf_counter() - t0) * 1000.0

    # Raw vector file hit@1
    raw_vector_hit1 = False
    if search_results:
        raw_vector_hit1 = (normalize_path(search_results[0].item.path) == target_file)

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
    usage: dict[str, Any] = {}
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

    bm = agent_output.get("best_match", {})
    bm_path = normalize_path(bm.get("path", "")) if bm.get("path") else (best_chunk["path"] if best_chunk else "")
    bm_start = bm.get("start_line", 0) or 0
    bm_end = bm.get("end_line", 0) or 0

    # File Hit@1: rank #1 chunk belongs to target_file OR model identified target_file
    file_hit = (bm_path == target_file) or (best_chunk is not None and best_chunk["path"] == target_file)

    # Line Overlap / Hit
    line_overlap = False
    line_iou = 0.0
    if best_chunk and best_chunk["is_target"]:
        line_overlap = True
        line_iou = compute_line_iou(best_chunk["start_line"], best_chunk["end_line"], n_start, n_end)
    elif best_chunk and best_chunk["path"] == target_file:
        line_overlap = intervals_overlap(best_chunk["start_line"], best_chunk["end_line"], n_start, n_end)
        line_iou = compute_line_iou(best_chunk["start_line"], best_chunk["end_line"], n_start, n_end)
    elif bm_path == target_file and bm_start > 0 and bm_end > 0:
        line_overlap = intervals_overlap(bm_start, bm_end, n_start, n_end)
        line_iou = compute_line_iou(bm_start, bm_end, n_start, n_end)

    return {
        "repo": repo,
        "needle_index": idx,
        "func": expected_func,
        "target_file": target_file,
        "target_lines": [n_start, n_end],
        "target_retrieval_rank": target_rank,
        "target_in_candidates": target_in_candidates,
        "raw_vector_hit1": raw_vector_hit1,
        "file_hit": file_hit,
        "line_overlap": line_overlap,
        "line_iou": round(line_iou, 4),
        "best_chunk_index": best_idx,
        "chosen_chunk": best_chunk,
        "agent_best_match": bm,
        "reasoning": agent_output.get("reasoning", ""),
        "parse_ok": parse_ok,
        "usage": usage,
        "timings": {
            "retrieval_ms": retrieval_ms,
            "agent_ms": agent_ms,
            "total_ms": retrieval_ms + agent_ms,
        },
    }


def run_verification(
    model: str = "gemini-3.5-flash-lite",
    endpoint: str = DEFAULT_ENDPOINT,
    limit: int = 120,
    top_k: int = 10,
    strategy: str = "top_chunks",
    output_path: Path | None = None,
) -> dict[str, Any]:
    api_key = os.environ.get("LITE_LLM_KEY") or os.environ.get("LITELLM_API_KEY", "")
    if not api_key:
        raise ValueError("LITE_LLM_KEY or LITELLM_API_KEY environment variable is not set!")

    dataset = load_repoqa_dataset()
    base_cfg = ConfigLoader().load(None)

    print("=" * 90)
    print("VERIFYING CHUNK-DIRECT RERANKER ON 20 NEEDLES (black & gson)")
    print(f"Model: {model} | Selection Strategy: {strategy} | Top-K Chunks: {top_k} | Retrieval Limit: {limit}")
    print("=" * 90)

    all_results: list[dict[str, Any]] = []
    repo_summaries: list[dict[str, Any]] = []

    for repo_spec in EVAL_REPOS:
        repo_name = repo_spec["repo"]
        lang = repo_spec["language"]
        slug = repo_spec["slug"]

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
        retrieval_strategy = RetrievalStrategyFactory().create("vector", config, provider, vs)

        repo_entry = next(r for r in dataset[lang] if r["repo"] == repo_name)
        needles = repo_entry.get("needles", [])

        print(f"\n--- Testing {repo_name} ({lang}, {len(needles)} needles) ---")

        repo_needle_results = []
        for idx, needle in enumerate(needles):
            func_name = needle.get("name") or "unknown"
            t_file = normalize_path(needle["path"])
            print(f"[{idx+1}/{len(needles)}] {repo_name} -> `{func_name}` ({t_file})...", end="", flush=True)

            res = evaluate_single_needle(
                repo=repo_name,
                lang=lang,
                idx=idx,
                needle=needle,
                strategy=retrieval_strategy,
                model=model,
                endpoint=endpoint,
                api_key=api_key,
                limit=limit,
                top_k=top_k,
                selection_mode=strategy,
            )
            repo_needle_results.append(res)
            all_results.append(res)

            status_f = "✓" if res["file_hit"] else "✗"
            status_l = "✓" if res["line_overlap"] else "✗"
            in_pool = "Y" if res["target_in_candidates"] else "N"
            t_ms = res["timings"]["total_ms"]
            a_ms = res["timings"]["agent_ms"]
            print(f" FileHit={status_f} LineOverlap={status_l} (InPool={in_pool}, Rank={res['target_retrieval_rank']}) Latency={t_ms:.0f}ms (LLM: {a_ms:.0f}ms)")

        close_vector_store(vs)

        # Summary for this repo
        n_count = len(repo_needle_results)
        f_hits = sum(1 for r in repo_needle_results if r["file_hit"])
        l_hits = sum(1 for r in repo_needle_results if r["line_overlap"])
        raw_hits = sum(1 for r in repo_needle_results if r["raw_vector_hit1"])
        in_cands = sum(1 for r in repo_needle_results if r["target_in_candidates"])
        avg_retrieval_ms = sum(r["timings"]["retrieval_ms"] for r in repo_needle_results) / n_count
        avg_agent_ms = sum(r["timings"]["agent_ms"] for r in repo_needle_results) / n_count
        avg_total_ms = sum(r["timings"]["total_ms"] for r in repo_needle_results) / n_count
        avg_iou = sum(r["line_iou"] for r in repo_needle_results) / n_count

        repo_summary = {
            "repo": repo_name,
            "language": lang,
            "needles_count": n_count,
            "raw_vector_hit1": raw_hits / n_count,
            "file_hit1": f_hits / n_count,
            "line_overlap": l_hits / n_count,
            "mean_line_iou": round(avg_iou, 4),
            "target_in_candidates": in_cands / n_count,
            "timings": {
                "mean_retrieval_ms": avg_retrieval_ms,
                "mean_agent_ms": avg_agent_ms,
                "mean_total_ms": avg_total_ms,
            },
        }
        repo_summaries.append(repo_summary)

    # Overall metrics
    total_needles = len(all_results)
    overall_f_hit = sum(1 for r in all_results if r["file_hit"]) / total_needles
    overall_l_hit = sum(1 for r in all_results if r["line_overlap"]) / total_needles
    overall_raw_hit = sum(1 for r in all_results if r["raw_vector_hit1"]) / total_needles
    overall_in_pool = sum(1 for r in all_results if r["target_in_candidates"]) / total_needles
    overall_mean_agent_ms = sum(r["timings"]["agent_ms"] for r in all_results) / total_needles
    overall_mean_total_ms = sum(r["timings"]["total_ms"] for r in all_results) / total_needles
    overall_mean_iou = sum(r["line_iou"] for r in all_results) / total_needles

    report = {
        "model": model,
        "strategy": strategy,
        "top_k": top_k,
        "limit": limit,
        "total_cases": total_needles,
        "overall": {
            "raw_vector_hit1": overall_raw_hit,
            "file_hit1": overall_f_hit,
            "line_overlap": overall_l_hit,
            "mean_line_iou": round(overall_mean_iou, 4),
            "target_in_candidates": overall_in_pool,
            "mean_agent_latency_ms": overall_mean_agent_ms,
            "mean_total_latency_ms": overall_mean_total_ms,
        },
        "repositories": repo_summaries,
        "results": all_results,
    }

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"\nSaved results to {output_path}")

    # Print final summary table
    print("\n" + "=" * 90)
    print(f"BENCHMARK REPORT: CHUNK-DIRECT RERANKER ({model})")
    print("=" * 90)
    print(f"{'Repository':<15} | {'Needles':<8} | {'Raw Hit@1':<10} | {'File Hit@1':<11} | {'Line Overlap':<12} | {'Avg Agent ms':<12} | {'Avg Total ms':<12}")
    print("-" * 90)
    for s in repo_summaries:
        print(
            f"{s['repo']:<15} | "
            f"{s['needles_count']:<8} | "
            f"{s['raw_vector_hit1']:>8.1%}   | "
            f"{s['file_hit1']:>9.1%}   | "
            f"{s['line_overlap']:>10.1%}   | "
            f"{s['timings']['mean_agent_ms']:>10.1f}ms | "
            f"{s['timings']['mean_total_ms']:>10.1f}ms"
        )
    print("-" * 90)
    print(
        f"{'OVERALL':<15} | "
        f"{total_needles:<8} | "
        f"{overall_raw_hit:>8.1%}   | "
        f"{overall_f_hit:>9.1%}   | "
        f"{overall_l_hit:>10.1%}   | "
        f"{overall_mean_agent_ms:>10.1f}ms | "
        f"{overall_mean_total_ms:>10.1f}ms"
    )
    print("=" * 90)

    print("\nPer-Needle Detailed Breakdown:")
    for r in all_results:
        f_sym = "✓" if r["file_hit"] else "✗"
        l_sym = "✓" if r["line_overlap"] else "✗"
        chosen_info = (
            f"Chunk #{r['best_chunk_index']} ({r['chosen_chunk']['path']}:{r['chosen_chunk']['symbol']} L{r['chosen_chunk']['start_line']}-{r['chosen_chunk']['end_line']})"
            if r["chosen_chunk"]
            else f"BestMatch ({r['agent_best_match'].get('path')}:{r['agent_best_match'].get('symbol')})"
        )
        print(f"[{f_sym} File | {l_sym} Line] {r['repo']} #{r['needle_index']} ({r['func']}): {chosen_info} [{r['timings']['total_ms']:.0f}ms]")

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify chunk-direct reranker on 20 needles (black & gson).")
    parser.add_argument("--model", type=str, default="gemini-3.5-flash-lite", help="LiteLLM model name")
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
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / ".benchmarks/repoqa/chunk_reranker_gemini35_black_gson.json",
        help="Output JSON file",
    )
    args = parser.parse_args()

    run_verification(
        model=args.model,
        endpoint=args.endpoint,
        limit=args.limit,
        top_k=args.top_k,
        strategy=args.strategy,
        output_path=args.output,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
