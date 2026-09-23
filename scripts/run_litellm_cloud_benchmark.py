#!/usr/bin/env python3
"""Run Benchmark for Cloud / LiteLLM models on the 100 precomputed agent contexts.

Models tested:
1. gpt-5.6-luna
2. gemini-3.5-flash-lite
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import numpy as np

CONTEXTS_PATH = Path("artifacts/research/precomputed_agent_contexts_100.json")
REPORT_PATH = Path("artifacts/research/litellm_cloud_benchmark_report.json")
REPO_ROOT = Path("/Users/iurii.medvedev/Work/intellij-community")
ENDPOINT = "https://litellm.labs.jb.gg/v1/chat/completions"
API_KEY = os.environ.get("LITE_LLM_KEY", "")

MODELS = [
    "gpt-5.6-luna",
    "gemini-3.5-flash-lite",
]

def extract_json_payload(text: str) -> dict:
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return json.loads(text[first_brace:last_brace + 1])
    return json.loads(text)

file_lines_cache = {}

def get_file_lines(rel_path: str) -> int:
    if rel_path in file_lines_cache:
        return file_lines_cache[rel_path]
    p = REPO_ROOT / rel_path
    if not p.is_file():
        file_lines_cache[rel_path] = -1
        return -1
    try:
        with open(p, "rb") as f:
            lines = sum(1 for _ in f)
        file_lines_cache[rel_path] = lines
        return lines
    except Exception:
        file_lines_cache[rel_path] = -1
        return -1

def call_model(model_name: str, prompt: str, max_tokens: int = 1536, temperature: float = 0.1, retries: int = 3):
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }
    if "luna" not in model_name:
        payload["temperature"] = temperature
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT,
        data=data,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
    )

    for attempt in range(retries):
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
            dur_ms = (time.perf_counter() - t0) * 1000.0
            parsed = json.loads(raw)
            choice = parsed["choices"][0]
            text = choice["message"]["content"] or ""
            usage = parsed.get("usage", {})
            completion_tokens = usage.get("completion_tokens", len(text.split()))
            tps = (completion_tokens / (dur_ms / 1000.0)) if dur_ms > 0 else 0.0
            return {
                "text": text,
                "duration_ms": dur_ms,
                "completion_tokens": completion_tokens,
                "tokens_per_sec": tps,
                "error": None,
            }
        except Exception as e:
            if attempt == retries - 1:
                return {
                    "text": "",
                    "duration_ms": 0.0,
                    "completion_tokens": 0,
                    "tokens_per_sec": 0.0,
                    "error": str(e),
                }
            time.sleep(1.0 + attempt)

def evaluate_cloud_model(model_name: str, cases: list, concurrency: int = 4):
    print(f"\n=======================================================")
    print(f"Testing Cloud LiteLLM Model: {model_name} (concurrency={concurrency})")
    print(f"=======================================================")

    results = [None] * len(cases)
    durations = []
    tps_list = []
    json_valid_count = 0
    total_citations = 0
    valid_path_citations = 0
    valid_line_citations = 0
    grounded_citations = 0

    def process_case(idx, case):
        res = call_model(model_name, case["prompt"])
        return idx, case, res

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(process_case, i, c) for i, c in enumerate(cases)]
        for f in as_completed(futures):
            idx, case, gen_res = f.result()
            if gen_res["error"]:
                print(f"Error on case {idx}: {gen_res['error']}")
                continue

            dur_ms = gen_res["duration_ms"]
            tps = gen_res["tokens_per_sec"]
            durations.append(dur_ms)
            tps_list.append(tps)

            context_files = set(case.get("context_files", []))
            try:
                payload = extract_json_payload(gen_res["text"])
                json_valid_count += 1
                citations = payload.get("citations", [])
                if isinstance(citations, list):
                    for cite in citations:
                        total_citations += 1
                        path = str(cite.get("path", "")).strip()
                        lines_str = str(cite.get("lines", "")).strip()

                        if path in context_files:
                            grounded_citations += 1

                        flines = get_file_lines(path)
                        if flines != -1:
                            valid_path_citations += 1

                            line_match = re.search(r"(\d+)(?:\s*-\s*(\d+))?", lines_str)
                            if line_match:
                                start_l = int(line_match.group(1))
                                end_l = int(line_match.group(2)) if line_match.group(2) else start_l
                                if 1 <= start_l <= flines and 1 <= end_l <= flines:
                                    valid_line_citations += 1
            except Exception:
                pass

            if len(durations) % 10 == 0 or len(durations) == len(cases):
                avg_ms = np.mean(durations) if durations else 0
                avg_tps = np.mean(tps_list) if tps_list else 0
                print(f"[{len(durations)}/{len(cases)}] avg lat: {avg_ms:.0f}ms, avg tps: {avg_tps:.1f}, json_valid: {json_valid_count}/{len(durations)}", flush=True)

    n = len(cases)
    return {
        "model": model_name,
        "backend": "litellm_cloud",
        "cases": n,
        "json_valid_rate": json_valid_count / n if n > 0 else 0.0,
        "mean_latency_ms": float(np.mean(durations)) if durations else 0.0,
        "p50_latency_ms": float(np.percentile(durations, 50)) if durations else 0.0,
        "p95_latency_ms": float(np.percentile(durations, 95)) if durations else 0.0,
        "mean_tokens_per_sec": float(np.mean(tps_list)) if tps_list else 0.0,
        "total_citations": total_citations,
        "citation_path_valid_rate": (valid_path_citations / total_citations) if total_citations > 0 else 0.0,
        "citation_line_valid_rate": (valid_line_citations / total_citations) if total_citations > 0 else 0.0,
        "grounded_citation_rate": (grounded_citations / total_citations) if total_citations > 0 else 0.0,
    }

def main():
    with open(CONTEXTS_PATH, "r", encoding="utf-8") as f:
        cases = json.load(f)
    print(f"Loaded {len(cases)} cases from {CONTEXTS_PATH}")

    all_results = []
    for m in MODELS:
        report = evaluate_cloud_model(m, cases, concurrency=8)
        all_results.append(report)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)

    print("\n\n================================ LITELLM CLOUD LEADERBOARD ================================")
    print(f"{'Model':<25} | {'Speed (t/s)':<11} | {'Mean Lat (ms)':<13} | {'p95 Lat (ms)':<13} | {'JSON Valid':<10} | {'Path Valid':<10} | {'Line Valid':<10}")
    print("-" * 110)
    for r in all_results:
        print(f"{r['model']:<25} | {r['mean_tokens_per_sec']:10.1f} | {r['mean_latency_ms']:12.0f} | {r['p95_latency_ms']:12.0f} | {r['json_valid_rate']*100:9.1f}% | {r['citation_path_valid_rate']*100:9.1f}% | {r['citation_line_valid_rate']*100:9.1f}%")
    print("===========================================================================================\n")

if __name__ == "__main__":
    main()
