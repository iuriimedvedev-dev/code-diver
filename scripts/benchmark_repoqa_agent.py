#!/usr/bin/env python3
"""Benchmark code-diver in closed-loop agent mode on RepoQA (psf/black & google/gson).

Uses local llama-server running gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf on Apple Silicon (Metal).
Measures:
  - File Hit@1, Hit@3, Hit@5
  - File MRR
  - Exact Line Overlap / Hit
  - Stage timings & End-to-end Latency (retrieval + inspection + agent verification)

Compares results against:
  - Raw Vector Search baseline (55% Hit@1)
  - JetBrains Context (jbcontext) baseline (100% Hit@1)
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import signal
import subprocess
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
from code_diver.config import AppConfig, ConfigLoader
from code_diver.inspection import FileOutlineService, ReadExcerptService
from code_diver.strategies.retrieval_strategy_factory import RetrievalStrategyFactory
from scripts.benchmark_repoqa import dedupe_files, index_repo, intervals_overlap, normalize_path, slugify_repo

DEFAULT_DATASET = Path("artifacts/repoqa/repoqa.json.gz")
DEFAULT_BENCHMARKS_DIR = Path(".benchmarks/repoqa")
DEFAULT_MODEL_PATH = Path(".code-diver/models/gemma-4-e4b-it-qat-GGUF/gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf")
DEFAULT_LLAMA_SERVER = Path("/opt/homebrew/bin/llama-server")
DEFAULT_OUTPUT = Path(".benchmarks/repoqa/agent_gemma4_e4b_results.json")
PORT = 18080

EVAL_REPOS = [
    {"repo": "psf/black", "language": "python", "slug": "psf_black"},
    {"repo": "google/gson", "language": "java", "slug": "google_gson"},
]


def stop_any_server_on_port(port: int) -> None:
    """Kill any existing process on port."""
    try:
        out = subprocess.check_output(["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"], text=True)
        for pid_str in out.strip().splitlines():
            if pid_str.strip():
                pid = int(pid_str.strip())
                os.kill(pid, signal.SIGKILL)
        time.sleep(0.5)
    except Exception:
        pass


class LlamaServerManager:
    """Context manager to spawn and cleanly terminate llama-server."""

    def __init__(
        self,
        model_path: Path,
        server_bin: Path = DEFAULT_LLAMA_SERVER,
        port: int = PORT,
        ctx_size: int = 8192,
        n_gpu_layers: int = 99,
    ):
        self.model_path = model_path.resolve()
        self.server_bin = server_bin.resolve()
        self.port = port
        self.ctx_size = ctx_size
        self.n_gpu_layers = n_gpu_layers
        self.proc: subprocess.Popen | None = None
        self.log_file = None

    def __enter__(self) -> LlamaServerManager:
        stop_any_server_on_port(self.port)
        if not self.model_path.is_file():
            raise FileNotFoundError(f"GGUF model not found at {self.model_path}")
        if not self.server_bin.is_file():
            raise FileNotFoundError(f"llama-server binary not found at {self.server_bin}")

        log_path = Path(f"/tmp/llama-server-{self.port}.log")
        self.log_file = open(log_path, "w", encoding="utf-8")

        cmd = [
            str(self.server_bin),
            "-m", str(self.model_path),
            "--host", "127.0.0.1",
            "--port", str(self.port),
            "-ngl", str(self.n_gpu_layers),
            "-c", str(self.ctx_size),
            "--parallel", "1",
            "--reasoning", "off",
        ]
        print(f"[LlamaServer] Launching: {' '.join(cmd)}")
        self.proc = subprocess.Popen(cmd, stdout=self.log_file, stderr=self.log_file)
        self._wait_ready()
        print(f"[LlamaServer] Ready on port {self.port} (Metal ngl={self.n_gpu_layers}, ctx={self.ctx_size})")
        return self

    def _wait_ready(self, timeout_s: float = 60.0) -> None:
        t0 = time.time()
        url = f"http://127.0.0.1:{self.port}/v1/models"
        while time.time() - t0 < timeout_s:
            if self.proc and self.proc.poll() is not None:
                raise RuntimeError(f"llama-server exited prematurely with returncode {self.proc.returncode}")
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    if resp.status == 200:
                        return
            except Exception:
                time.sleep(0.5)
        raise TimeoutError(f"llama-server failed to respond on port {self.port} within {timeout_s}s")

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        print("[LlamaServer] Shutting down server...")
        if self.proc is not None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
        if self.log_file is not None:
            self.log_file.close()
        stop_any_server_on_port(self.port)
        print("[LlamaServer] Cleanly terminated.")


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
        # Outline inspection
        symbols: list[str] = []
        try:
            outline = outline_svc.structured(norm_path)
            for s in outline.get("symbols", [])[:max_symbols_per_file]:
                symbols.append(f"{s.get('kind')} {s.get('name')} (lines {s.get('startLine')}-{s.get('endLine')})")
        except Exception:
            symbols = []

        # Find best starting line for excerpt reading from retrieval hits
        hit_lines = [
            r.item.start_line
            for r in retrieved_items
            if normalize_path(r.item.path) == norm_path and r.item.start_line
        ]
        start_line = max(1, hit_lines[0] - 8) if hit_lines else 1

        # Read bounded excerpt
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


def query_agent(
    port: int,
    query: str,
    context_text: str,
    candidate_files: list[str],
) -> tuple[dict[str, Any], float]:
    """Call LLM via llama-server OpenAI-compatible API to perform closed-loop verification."""
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
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 384,
    }
    url = f"http://127.0.0.1:{port}/v1/chat/completions"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})

    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as resp:
        res_data = json.loads(resp.read().decode("utf-8"))
    agent_ms = (time.perf_counter() - t0) * 1000.0

    content = res_data["choices"][0]["message"]["content"]
    parsed = extract_json_payload(content)
    return parsed, agent_ms


def evaluate_needle_closed_loop(
    needle: dict[str, Any],
    needle_index: int,
    strategy: Any,
    repo_root: Path,
    port: int,
    limit: int = 10,
    max_inspect_files: int = 4,
) -> dict[str, Any]:
    """Run full closed loop for a single RepoQA needle: retrieval -> inspection -> agent rerank."""
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

    # Top candidates for deep inspection
    inspect_candidates = vector_candidate_files[:max_inspect_files]

    # 2. Inspection Stage
    context_text, inspection_ms = build_agent_context(
        repo_root=repo_root,
        candidate_files=inspect_candidates,
        retrieved_items=search_results,
    )

    # 3. Agent Verification & Reranking Stage
    agent_output = {}
    agent_ms = 0.0
    parse_ok = True
    try:
        agent_output, agent_ms = query_agent(
            port=port,
            query=query,
            context_text=context_text,
            candidate_files=inspect_candidates,
        )
    except Exception as exc:
        parse_ok = False
        print(f"    [Agent Warning] Failed to parse agent JSON on needle {needle_index}: {exc}")
        agent_output = {"ranked_files": inspect_candidates, "best_match": {}}

    total_e2e_ms = retrieval_ms + inspection_ms + agent_ms

    # Extract final ranked files with fuzzy path matching
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

    # Append any candidate files that the agent omitted to preserve candidate pool
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
    best_match = agent_output.get("best_match", {})
    bm_raw_path = str(best_match.get("path", ""))
    bm_path = resolve_cand(bm_raw_path) or normalize_path(bm_raw_path)
    try:
        bm_start = int(best_match.get("start_line", 0))
        bm_end = int(best_match.get("end_line", 0))
    except (ValueError, TypeError):
        bm_start, bm_end = 0, 0

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
        "agent_best_match": best_match,
        "final_ranked_files": final_files[:5],
        "vector_candidate_files": vector_candidate_files[:5],
        "reasoning": agent_output.get("reasoning", ""),
        "parse_ok": parse_ok,
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
    model_path: Path = DEFAULT_MODEL_PATH,
    output_path: Path = DEFAULT_OUTPUT,
    port: int = PORT,
    limit: int = 10,
) -> dict[str, Any]:
    """Execute complete benchmark over RepoQA target repositories."""
    print("================================================================================")
    print(" RepoQA Closed-Loop Agent Benchmark (gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf)")
    print("================================================================================")
    print(f"Dataset:    {dataset_path}")
    print(f"Corpora:    {benchmarks_dir}")
    print(f"Model GGUF: {model_path}")
    print(f"Port:       {port}")
    print("================================================================================\n")

    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    with gzip.open(dataset_path, "rt", encoding="utf-8") as f:
        dataset = json.load(f)

    base_config = ConfigLoader().load(None)

    repo_results: list[dict[str, Any]] = []
    overall_t0 = time.perf_counter()

    with LlamaServerManager(model_path=model_path, port=port):
        for target in EVAL_REPOS:
            repo_name = target["repo"]
            lang = target["language"]
            slug = target["slug"]

            entry = next(r for r in dataset[lang] if r["repo"] == repo_name)
            needles = entry.get("needles", [])
            target_dir = benchmarks_dir / lang / slug

            print(f"\n--- Evaluating `{repo_name}` ({lang}, {len(needles)} needles) ---")
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
                res = evaluate_needle_closed_loop(
                    needle=needle,
                    needle_index=idx,
                    strategy=strategy,
                    repo_root=target_dir,
                    port=port,
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
                    f"insp:{timings['inspection_ms']:.0f}ms, agent:{timings['agent_ms']:.0f}ms)"
                )

            close_vector_store(vs)

            # Summarize repository metrics
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
                f"Mean E2E: {mean_e2e:.1f}ms"
            )

    total_wall_s = time.perf_counter() - overall_t0

    # Aggregates across all repos
    total_needles = sum(r["needles_count"] for r in repo_results)
    avg_raw_h1 = sum(r["raw_vector_hit1"] * r["needles_count"] for r in repo_results) / total_needles
    avg_h1 = sum(r["file_hit1"] * r["needles_count"] for r in repo_results) / total_needles
    avg_h3 = sum(r["file_hit3"] * r["needles_count"] for r in repo_results) / total_needles
    avg_h5 = sum(r["file_hit5"] * r["needles_count"] for r in repo_results) / total_needles
    avg_mrr = sum(r["file_mrr"] * r["needles_count"] for r in repo_results) / total_needles
    avg_line = sum(r["exact_line_hit"] * r["needles_count"] for r in repo_results) / total_needles
    avg_e2e = sum(r["timings"]["mean_e2e_ms"] * r["needles_count"] for r in repo_results) / total_needles

    report = {
        "model": "gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf",
        "backend": "llama-server Metal",
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
            "mean_e2e_latency_ms": avg_e2e,
        },
        "baselines_reference": {
            "raw_vector_hit1": 0.55,
            "jbcontext_hit1": 1.00,
        },
        "repositories": repo_results,
    }

    # Save to output path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"\nSaved benchmark results to {output_path}")

    # Print comparative report table
    print_comparison_report(report)
    return report


def print_comparison_report(report: dict[str, Any]) -> None:
    """Print comparative table against baselines."""
    print("\n" + "=" * 105)
    print("                     RepoQA EVALUATION: CLOSED-LOOP AGENT vs BASELINES")
    print("=" * 105)
    headers = [
        "System / Approach",
        "Cases",
        "File Hit@1",
        "File Hit@3",
        "File Hit@5",
        "File MRR",
        "Line Overlap",
        "Mean Latency",
    ]
    sep = ["-" * len(h) for h in headers]
    fmt = "{:<32} | {:<5} | {:<10} | {:<10} | {:<10} | {:<8} | {:<12} | {:<12}"
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
            "~293 ms",
        )
    )

    # Agent Mode
    ov = report["overall"]
    print(
        fmt.format(
            "code-diver Agent (Gemma-4-E4B)",
            str(report["total_cases"]),
            f"{ov['file_hit1']:.1%}",
            f"{ov['file_hit3']:.1%}",
            f"{ov['file_hit5']:.1%}",
            f"{ov['file_mrr']:.3f}",
            f"{ov['exact_line_hit']:.1%}",
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
            "1,546 ms",
        )
    )
    print("=" * 105 + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate code-diver in closed-loop agent mode on RepoQA.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--benchmarks-dir", type=Path, default=DEFAULT_BENCHMARKS_DIR)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--server-bin", type=Path, default=DEFAULT_LLAMA_SERVER)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=10)

    args = parser.parse_args()
    run_benchmark(
        dataset_path=args.dataset,
        benchmarks_dir=args.benchmarks_dir,
        model_path=args.model,
        output_path=args.output,
        port=args.port,
        limit=args.limit,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
