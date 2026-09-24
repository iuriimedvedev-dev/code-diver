#!/usr/bin/env python3
"""Benchmark code-diver in closed-loop agent mode on RepoQA using GPT-5.6-Luna via LiteLLM.

Evaluates on the 20 RepoQA queries (10 from psf/black, 10 from google/gson):
1. Vector retrieval candidate generation
2. Deep inspection context (FileOutlineService + ReadExcerptService)
3. Closed-loop reranking and symbol/line localization with gpt-5.6-luna via LiteLLM
4. Calculates:
   - File Hit@1, File Hit@3, File Hit@5
   - File MRR
   - Line Overlap / Hit (exact target function)
   - Latency (inference time and total closed-loop time)
5. Saves results to .benchmarks/repoqa/agent_gpt56_luna_results.json
6. Produces comparison against raw vector search, Gemma-4-E4B, and jbcontext.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from code_diver.cli import close_vector_store, make_embedding_provider, make_vector_store
from code_diver.config import ConfigLoader
from code_diver.inspection import FileOutlineService, ReadExcerptService
from code_diver.strategies.retrieval_strategy_factory import RetrievalStrategyFactory
from scripts.benchmark_repoqa import dedupe_files, index_repo, intervals_overlap, normalize_path

DEFAULT_DATASET = Path("artifacts/repoqa/repoqa.json.gz")
DEFAULT_BENCHMARKS_DIR = Path(".benchmarks/repoqa")
DEFAULT_OUTPUT = Path(".benchmarks/repoqa/agent_gpt56_luna_results.json")
DEFAULT_ENDPOINT = "https://litellm.labs.jb.gg/v1/chat/completions"
DEFAULT_MODEL = "gpt-5.6-luna"

EVAL_REPOS = [
    {"repo": "psf/black", "language": "python", "slug": "psf_black"},
    {"repo": "google/gson", "language": "java", "slug": "google_gson"},
]


def get_ssl_context() -> ssl.SSLContext:
    """Create a valid SSL context, falling back gracefully."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        try:
            return ssl.create_default_context()
        except Exception:
            return ssl._create_unverified_context()


def extract_json_payload(text: str) -> dict[str, Any]:
    """Robustly extract and parse JSON payload from LLM completion."""
    cleaned = text.strip()
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if match:
        return json.loads(match.group(1))

    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return json.loads(cleaned[first_brace : last_brace + 1])
    return json.loads(cleaned)


def build_agent_context(
    repo_root: Path,
    candidate_files: list[str],
    retrieved_items: list[Any],
    max_symbols_per_file: int = 15,
    max_excerpt_lines: int = 60,
) -> tuple[str, float]:
    """Inspect candidate files using FileOutlineService and ReadExcerptService."""
    t0 = time.perf_counter()
    outline_svc = FileOutlineService(repo_root)
    read_svc = ReadExcerptService(repo_root)

    file_blocks = []
    for fpath in candidate_files:
        norm_path = normalize_path(fpath)
        symbols: list[str] = []
        try:
            outline = outline_svc.structured(norm_path)
            for s in outline.get("symbols", [])[:max_symbols_per_file]:
                symbols.append(f"{s.get('kind')} {s.get('name')} (lines {s.get('startLine')}-{s.get('endLine')})")
        except Exception:
            symbols = []

        hit_lines = [
            r.item.start_line
            for r in retrieved_items
            if normalize_path(r.item.path) == norm_path and r.item.start_line
        ]
        start_line = max(1, hit_lines[0] - 8) if hit_lines else 1

        excerpt_text = ""
        try:
            excerpt_obj = read_svc.structured(norm_path, start_line=start_line, lines=max_excerpt_lines)
            lines_list = excerpt_obj.get("lines", [])
            excerpt_text = "\n".join(f"{l.get('line'):4d} | {l.get('text')}" for l in lines_list[:max_excerpt_lines])
        except Exception:
            excerpt_text = ""

        sym_str = "\n".join(f"  - {s}" for s in symbols) if symbols else "  (none extracted)"
        file_blocks.append(
            f"### File: {norm_path}\n"
            f"Key Symbols:\n{sym_str}\n\n"
            f"Excerpt (lines {start_line}+):\n{excerpt_text}\n"
        )

    context_str = "\n".join(file_blocks)
    inspect_ms = (time.perf_counter() - t0) * 1000.0
    return context_str, inspect_ms


def call_litellm_agent(
    prompt: str,
    model: str = DEFAULT_MODEL,
    endpoint: str = DEFAULT_ENDPOINT,
    api_key: str = "",
    max_tokens: int = 4096,
    retries: int = 3,
) -> tuple[str, float, dict[str, Any]]:
    """Call model through LiteLLM OpenAI-compatible endpoint."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }
    # Note: gpt-5.6-luna errors if temperature != 1 when reasoning is active.
    # We use reasoning_effort="low" so reasoning tokens do not exhaust max_tokens budget.
    if "luna" in model:
        payload["reasoning_effort"] = "low"
    else:
        payload["temperature"] = 0.0

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    ssl_ctx = get_ssl_context()

    last_err: Exception | None = None
    for attempt in range(retries):
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=90, context=ssl_ctx) as resp:
                raw = resp.read().decode("utf-8")
            dur_ms = (time.perf_counter() - t0) * 1000.0
            parsed = json.loads(raw)
            choice = parsed["choices"][0]
            text = (choice["message"].get("content") or "").strip()
            if not text:
                finish = choice.get("finish_reason")
                raise ValueError(f"Empty content received from {model} (finish_reason={finish})")
            usage = parsed.get("usage", {})
            return text, dur_ms, usage
        except Exception as e:
            last_err = e
            time.sleep(2.0 * (attempt + 1))

    raise RuntimeError(f"LiteLLM call failed after {retries} retries: {last_err}")


def query_agent(
    query: str,
    context_text: str,
    candidate_files: list[str],
    model: str,
    endpoint: str,
    api_key: str,
) -> tuple[dict[str, Any], float, dict[str, Any]]:
    """Prompt gpt-5.6-luna to rerank candidates and localize the target function."""
    prompt = f"""You are an expert code analyst. A developer is searching for code implementing this description:
"{query}"

Below are candidate files from the repository with symbol outlines and bounded code excerpts:

{context_text}

Task:
1. Examine the candidate files and their code excerpts.
2. Determine which candidate file and exact function/method implements the described behavior.
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
    raw_text, agent_ms, usage = call_litellm_agent(
        prompt=prompt,
        model=model,
        endpoint=endpoint,
        api_key=api_key,
    )
    parsed = extract_json_payload(raw_text)
    return parsed, agent_ms, usage


def parse_best_match_coords(agent_output: dict[str, Any]) -> tuple[str, str, int, int]:
    """Extract path, symbol, start_line, end_line from agent response."""
    best_match = agent_output.get("best_match") or {}
    path = str(best_match.get("path", "")).strip()
    symbol = str(best_match.get("symbol", "")).strip()
    try:
        s_line = int(best_match.get("start_line", 0) or 0)
        e_line = int(best_match.get("end_line", 0) or 0)
    except (ValueError, TypeError):
        s_line, e_line = 0, 0

    # Fallback to citations if best_match missing
    if not path or s_line == 0:
        citations = agent_output.get("citations") or agent_output.get("citation") or []
        if isinstance(citations, list) and citations:
            c0 = citations[0]
            if isinstance(c0, dict):
                path = str(c0.get("path", "")).strip()
                lines_str = str(c0.get("lines", "")).strip()
                m = re.search(r"(\d+)(?:\s*-\s*(\d+))?", lines_str)
                if m:
                    s_line = int(m.group(1))
                    e_line = int(m.group(2)) if m.group(2) else s_line
                else:
                    try:
                        s_line = int(c0.get("start_line", 0) or 0)
                        e_line = int(c0.get("end_line", 0) or s_line)
                    except (ValueError, TypeError):
                        pass

    return path, symbol, s_line, e_line


def evaluate_needle_closed_loop(
    needle: dict[str, Any],
    needle_index: int,
    strategy: Any,
    repo_root: Path,
    model: str,
    endpoint: str,
    api_key: str,
    limit: int = 10,
    max_inspect_files: int = 4,
) -> dict[str, Any]:
    """Run full closed loop: retrieval -> inspection -> agent rerank."""
    query = needle.get("description", "").strip()
    target_file = normalize_path(needle.get("path", ""))
    n_start = int(needle.get("start_line", 0))
    n_end = int(needle.get("end_line", 0))
    func_name = needle.get("name", "")

    # 1. Retrieval Stage
    t_retrieval_start = time.perf_counter()
    search_results = strategy.search(query, limit=limit)
    retrieval_ms = (time.perf_counter() - t_retrieval_start) * 1000.0

    retrieved_paths = [r.item.path for r in search_results]
    vector_candidate_files = dedupe_files(retrieved_paths)
    raw_vector_hit1 = bool(vector_candidate_files and vector_candidate_files[0] == target_file)

    inspect_candidates = vector_candidate_files[:max_inspect_files]

    # 2. Inspection Stage
    context_text, inspection_ms = build_agent_context(
        repo_root=repo_root,
        candidate_files=inspect_candidates,
        retrieved_items=search_results,
    )

    # 3. Agent Verification & Reranking Stage
    agent_output: dict[str, Any] = {}
    agent_ms = 0.0
    usage: dict[str, Any] = {}
    parse_ok = True
    try:
        agent_output, agent_ms, usage = query_agent(
            query=query,
            context_text=context_text,
            candidate_files=inspect_candidates,
            model=model,
            endpoint=endpoint,
            api_key=api_key,
        )
    except Exception as exc:
        parse_ok = False
        print(f"    [Agent Warning] Needle {needle_index} error: {exc}")
        agent_output = {"ranked_files": inspect_candidates, "best_match": {}}

    total_e2e_ms = retrieval_ms + inspection_ms + agent_ms

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

    # File ranking metrics
    file_hit1 = bool(final_files and final_files[0] == target_file)
    file_hit3 = target_file in final_files[:3]
    file_hit5 = target_file in final_files[:5]
    file_mrr = (1.0 / (final_files.index(target_file) + 1)) if target_file in final_files else 0.0

    # Line Overlap verification
    bm_path_raw, bm_symbol, bm_start, bm_end = parse_best_match_coords(agent_output)
    bm_path = resolve_cand(bm_path_raw) or normalize_path(bm_path_raw)

    exact_line_hit = False
    if bm_path == target_file and bm_start > 0 and bm_end > 0:
        exact_line_hit = intervals_overlap(bm_start, bm_end, n_start, n_end)

    return {
        "needle_index": needle_index,
        "function": func_name,
        "target_file": target_file,
        "lines": [n_start, n_end],
        "raw_vector_hit1": raw_vector_hit1,
        "file_hit1": file_hit1,
        "file_hit3": file_hit3,
        "file_hit5": file_hit5,
        "file_mrr": file_mrr,
        "exact_line_hit": exact_line_hit,
        "agent_best_match": {
            "path": bm_path,
            "symbol": bm_symbol,
            "start_line": bm_start,
            "end_line": bm_end,
        },
        "final_ranked_files": final_files[:5],
        "vector_candidate_files": vector_candidate_files[:5],
        "reasoning": agent_output.get("reasoning", ""),
        "parse_ok": parse_ok,
        "usage": usage,
        "timings": {
            "retrieval_ms": retrieval_ms,
            "inspection_ms": inspection_ms,
            "agent_ms": agent_ms,
            "e2e_ms": total_e2e_ms,
        },
    }


def run_benchmark(
    dataset_path: Path = DEFAULT_DATASET,
    benchmarks_dir: Path = DEFAULT_BENCHMARKS_DIR,
    output_path: Path = DEFAULT_OUTPUT,
    endpoint: str = DEFAULT_ENDPOINT,
    model: str = DEFAULT_MODEL,
    limit: int = 10,
) -> dict[str, Any]:
    """Execute complete closed-loop benchmark using LiteLLM."""
    api_key = os.environ.get("LITE_LLM_KEY", "")
    if not api_key:
        raise ValueError("LITE_LLM_KEY environment variable is not set!")

    print("================================================================================", flush=True)
    print(f" RepoQA Closed-Loop Agent Benchmark ({model} via LiteLLM)", flush=True)
    print("================================================================================", flush=True)
    print(f"Dataset:    {dataset_path}", flush=True)
    print(f"Endpoint:   {endpoint}", flush=True)
    print(f"Model:      {model}", flush=True)
    print(f"Output:     {output_path}", flush=True)
    print("================================================================================\n", flush=True)

    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    with gzip.open(dataset_path, "rt", encoding="utf-8") as f:
        dataset = json.load(f)

    base_config = ConfigLoader().load(None)

    repo_results: list[dict[str, Any]] = []
    overall_t0 = time.perf_counter()

    for target in EVAL_REPOS:
        repo_name = target["repo"]
        lang = target["language"]
        slug = target["slug"]

        entry = next(r for r in dataset[lang] if r["repo"] == repo_name)
        needles = entry.get("needles", [])
        target_dir = benchmarks_dir / lang / slug

        print(f"\n--- Evaluating `{repo_name}` ({lang}, {len(needles)} needles) ---", flush=True)
        config, _ = index_repo(
            target_dir=target_dir,
            base_config=base_config,
            symbol_chunks=True,
            symbol_body=True,
            reindex=False,
        )

        vs = make_vector_store(config)
        provider = make_embedding_provider(config, vs.metadata())
        strategy = RetrievalStrategyFactory().create("vector", config, provider, vs)

        needle_evals = []
        for idx, needle in enumerate(needles):
            print(f"  [{idx+1:2d}/{len(needles)}] Querying agent for `{needle.get('name')}`...", end="\r", flush=True)
            res = evaluate_needle_closed_loop(
                needle=needle,
                needle_index=idx,
                strategy=strategy,
                repo_root=target_dir,
                model=model,
                endpoint=endpoint,
                api_key=api_key,
                limit=limit,
            )
            needle_evals.append(res)
            hit_str = "✓ Hit@1" if res["file_hit1"] else "✗ Miss"
            line_str = "✓ LineHit" if res["exact_line_hit"] else "✗ LineMiss"
            timings = res["timings"]
            print(
                f"  [{idx+1:2d}/{len(needles)}] {needle.get('name'):<30} | "
                f"Target: {res['target_file']:<35} | {hit_str:<8} | {line_str:<10} | "
                f"E2E: {timings['e2e_ms']:.0f}ms (vec:{timings['retrieval_ms']:.0f}ms, "
                f"insp:{timings['inspection_ms']:.0f}ms, agent:{timings['agent_ms']:.0f}ms)",
                flush=True,
            )

        close_vector_store(vs)

        n_count = len(needle_evals) or 1
        raw_vec_h1 = sum(r["raw_vector_hit1"] for r in needle_evals) / n_count
        h1 = sum(r["file_hit1"] for r in needle_evals) / n_count
        h3 = sum(r["file_hit3"] for r in needle_evals) / n_count
        h5 = sum(r["file_hit5"] for r in needle_evals) / n_count
        mrr = sum(r["file_mrr"] for r in needle_evals) / n_count
        line_hit = sum(r["exact_line_hit"] for r in needle_evals) / n_count
        mean_e2e = sum(r["timings"]["e2e_ms"] for r in needle_evals) / n_count
        mean_retrieval = sum(r["timings"]["retrieval_ms"] for r in needle_evals) / n_count
        mean_inspection = sum(r["timings"]["inspection_ms"] for r in needle_evals) / n_count
        mean_agent = sum(r["timings"]["agent_ms"] for r in needle_evals) / n_count

        repo_summary = {
            "repo": repo_name,
            "language": lang,
            "needles_count": n_count,
            "raw_vector_hit1": raw_vec_h1,
            "file_hit1": h1,
            "file_hit3": h3,
            "file_hit5": h5,
            "file_mrr": mrr,
            "exact_line_hit": line_hit,
            "timings": {
                "mean_retrieval_ms": mean_retrieval,
                "mean_inspection_ms": mean_inspection,
                "mean_agent_ms": mean_agent,
                "mean_e2e_ms": mean_e2e,
            },
            "needles": needle_evals,
        }
        repo_results.append(repo_summary)

        print(
            f"\n  Summary `{repo_name}`: "
            f"Raw Vector Hit@1: {raw_vec_h1:.1%} -> Agent Hit@1: {h1:.1%} | "
            f"Hit@3: {h3:.1%} | MRR: {mrr:.3f} | Line Hit: {line_hit:.1%} | "
            f"Agent Latency: {mean_agent:.1f}ms | Mean E2E: {mean_e2e:.1f}ms",
            flush=True,
        )

    total_wall_s = time.perf_counter() - overall_t0

    total_needles = sum(r["needles_count"] for r in repo_results)
    avg_raw_h1 = sum(r["raw_vector_hit1"] * r["needles_count"] for r in repo_results) / total_needles
    avg_h1 = sum(r["file_hit1"] * r["needles_count"] for r in repo_results) / total_needles
    avg_h3 = sum(r["file_hit3"] * r["needles_count"] for r in repo_results) / total_needles
    avg_h5 = sum(r["file_hit5"] * r["needles_count"] for r in repo_results) / total_needles
    avg_mrr = sum(r["file_mrr"] * r["needles_count"] for r in repo_results) / total_needles
    avg_line = sum(r["exact_line_hit"] * r["needles_count"] for r in repo_results) / total_needles
    avg_agent = sum(r["timings"]["mean_agent_ms"] * r["needles_count"] for r in repo_results) / total_needles
    avg_e2e = sum(r["timings"]["mean_e2e_ms"] * r["needles_count"] for r in repo_results) / total_needles

    report = {
        "model": model,
        "backend": f"LiteLLM ({endpoint})",
        "mode": "closed_loop_agent",
        "total_cases": total_needles,
        "total_wall_time_s": total_wall_s,
        "overall": {
            "raw_vector_hit1": avg_raw_h1,
            "file_hit1": avg_h1,
            "file_hit3": avg_h3,
            "file_hit5": avg_h5,
            "file_mrr": avg_mrr,
            "exact_line_hit": avg_line,
            "mean_agent_latency_ms": avg_agent,
            "mean_e2e_latency_ms": avg_e2e,
        },
        "baselines_reference": {
            "raw_vector_hit1": 0.55,
            "gemma4_hit1": 0.90,
            "gemma4_line_overlap": 0.70,
            "jbcontext_hit1": 1.00,
            "jbcontext_line_overlap": 0.80,
        },
        "repositories": repo_results,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"\nSaved benchmark results to {output_path}")

    print_comparison_report(report)
    return report


def print_comparison_report(report: dict[str, Any]) -> None:
    """Print comparative table against baselines."""
    print("\n" + "=" * 115)
    print("                     RepoQA EVALUATION: CLOSED-LOOP AGENT vs BASELINES")
    print("=" * 115)
    headers = [
        "System / Approach",
        "Cases",
        "File Hit@1",
        "File Hit@3",
        "File Hit@5",
        "File MRR",
        "Line Overlap",
        "Agent Lat",
        "Total E2E Lat",
    ]
    sep = ["-" * len(h) for h in headers]
    fmt = "{:<32} | {:<5} | {:<10} | {:<10} | {:<10} | {:<8} | {:<12} | {:<10} | {:<13}"
    print(fmt.format(*headers))
    print(fmt.format(*sep))

    # Baseline 1: Raw Vector Search
    print(
        fmt.format(
            "code-diver Raw Vector",
            "20",
            "55.0%",
            "90.0%",
            "90.0%",
            "0.717",
            "40.0%",
            "-",
            "~293 ms",
        )
    )

    # Local Gemma 4 E4B Agent
    print(
        fmt.format(
            "code-diver Agent (Gemma-4-E4B)",
            "20",
            "90.0%",
            "90.0%",
            "90.0%",
            "0.900",
            "70.0%",
            "~7,411 ms",
            "~7,912 ms",
        )
    )

    # Cloud GPT-5.6-Luna Agent
    ov = report["overall"]
    print(
        fmt.format(
            f"code-diver Agent ({report['model']})",
            str(report["total_cases"]),
            f"{ov['file_hit1']:.1%}",
            f"{ov['file_hit3']:.1%}",
            f"{ov['file_hit5']:.1%}",
            f"{ov['file_mrr']:.3f}",
            f"{ov['exact_line_hit']:.1%}",
            f"{ov['mean_agent_latency_ms']:.0f} ms",
            f"{ov['mean_e2e_latency_ms']:.0f} ms",
        )
    )

    # Baseline 2: JetBrains Context
    print(
        fmt.format(
            "JetBrains Context (jbcontext)",
            "20",
            "100.0%",
            "100.0%",
            "100.0%",
            "1.000",
            "80.0%",
            "-",
            "1,546 ms",
        )
    )
    print("=" * 115 + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate code-diver in closed-loop agent mode on RepoQA with LiteLLM.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--benchmarks-dir", type=Path, default=DEFAULT_BENCHMARKS_DIR)
    parser.add_argument("--endpoint", type=str, default=DEFAULT_ENDPOINT)
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=10)

    args = parser.parse_args()
    run_benchmark(
        dataset_path=args.dataset,
        benchmarks_dir=args.benchmarks_dir,
        output_path=args.output,
        endpoint=args.endpoint,
        model=args.model,
        limit=args.limit,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
