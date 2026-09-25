#!/usr/bin/env python3
"""Benchmark RepoQA 600 needles across all 60 repos using Dual-Context Cascade with Gemini 3.5 Flash Lite.

Dual-Context Architecture:
1. Vector retrieval candidate generation (default limit=120)
2. Section 1: Top 10 retrieved code chunks with line boundaries and scores
3. Section 2: Candidate file symbol outlines (up to 5 candidate files) with module purposes
4. Unified LLM evaluation with cascade instructions (gemini-3.5-flash-lite via LiteLLM)
5. Parallel execution with ThreadPoolExecutor for high-throughput LLM evaluation
6. Incremental per-repo checkpointing to avoid losing progress
7. Comprehensive evaluation:
   - File Hit@1, File Hit@3, File Hit@5, File MRR
   - Line Overlap (exact function boundary overlap)
   - Source distribution (Chunk vs Outline fallback)
   - Per-language and per-repository breakdown
   - End-to-end latency metrics
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import gzip
import json
import os
from pathlib import Path
import re
import ssl
import sys
import time
from typing import Any
import urllib.error
import urllib.request

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from code_diver.cli import close_vector_store, make_embedding_provider, make_vector_store
from code_diver.config import ConfigLoader
from code_diver.inspection.file_outline_service import FileOutlineService
from code_diver.services.code_symbol_extractor import CodeSymbolExtractor
from code_diver.services.file_summary_item_builder import FileSummaryItemBuilder
from code_diver.strategies.retrieval_strategy_factory import RetrievalStrategyFactory
from scripts.benchmark_repoqa import (
    dedupe_files,
    index_repo,
    intervals_overlap,
    normalize_path,
    slugify_repo,
)
from scripts.benchmark_repoqa_agent_litellm import EVAL_REPOS_100

DEFAULT_DATASET = PROJECT_ROOT / "artifacts" / "repoqa" / "repoqa.json.gz"
DEFAULT_BENCHMARKS_DIR = PROJECT_ROOT / ".benchmarks" / "repoqa"
DEFAULT_OUTPUT = PROJECT_ROOT / ".benchmarks" / "repoqa" / "agent_gemini35_cascade_600.json"
DEFAULT_ENDPOINT = "https://litellm.labs.jb.gg/v1/chat/completions"
DEFAULT_MODEL = "gemini-3.5-flash-lite"
DEFAULT_LIMIT = 120
DEFAULT_TOP_CHUNKS_K = 10
DEFAULT_TOP_FILES_K = 5
DEFAULT_MAX_SYMBOLS_PER_FILE = 120
DEFAULT_WORKERS = 10

KNOWN_SLUGS: dict[str, str] = {r["repo"]: r["slug"] for r in EVAL_REPOS_100}
ALL_LANGUAGES: list[str] = ["python", "cpp", "java", "typescript", "rust", "go"]


def get_repo_slug(repo_name: str) -> str:
    """Return directory slug for repository, respecting known benchmark slugs."""
    return KNOWN_SLUGS.get(repo_name, slugify_repo(repo_name))


def get_ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    except Exception:
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx
        except Exception:
            return ssl._create_unverified_context()


def load_repoqa_dataset(dataset_path: Path = DEFAULT_DATASET) -> dict[str, Any]:
    with gzip.open(dataset_path, "rt", encoding="utf-8") as f:
        return json.load(f)


def discover_all_benchmark_repos(
    dataset: dict[str, Any],
    benchmarks_dir: Path = DEFAULT_BENCHMARKS_DIR,
) -> list[dict[str, Any]]:
    """Discover all 60 benchmark repos in dataset order across all 6 languages."""
    repos: list[dict[str, Any]] = []
    for lang in ALL_LANGUAGES:
        entries = dataset.get(lang, [])
        for entry in entries:
            repo_name = entry.get("repo", "")
            slug = get_repo_slug(repo_name)
            target_dir = benchmarks_dir / lang / slug
            repos.append({
                "repo": repo_name,
                "language": lang,
                "slug": slug,
                "path": target_dir,
                "needles": entry.get("needles", []),
            })
    return repos


def call_litellm_agent(
    prompt: str,
    model: str = DEFAULT_MODEL,
    endpoint: str = DEFAULT_ENDPOINT,
    api_key: str = "",
    max_tokens: int = 4096,
    retries: int = 3,
) -> tuple[str, float, dict[str, Any]]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }
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


def extract_json_payload(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    candidate_str = match.group(1) if match else None

    if candidate_str:
        try:
            return json.loads(candidate_str)
        except Exception:
            pass

    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        snippet = cleaned[first_brace : last_brace + 1]
        try:
            return json.loads(snippet)
        except Exception:
            pass

    res: dict[str, Any] = {}
    best_match_block = re.search(r'"best_match"\s*:\s*(\{[^\}]*\})', cleaned)
    if best_match_block:
        try:
            res["best_match"] = json.loads(best_match_block.group(1))
        except Exception:
            bm: dict[str, Any] = {}
            for k in ("path", "symbol", "start_line", "end_line"):
                m = re.search(rf'"{k}"\s*:\s*([^,\n\}}]+)', best_match_block.group(1))
                if m:
                    val = m.group(1).strip(' "\'\t')
                    if k in ("start_line", "end_line"):
                        try:
                            bm[k] = int(val)
                        except Exception:
                            bm[k] = None
                    else:
                        bm[k] = val
            res["best_match"] = bm

    for k in ("source", "reasoning"):
        m = re.search(rf'"{k}"\s*:\s*"([^"]*)"', cleaned)
        if m:
            res[k] = m.group(1)

    m_idx = re.search(r'"best_chunk_index"\s*:\s*(\d+)', cleaned)
    if m_idx:
        res["best_chunk_index"] = int(m_idx.group(1))

    if res:
        return res

    return json.loads(cleaned)


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
    outline_svc: FileOutlineService,
    extractor: CodeSymbolExtractor,
    builder: FileSummaryItemBuilder,
    cache: dict[str, str] | None = None,
    max_symbols_per_file: int = 120,
) -> str:
    file_sections: list[str] = []
    for cf in candidate_files:
        norm_cf = normalize_path(cf)
        if cache is not None and norm_cf in cache:
            file_sections.append(cache[norm_cf])
            continue

        full_path = repo_root / norm_cf
        file_summary_desc = ""
        symbols_list: list[dict[str, Any]] = []

        if full_path.is_file():
            try:
                text = full_path.read_text(encoding="utf-8", errors="replace")
                syms = extractor.extract(norm_cf, text)
                summary_item = builder.build(norm_cf, text, syms)
                summary_lines = [
                    l for l in summary_item.content.splitlines() if l.startswith("purpose: ") or l.startswith("terms: ")
                ]
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

        section_text = (
            f"### File: {norm_cf}\n"
            f"{summary_block}"
            f"Defined Symbols ({len(symbols_list)}):\n"
            f"{symbols_block}"
        )
        if cache is not None:
            cache[norm_cf] = section_text
        file_sections.append(section_text)

    return "\n\n".join(file_sections)


def build_unified_prompt(query: str, formatted_chunks: list[str], outlines_text: str) -> str:
    chunks_text = "\n\n".join(formatted_chunks) if formatted_chunks else "(No raw code chunks retrieved for this repository)"
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


@dataclass
class NeedleContext:
    meta: dict[str, Any]
    needle: dict[str, Any]
    target_file: str
    expected_func: str
    n_start: int
    n_end: int
    prompt: str
    chunk_meta_list: list[dict[str, Any]]
    candidate_files: list[str]
    raw_vector_hit1: bool
    retrieval_ms: float
    outlines_ms: float


def prepare_needle_context(
    meta: dict[str, Any],
    needle: dict[str, Any],
    strategy: Any,
    repo_dir: Path,
    outline_svc: FileOutlineService,
    extractor: CodeSymbolExtractor,
    builder: FileSummaryItemBuilder,
    outline_cache: dict[str, str],
    limit: int = DEFAULT_LIMIT,
    top_chunks_k: int = DEFAULT_TOP_CHUNKS_K,
    top_files_k: int = DEFAULT_TOP_FILES_K,
    max_symbols_per_file: int = DEFAULT_MAX_SYMBOLS_PER_FILE,
) -> NeedleContext:
    lang = meta["language"]
    query = needle["description"].strip()
    target_file = normalize_path(needle.get("path") or needle.get("file_path", ""))
    expected_func = needle.get("name") or needle.get("function_name", "")
    n_start = int(needle["start_line"])
    n_end = int(needle["end_line"])

    t0_retrieval = time.perf_counter()
    search_results = strategy.search(query, limit=limit)
    retrieval_ms = (time.perf_counter() - t0_retrieval) * 1000.0

    retrieved_paths = [r.item.path for r in search_results]
    vector_candidate_files = dedupe_files(retrieved_paths)
    candidate_files = vector_candidate_files[:top_files_k]
    raw_vector_hit1 = bool(
        vector_candidate_files
        and (
            vector_candidate_files[0] == target_file
            or vector_candidate_files[0].endswith("/" + target_file)
            or target_file.endswith("/" + vector_candidate_files[0])
        )
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

    t0_outlines = time.perf_counter()
    outlines_text = build_candidate_outlines(
        repo_root=repo_dir,
        candidate_files=candidate_files,
        outline_svc=outline_svc,
        extractor=extractor,
        builder=builder,
        cache=outline_cache,
        max_symbols_per_file=max_symbols_per_file,
    )
    outlines_ms = (time.perf_counter() - t0_outlines) * 1000.0

    uni_prompt = build_unified_prompt(query, formatted_chunks, outlines_text)

    return NeedleContext(
        meta=meta,
        needle=needle,
        target_file=target_file,
        expected_func=expected_func,
        n_start=n_start,
        n_end=n_end,
        prompt=uni_prompt,
        chunk_meta_list=chunk_meta_list,
        candidate_files=candidate_files,
        raw_vector_hit1=raw_vector_hit1,
        retrieval_ms=retrieval_ms,
        outlines_ms=outlines_ms,
    )


def score_needle_response(
    ctx: NeedleContext,
    raw_response: str,
    agent_ms: float,
    usage: dict[str, Any],
    outline_svc: FileOutlineService | None = None,
    max_symbols_per_file: int = DEFAULT_MAX_SYMBOLS_PER_FILE,
) -> dict[str, Any]:
    needle_index = ctx.meta["needle_index"]
    target_file = ctx.target_file
    expected_func = ctx.expected_func
    n_start = ctx.n_start
    n_end = ctx.n_end
    candidate_files = ctx.candidate_files
    chunk_meta_list = ctx.chunk_meta_list

    try:
        agent_output = extract_json_payload(raw_response)
    except Exception as e:
        agent_output = {"reasoning": f"JSON decode error: {e}", "best_match": {}}

    reasoning = agent_output.get("reasoning", "")
    source = agent_output.get("source", "chunk")
    best_chunk_idx = agent_output.get("best_chunk_index")
    if isinstance(best_chunk_idx, str) and best_chunk_idx.isdigit():
        best_chunk_idx = int(best_chunk_idx)

    matching_chunk = None
    if isinstance(best_chunk_idx, int) and 1 <= best_chunk_idx <= len(chunk_meta_list):
        matching_chunk = chunk_meta_list[best_chunk_idx - 1]

    bm = agent_output.get("best_match") or {}
    bm_path_raw = bm.get("path") or (matching_chunk["path"] if matching_chunk else "")
    bm_path = normalize_path(bm_path_raw)

    # Resolve candidate file path
    for cf in candidate_files:
        if bm_path == cf or cf.endswith("/" + bm_path) or bm_path.endswith("/" + cf):
            bm_path = cf
            break

    bm_symbol = bm.get("symbol") or (matching_chunk["symbol"] if matching_chunk else "")
    bm_start = int(bm.get("start_line", 0)) if bm.get("start_line") is not None else 0
    bm_end = int(bm.get("end_line", 0)) if bm.get("end_line") is not None else 0

    if (bm_start == 0 or bm_end == 0) and matching_chunk:
        bm_start = matching_chunk["start_line"]
        bm_end = matching_chunk["end_line"]
        if not bm_path:
            bm_path = matching_chunk["path"]

    # Construct final ranked files
    final_files: list[str] = []
    seen: set[str] = set()
    if bm_path:
        final_files.append(bm_path)
        seen.add(bm_path)
    for f in candidate_files:
        if f not in seen and not any(f == x or f.endswith("/" + x) or x.endswith("/" + f) for x in seen):
            seen.add(f)
            final_files.append(f)

    # Compute File Hit metrics
    file_hit1 = (bm_path == target_file) or (
        bm_path.endswith("/" + target_file) or target_file.endswith("/" + bm_path)
    )
    file_hit3 = any(f == target_file or f.endswith("/" + target_file) or target_file.endswith("/" + f) for f in final_files[:3])
    file_hit5 = any(f == target_file or f.endswith("/" + target_file) or target_file.endswith("/" + f) for f in final_files[:5])

    file_mrr = 0.0
    for r_idx, f in enumerate(final_files, 1):
        if f == target_file or f.endswith("/" + target_file) or target_file.endswith("/" + f):
            file_mrr = 1.0 / r_idx
            break

    # Compute Line Overlap
    line_hit = False
    if file_hit1:
        if source == "chunk" and matching_chunk and matching_chunk["is_target"]:
            line_hit = True
        elif bm_start > 0 and bm_end > 0 and intervals_overlap(bm_start, bm_end, n_start, n_end):
            line_hit = True
        elif bm_symbol:
            clean_sym = bm_symbol.split(".")[-1].split("::")[-1].strip()
            if clean_sym == expected_func or bm_symbol == expected_func:
                line_hit = True
            elif outline_svc is not None:
                # Check symbol outline for target file
                try:
                    outline = outline_svc.structured(target_file, symbol_limit=max_symbols_per_file)
                    for s in outline.get("symbols", []):
                        if s["name"] == bm_symbol or s["name"] == clean_sym:
                            if intervals_overlap(s["startLine"], s["endLine"], n_start, n_end):
                                line_hit = True
                                break
                except Exception:
                    pass

    total_e2e_ms = ctx.retrieval_ms + ctx.outlines_ms + agent_ms

    return {
        "needle_index": needle_index,
        "function": expected_func,
        "target_file": target_file,
        "lines": [n_start, n_end],
        "raw_vector_hit1": ctx.raw_vector_hit1,
        "file_hit1": file_hit1,
        "file_hit3": file_hit3,
        "file_hit5": file_hit5,
        "file_mrr": file_mrr,
        "exact_line_hit": line_hit,
        "source": source,
        "best_chunk_index": best_chunk_idx,
        "agent_best_match": {
            "path": bm_path,
            "symbol": bm_symbol,
            "start_line": bm_start,
            "end_line": bm_end,
        },
        "final_ranked_files": final_files[:5],
        "candidate_files": candidate_files[:5],
        "reasoning": reasoning,
        "usage": usage,
        "timings": {
            "retrieval_ms": ctx.retrieval_ms,
            "outlines_ms": ctx.outlines_ms,
            "agent_ms": agent_ms,
            "e2e_ms": total_e2e_ms,
        },
    }


def evaluate_needle_worker(
    ctx: NeedleContext,
    model: str,
    endpoint: str,
    api_key: str,
    outline_svc: FileOutlineService | None = None,
    max_symbols_per_file: int = DEFAULT_MAX_SYMBOLS_PER_FILE,
) -> dict[str, Any]:
    try:
        raw_response, agent_ms, usage = call_litellm_agent(
            prompt=ctx.prompt,
            model=model,
            endpoint=endpoint,
            api_key=api_key,
        )
        return score_needle_response(
            ctx=ctx,
            raw_response=raw_response,
            agent_ms=agent_ms,
            usage=usage,
            outline_svc=outline_svc,
            max_symbols_per_file=max_symbols_per_file,
        )
    except Exception as e:
        # Fallback in case of exhausted retries/network errors
        return {
            "needle_index": ctx.meta["needle_index"],
            "function": ctx.expected_func,
            "target_file": ctx.target_file,
            "lines": [ctx.n_start, ctx.n_end],
            "raw_vector_hit1": ctx.raw_vector_hit1,
            "file_hit1": False,
            "file_hit3": False,
            "file_hit5": False,
            "file_mrr": 0.0,
            "exact_line_hit": False,
            "source": "error",
            "best_chunk_index": None,
            "agent_best_match": {"path": "", "symbol": "", "start_line": 0, "end_line": 0},
            "final_ranked_files": [],
            "candidate_files": ctx.candidate_files[:5],
            "reasoning": f"Execution error: {e}",
            "usage": {},
            "timings": {
                "retrieval_ms": ctx.retrieval_ms,
                "outlines_ms": ctx.outlines_ms,
                "agent_ms": 0.0,
                "e2e_ms": ctx.retrieval_ms + ctx.outlines_ms,
            },
            "error": str(e),
        }


def compute_metrics_summary(repo_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute overall and per-language metrics across repository summaries."""
    total_needles = sum(r["needles_count"] for r in repo_summaries)
    if total_needles == 0:
        return {}

    def weighted_avg(metric_key: str) -> float:
        return sum(r[metric_key] * r["needles_count"] for r in repo_summaries) / total_needles

    def timing_weighted_avg(timing_key: str) -> float:
        return sum(r["timings"][timing_key] * r["needles_count"] for r in repo_summaries) / total_needles

    overall = {
        "raw_vector_hit1": weighted_avg("raw_vector_hit1"),
        "file_hit1": weighted_avg("file_hit1"),
        "file_hit3": weighted_avg("file_hit3"),
        "file_hit5": weighted_avg("file_hit5"),
        "file_mrr": weighted_avg("file_mrr"),
        "exact_line_hit": weighted_avg("exact_line_hit"),
        "chunk_source_ratio": weighted_avg("chunk_source_ratio"),
        "mean_retrieval_latency_ms": timing_weighted_avg("mean_retrieval_ms"),
        "mean_outlines_latency_ms": timing_weighted_avg("mean_outlines_ms"),
        "mean_agent_latency_ms": timing_weighted_avg("mean_agent_ms"),
        "mean_e2e_latency_ms": timing_weighted_avg("mean_e2e_ms"),
    }

    # Per-language breakdown
    by_language: dict[str, dict[str, Any]] = {}
    for lang in ALL_LANGUAGES:
        lang_repos = [r for r in repo_summaries if r["language"] == lang]
        l_needles = sum(r["needles_count"] for r in lang_repos)
        if l_needles == 0:
            continue

        by_language[lang] = {
            "repos_count": len(lang_repos),
            "needles_count": l_needles,
            "raw_vector_hit1": sum(r["raw_vector_hit1"] * r["needles_count"] for r in lang_repos) / l_needles,
            "file_hit1": sum(r["file_hit1"] * r["needles_count"] for r in lang_repos) / l_needles,
            "file_hit3": sum(r["file_hit3"] * r["needles_count"] for r in lang_repos) / l_needles,
            "file_hit5": sum(r["file_hit5"] * r["needles_count"] for r in lang_repos) / l_needles,
            "file_mrr": sum(r["file_mrr"] * r["needles_count"] for r in lang_repos) / l_needles,
            "exact_line_hit": sum(r["exact_line_hit"] * r["needles_count"] for r in lang_repos) / l_needles,
            "chunk_source_ratio": sum(r["chunk_source_ratio"] * r["needles_count"] for r in lang_repos) / l_needles,
            "mean_agent_latency_ms": sum(r["timings"]["mean_agent_ms"] * r["needles_count"] for r in lang_repos) / l_needles,
            "mean_e2e_latency_ms": sum(r["timings"]["mean_e2e_ms"] * r["needles_count"] for r in lang_repos) / l_needles,
        }

    return {"overall": overall, "by_language": by_language}


def save_checkpoint(
    output_path: Path,
    model: str,
    endpoint: str,
    total_cases: int,
    wall_time_s: float,
    repo_summaries: list[dict[str, Any]],
) -> None:
    metrics = compute_metrics_summary(repo_summaries)
    report = {
        "model": model,
        "backend": f"LiteLLM ({endpoint})",
        "mode": "unified_dual_context_cascade",
        "total_cases": total_cases,
        "total_wall_time_s": wall_time_s,
        "overall": metrics.get("overall", {}),
        "by_language": metrics.get("by_language", {}),
        "baselines_reference": {
            "jbcontext_100": {
                "file_hit1": 0.98,
                "file_hit3": 1.00,
                "line_overlap1": 0.87,
            },
            "gemini35_standard_agent_100": {
                "file_hit1": 0.95,
                "file_hit3": 0.98,
                "exact_line_hit": 0.87,
            },
        },
        "repositories": repo_summaries,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(".tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    temp_path.replace(output_path)


def print_comparison_tables(report: dict[str, Any]) -> None:
    # 1. Per-Language Table
    by_lang = report.get("by_language", {})
    if by_lang:
        print("\n" + "=" * 105)
        print("                        PER-LANGUAGE PERFORMANCE BREAKDOWN")
        print("=" * 105)
        l_hdr = ["Language", "Repos", "Needles", "File Hit@1", "File Hit@3", "File MRR", "Line Overlap", "Chunk Ratio", "Agent Lat"]
        l_fmt = "{:<12} | {:<5} | {:<7} | {:<10} | {:<10} | {:<8} | {:<12} | {:<11} | {:<10}"
        print(l_fmt.format(*l_hdr))
        print(l_fmt.format(*["-" * len(h) for h in l_hdr]))
        for lang, s in by_lang.items():
            print(
                l_fmt.format(
                    lang,
                    str(s["repos_count"]),
                    str(s["needles_count"]),
                    f"{s['file_hit1']:.1%}",
                    f"{s['file_hit3']:.1%}",
                    f"{s['file_mrr']:.3f}",
                    f"{s['exact_line_hit']:.1%}",
                    f"{s['chunk_source_ratio']:.1%}",
                    f"{s['mean_agent_latency_ms']:.0f} ms",
                )
            )
        print("=" * 105)

    # 2. Overall Comparison Table
    print("\n" + "=" * 115)
    print("                     RepoQA BENCHMARK: DUAL-CONTEXT CASCADE vs BASELINES")
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
    fmt = "{:<36} | {:<5} | {:<10} | {:<10} | {:<10} | {:<8} | {:<12} | {:<10} | {:<13}"
    print(fmt.format(*headers))
    print(fmt.format(*["-" * len(h) for h in headers]))

    ov = report.get("overall", {})
    total_cases = report.get("total_cases", 0)

    # Reference Baselines (100 needles)
    print(
        fmt.format(
            "code-diver Raw Vector (100 n)",
            "100",
            "79.0%",
            "93.0%",
            "96.0%",
            "0.892",
            "52.0%",
            "-",
            "~320 ms",
        )
    )
    print(
        fmt.format(
            "JetBrains Context (jbcontext 100 n)",
            "100",
            "98.0%",
            "100.0%",
            "100.0%",
            "0.990",
            "87.0%",
            "-",
            "~1,580 ms",
        )
    )

    # Current Cascade Agent
    if ov:
        print(
            fmt.format(
                f"code-diver Cascade ({report['model']})",
                str(total_cases),
                f"{ov.get('file_hit1', 0.0):.1%}",
                f"{ov.get('file_hit3', 0.0):.1%}",
                f"{ov.get('file_hit5', 0.0):.1%}",
                f"{ov.get('file_mrr', 0.0):.3f}",
                f"{ov.get('exact_line_hit', 0.0):.1%}",
                f"{ov.get('mean_agent_latency_ms', 0.0):.0f} ms",
                f"{ov.get('mean_e2e_latency_ms', 0.0):.0f} ms",
            )
        )
    print("=" * 115)


def run_benchmark(
    dataset_path: Path = DEFAULT_DATASET,
    benchmarks_dir: Path = DEFAULT_BENCHMARKS_DIR,
    output_path: Path = DEFAULT_OUTPUT,
    model: str = DEFAULT_MODEL,
    endpoint: str = DEFAULT_ENDPOINT,
    limit: int = DEFAULT_LIMIT,
    top_chunks_k: int = DEFAULT_TOP_CHUNKS_K,
    top_files_k: int = DEFAULT_TOP_FILES_K,
    max_symbols_per_file: int = DEFAULT_MAX_SYMBOLS_PER_FILE,
    languages: list[str] | None = None,
    repos_filter: list[str] | None = None,
    workers: int = DEFAULT_WORKERS,
    resume: bool = False,
) -> dict[str, Any]:
    api_key = os.environ.get("LITE_LLM_KEY") or os.environ.get("LITELLM_API_KEY", "")
    dataset = load_repoqa_dataset(dataset_path)
    base_cfg = ConfigLoader().load(None)

    all_repos = discover_all_benchmark_repos(dataset, benchmarks_dir)

    # Filter languages
    if languages:
        lang_set = set(l.lower() for l in languages)
        all_repos = [r for r in all_repos if r["language"].lower() in lang_set]

    # Filter repos
    if repos_filter:
        filter_set = set(repos_filter)
        all_repos = [
            r for r in all_repos
            if r["repo"] in filter_set or r["slug"] in filter_set or any(f in r["repo"] for f in filter_set)
        ]

    if not all_repos:
        raise ValueError("No repositories matched the specified filters!")

    # Resume support
    repo_summaries: list[dict[str, Any]] = []
    completed_slugs: set[str] = set()

    if resume and output_path.exists():
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                prev_data = json.load(f)
            prev_repos = prev_data.get("repositories", [])
            for pr in prev_repos:
                completed_slugs.add(pr["slug"])
                repo_summaries.append(pr)
            print(f"Resuming benchmark: loaded {len(repo_summaries)} already evaluated repositories from {output_path}")
        except Exception as e:
            print(f"Warning: could not resume from {output_path}: {e}")

    total_needles_count = sum(len(r["needles"]) for r in all_repos)

    print("=" * 95)
    print(f"RUNNING REPOQA DUAL-CONTEXT CASCADE BENCHMARK (ALL)")
    print(f"Model: {model} | Top Chunks: {top_chunks_k} | Top Files: {top_files_k} | Limit: {limit}")
    print(f"Endpoint: {endpoint} | Workers: {workers}")
    print(f"Total Repositories: {len(all_repos)} repos ({total_needles_count} needles)")
    if completed_slugs:
        print(f"Already Completed: {len(completed_slugs)} repos (Remaining: {len(all_repos) - len(completed_slugs)})")
    print("=" * 95)

    overall_t0 = time.perf_counter()

    for r_idx, repo_meta in enumerate(all_repos, 1):
        repo_name = repo_meta["repo"]
        lang = repo_meta["language"]
        slug = repo_meta["slug"]
        repo_dir = repo_meta["path"]
        needles = repo_meta["needles"]

        if slug in completed_slugs:
            print(f"[{r_idx}/{len(all_repos)}] Skipping already evaluated `{repo_name}` ({lang})", flush=True)
            continue

        print(f"\n[{r_idx}/{len(all_repos)}] Evaluating `{repo_name}` ({lang}, {len(needles)} needles)...", flush=True)

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
        outline_svc = FileOutlineService(repo_dir)
        extractor = CodeSymbolExtractor()
        builder = FileSummaryItemBuilder(compact_budget=True)
        outline_cache: dict[str, str] = {}

        # 1. Prepare search contexts (retrieval + outlines)
        contexts: list[NeedleContext] = []
        for n_idx, needle in enumerate(needles):
            eval_meta = {
                "language": lang,
                "repo": repo_name,
                "slug": slug,
                "needle_index": n_idx,
            }
            ctx = prepare_needle_context(
                meta=eval_meta,
                needle=needle,
                strategy=strategy,
                repo_dir=repo_dir,
                outline_svc=outline_svc,
                extractor=extractor,
                builder=builder,
                outline_cache=outline_cache,
                limit=limit,
                top_chunks_k=top_chunks_k,
                top_files_k=top_files_k,
                max_symbols_per_file=max_symbols_per_file,
            )
            contexts.append(ctx)

        # Vector store can be closed now since all retrieval queries for this repo are done
        close_vector_store(vs)

        # 2. Execute LLM evaluations in parallel with ThreadPoolExecutor
        actual_workers = max(1, min(workers, len(contexts)))
        needle_evals_by_idx: dict[int, dict[str, Any]] = {}

        if actual_workers > 1:
            with ThreadPoolExecutor(max_workers=actual_workers) as executor:
                future_to_idx = {
                    executor.submit(
                        evaluate_needle_worker,
                        ctx,
                        model,
                        endpoint,
                        api_key,
                        outline_svc,
                        max_symbols_per_file,
                    ): ctx.meta["needle_index"]
                    for ctx in contexts
                }

                for future in as_completed(future_to_idx):
                    n_idx = future_to_idx[future]
                    res = future.result()
                    needle_evals_by_idx[n_idx] = res

                    status_f = "✓" if res["file_hit1"] else "✗"
                    status_l = "✓" if res["exact_line_hit"] else "✗"
                    src_str = f"[{res['source'].upper()[:5]}]"
                    fn_desc = f"{res['function']}"
                    bm = res["agent_best_match"]
                    bm_str = f"{bm['path']}:{bm['symbol']} ({bm['start_line']}-{bm['end_line']})"
                    print(
                        f"  [{n_idx+1:2d}/{len(needles)}] File:{status_f} Line:{status_l} {src_str} {fn_desc:<25} -> {bm_str:<45} ({res['timings']['e2e_ms']:.0f}ms)",
                        flush=True,
                    )
        else:
            for ctx in contexts:
                n_idx = ctx.meta["needle_index"]
                res = evaluate_needle_worker(
                    ctx,
                    model,
                    endpoint,
                    api_key,
                    outline_svc,
                    max_symbols_per_file,
                )
                needle_evals_by_idx[n_idx] = res

                status_f = "✓" if res["file_hit1"] else "✗"
                status_l = "✓" if res["exact_line_hit"] else "✗"
                src_str = f"[{res['source'].upper()[:5]}]"
                fn_desc = f"{res['function']}"
                bm = res["agent_best_match"]
                bm_str = f"{bm['path']}:{bm['symbol']} ({bm['start_line']}-{bm['end_line']})"
                print(
                    f"  [{n_idx+1:2d}/{len(needles)}] File:{status_f} Line:{status_l} {src_str} {fn_desc:<25} -> {bm_str:<45} ({res['timings']['e2e_ms']:.0f}ms)",
                    flush=True,
                )

        needle_evals = [needle_evals_by_idx[i] for i in range(len(needles))]

        # Compute repo summary metrics
        n_count = len(needle_evals)
        h1 = sum(1 for r in needle_evals if r["file_hit1"]) / n_count
        h3 = sum(1 for r in needle_evals if r["file_hit3"]) / n_count
        h5 = sum(1 for r in needle_evals if r["file_hit5"]) / n_count
        mrr = sum(r["file_mrr"] for r in needle_evals) / n_count
        l_hit = sum(1 for r in needle_evals if r["exact_line_hit"]) / n_count
        raw_vec_h1 = sum(1 for r in needle_evals if r["raw_vector_hit1"]) / n_count
        chunk_source_count = sum(1 for r in needle_evals if r["source"] == "chunk")

        mean_retrieval = sum(r["timings"]["retrieval_ms"] for r in needle_evals) / n_count
        mean_outlines = sum(r["timings"]["outlines_ms"] for r in needle_evals) / n_count
        mean_agent = sum(r["timings"]["agent_ms"] for r in needle_evals) / n_count
        mean_e2e = sum(r["timings"]["e2e_ms"] for r in needle_evals) / n_count

        repo_summary = {
            "repo": repo_name,
            "language": lang,
            "slug": slug,
            "needles_count": n_count,
            "raw_vector_hit1": raw_vec_h1,
            "file_hit1": h1,
            "file_hit3": h3,
            "file_hit5": h5,
            "file_mrr": mrr,
            "exact_line_hit": l_hit,
            "chunk_source_ratio": chunk_source_count / n_count,
            "timings": {
                "mean_retrieval_ms": mean_retrieval,
                "mean_outlines_ms": mean_outlines,
                "mean_agent_ms": mean_agent,
                "mean_e2e_ms": mean_e2e,
            },
            "needles": needle_evals,
        }
        repo_summaries.append(repo_summary)
        completed_slugs.add(slug)

        print(
            f"  >> Summary `{repo_name}`: "
            f"File Hit@1: {h1:.1%} | Hit@3: {h3:.1%} | MRR: {mrr:.3f} | Line Overlap: {l_hit:.1%} | "
            f"Chunks: {chunk_source_count}/{n_count} | Latency: {mean_e2e:.0f}ms (Agent: {mean_agent:.0f}ms)",
            flush=True,
        )

        # Incremental checkpoint save after every repository
        wall_time_so_far = time.perf_counter() - overall_t0
        total_eval_needles = sum(r["needles_count"] for r in repo_summaries)
        save_checkpoint(
            output_path=output_path,
            model=model,
            endpoint=endpoint,
            total_cases=total_eval_needles,
            wall_time_s=wall_time_so_far,
            repo_summaries=repo_summaries,
        )

        curr_metrics = compute_metrics_summary(repo_summaries)["overall"]
        print(
            f"  >> Cumulative [{len(repo_summaries)}/{len(all_repos)} repos | {total_eval_needles}/{total_needles_count} needles]: "
            f"File Hit@1: {curr_metrics['file_hit1']:.1%} | MRR: {curr_metrics['file_mrr']:.3f} | Line Overlap: {curr_metrics['exact_line_hit']:.1%} (checkpoint saved)",
            flush=True,
        )

    total_wall_s = time.perf_counter() - overall_t0
    total_eval_needles = sum(r["needles_count"] for r in repo_summaries)

    save_checkpoint(
        output_path=output_path,
        model=model,
        endpoint=endpoint,
        total_cases=total_eval_needles,
        wall_time_s=total_wall_s,
        repo_summaries=repo_summaries,
    )

    with open(output_path, "r", encoding="utf-8") as f:
        final_report = json.load(f)

    # Print summary tables
    print_comparison_tables(final_report)
    print(f"\nFinal benchmark results successfully saved to: {output_path}")
    print(f"Total Wall Time: {total_wall_s:.1f}s ({total_wall_s/60:.2f} min) across {total_eval_needles} needles.")
    return final_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RepoQA 600 benchmark across all 60 repos with Dual-Context Cascade.")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help=f"LiteLLM model (default: {DEFAULT_MODEL})")
    parser.add_argument("--endpoint", type=str, default=DEFAULT_ENDPOINT, help=f"LiteLLM endpoint (default: {DEFAULT_ENDPOINT})")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help=f"Output path (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"Vector retrieval candidate limit (default: {DEFAULT_LIMIT})")
    parser.add_argument("--top-chunks-k", type=int, default=DEFAULT_TOP_CHUNKS_K, help=f"Candidate chunks in prompt (default: {DEFAULT_TOP_CHUNKS_K})")
    parser.add_argument("--top-files-k", type=int, default=DEFAULT_TOP_FILES_K, help=f"Candidate files for outlines (default: {DEFAULT_TOP_FILES_K})")
    parser.add_argument("--max-symbols", type=int, default=DEFAULT_MAX_SYMBOLS_PER_FILE, help=f"Max symbols per file in outline (default: {DEFAULT_MAX_SYMBOLS_PER_FILE})")
    parser.add_argument("--languages", nargs="+", default=None, help="Subset of languages to benchmark (e.g. python java cpp typescript rust go)")
    parser.add_argument("--repos", nargs="+", default=None, help="Subset of repositories or slugs to benchmark (e.g. psf/black nom)")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help=f"Parallel worker threads for LLM calls (default: {DEFAULT_WORKERS})")
    parser.add_argument("--resume", action="store_true", default=False, help="Resume benchmark from existing output file checkpoint")
    args = parser.parse_args()

    run_benchmark(
        output_path=args.output,
        model=args.model,
        endpoint=args.endpoint,
        limit=args.limit,
        top_chunks_k=args.top_chunks_k,
        top_files_k=args.top_files_k,
        max_symbols_per_file=args.max_symbols,
        languages=args.languages,
        repos_filter=args.repos,
        workers=args.workers,
        resume=args.resume,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
