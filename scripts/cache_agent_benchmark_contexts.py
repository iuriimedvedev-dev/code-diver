#!/usr/bin/env python3
"""Run retrieval and context assembly for 100 cases and cache to disk.
This creates a standalone benchmark dataset containing pre-computed retrieval and context,
allowing pure LLM generation and citation benchmarking without rerunning retrieval.
"""

import json
import time
from pathlib import Path
from code_diver.inspection.file_outline_service import FileOutlineService
from code_diver.inspection.read_excerpt_service import ReadExcerptService
from benchmark_closed_loop_stages import NativeSearchServer, load_dataset, REPO_ROOT

CASES_FILE = Path("datasets/intellij_eval_1000.answer_sets.jsonl")
OUT_CACHE = Path("artifacts/research/precomputed_agent_contexts_100.json")

def main():
    cases = load_dataset(CASES_FILE, max_cases=100)
    print(f"Loaded {len(cases)} cases.")
    server = NativeSearchServer(preset="selective-strict", candidate_limit=24)
    outline_service = FileOutlineService(REPO_ROOT, max_file_bytes=2_000_000)
    read_service = ReadExcerptService(REPO_ROOT, max_file_bytes=2_000_000)

    cached_data = []

    try:
        for idx, case in enumerate(cases):
            q = case["query"]
            expected = case.get("expected", [])
            res = server.query(q, limit=10)
            results = res.get("results", [])
            retrieved_paths = [r["path"] for r in results]
            top_files = retrieved_paths[:3]

            context_snippets = []
            for path in top_files:
                try:
                    outline = outline_service.structured(path)
                    symbols = [s.get("name") for s in outline.get("symbols", [])[:15]]
                except Exception:
                    symbols = []

                try:
                    excerpt = read_service.structured(path, start_line=1, lines=120)
                    code_text = excerpt.get("content") or "\n".join(
                        f"{line['line']:>5} | {line['text']}"
                        for line in excerpt.get("lines", [])
                    )
                except Exception:
                    code_text = ""

                snippet = f"=== File: {path} ===\nKey symbols: {', '.join(symbols)}\nExcerpt:\n{code_text}\n"
                context_snippets.append({"path": path, "snippet": snippet, "symbols": symbols})

            full_context_text = "\n\n".join(s["snippet"] for s in context_snippets)

            prompt = f"""Answer the developer's question using ONLY the provided code context.
Explain where and how this behavior is implemented, citing exact relative file paths and line number ranges.

Requirements:
- Ground claims in the provided excerpts.
- Return JSON strictly matching this schema:
{{
  "answer": "string explanation",
  "citations": [
    {{"path": "relative/path/to/File.java", "lines": "start-end", "reason": "short explanation"}}
  ]
}}

Question:
{q}

Provided Code Context:
{full_context_text}
"""
            cached_data.append({
                "case_id": case.get("id", f"case_{idx}"),
                "query": q,
                "expected": expected,
                "retrieved_files": retrieved_paths,
                "top_files": top_files,
                "prompt": prompt,
                "context_files": top_files,
            })
            if (idx + 1) % 20 == 0:
                print(f"[{idx+1}/100] cached context assembled")
    finally:
        server.close()

    OUT_CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CACHE, "w", encoding="utf-8") as f:
        json.dump(cached_data, f, indent=2)
    print(f"Successfully saved {len(cached_data)} cached contexts to {OUT_CACHE}")

if __name__ == "__main__":
    main()
