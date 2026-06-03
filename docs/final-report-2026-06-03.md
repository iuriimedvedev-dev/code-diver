# Final Report - 2026-06-03

This is the compact final report for the current Code Diver research slice.

## What Problems We Solved

We started with a broad code RAG sandbox and narrowed it into a reproducible code-search system:

- CLI reduced toward the required public surface: `index`, `search`, `evaluate`.
- Research commands remain available through `--help-all`, but are not the first thing a reviewer sees.
- Search output already has readable Rich rendering; `evaluate` now also has a readable Rich summary and stable JSON.
- `evaluate --benchmark ...` now supports first-class benchmark profiles.
- Public benchmark assets can be prepared automatically, but the CLI asks before downloading unless `--yes` is passed.
- The default no-config repository path now applies a built-in Pure H3 profile instead of requiring a hand-written YAML.

## Hypotheses We Tested And Rejected

| Hypothesis | Result | Decision |
| --- | --- | --- |
| Full agentic search for every query | Worse than deterministic H3 on valid 100-case calibration; more model calls, more cost, more latency. | Not default. Keep as research/hard-case path only. |
| Ephemeral deep vector index over candidate files | Branch B was consistently worse than structured grep/read/tool probing in the saved matrix. | Rejected as default. Useful only if later evidence changes. |
| Gemini 3.5 Flash everywhere | Best quality ceiling, but too expensive for repeated 1000-case sweeps. | Oracle only, not routine. |
| Local Qwen3.5 4B as agent/reranker | Usable but too slow in the current loop: 100-case bounded run mean was 44.57s/query. | Not interactive default. |
| `protogen` as public benchmark | Not acceptable because reviewers will only have this repository. | Removed from public benchmark path. |

## Why Pure H3 Wins

Pure H3 is not "just vector search." It is a compact file-first hybrid retrieval setup:

1. **Index file-level artifacts**, not every tiny code chunk by default:
   - file manifest;
   - file summary;
   - bounded symbol metadata.
2. **Search with hybrid signals**:
   - dense vectors;
   - BM25/lexical matching;
   - path and symbol signals;
   - routed weighting by query shape.
3. **Keep candidate generation deterministic and cheap.**
4. **Use LLM rerank surgically**, only when a quality run explicitly asks for it.

Why it is the current best:

- It keeps the index compact.
- It avoids burying the right file among many duplicate chunks.
- It is much faster and cheaper than open-ended agent loops.
- It already reached the target quality with the saved oracle reranker run.

Best valid saved result:

| Setup | Dataset | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | MRR@10 | nDCG@10 | Mean ms | Cost | Degraded |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H3 manifest + Gemini 3.5 Flash | `datasets/intellij_eval_1000.answer_sets.jsonl` | 1000 | 0.871 | 0.903 | 0.943 | 0.976 | 0.964 | 0.419 | 0.898 | 0.908 | 6542 | $34.94 | 0 |

This proves the `Hit@10 >= 0.95` goal is reachable. The cost means Gemini 3.5 Flash remains an oracle, not the default loop.

## Public Benchmark

The public benchmark path is now **MTEB CodeSearchNetRetrieval Python 1000**.

Command:

```bash
uv run code-diver \
  --config configs/codesearchnet-mteb-python-hash.yml \
  evaluate \
  --benchmark codesearchnet-mteb-python-1000 \
  --limit 10 \
  --json \
  --yes \
  --reindex
```

Without `--yes`, the CLI asks before downloading missing assets.

Fresh local run:

| Metric | Value |
| --- | ---: |
| Cases | 1000 |
| Corpus files | 1000 |
| Local prepared assets | 13 MB |
| Indexed items | 1001 |
| Hit@1 | 0.164 |
| Hit@3 | 0.300 |
| Hit@5 | 0.364 |
| Hit@10 | 0.476 |
| Recall@10 | 0.476 |
| Precision@10 | 0.0476 |
| nDCG@10 | 0.304 |
| MAP@10 | 0.251 |
| Mean ms/query | 95.3 |
| p95 ms/query | 127.2 |
| Degraded cases | 0 |

This is a **pipeline baseline**, not the quality target. It uses deterministic hash embeddings so reviewers can download and run the benchmark without API keys or local model servers. The next quality benchmark profile should swap in the real Pure H3 embedding/rerank stack.

Additional public CodeSearchNet comparison is in `docs/codesearchnet-market-comparison-2026-06-03.md`.

Current no-key matrix snapshot:

| Setup | Hit@1 | Hit@3 | Hit@5 | Hit@10 | nDCG@10 | Mean ms/query | Status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Vector chunks | 0.164 | 0.300 | 0.364 | 0.476 | 0.304 | 86 | Stable baseline. |
| H2 line+symbol hybrid | 0.295 | 0.510 | 0.595 | 0.708 | 0.493 | 195 | Best matching pair, but later drifted. |
| Pure H3 | 0.320 | 0.607 | 0.681 | 0.775 | 0.552 | 316 | Best completed no-key quality run. |

Market comparison: public MTEB `CodeSearchNetRetrieval` Python rows for strong embedding models are around `0.94-0.967` official score, with `voyage-code-3`, `Qwen3-Embedding-8B`, `gemini-embedding-001`, `embeddinggemma-300m`, and `Qwen3-Embedding-4B` all far above our hash-only public profiles. We are not SOTA on this benchmark yet; the next valid quality run must use a real code-aware embedder.

Evaluation caveat: `h2_line_symbol_hybrid` produced different results across deterministic no-key runs (`Hit@10` ranged from `0.622` to `0.708`, verify single-run `0.675`). Treat that as an eval/retrieval determinism bug, likely unstable candidate ordering or tie-breaking in hybrid ranking. Fix it before using repeated-run variance as a quality claim.

Claude audit status: attempted with Claude Code Opus 4.8, but the CLI returned `Not logged in · Please run /login`. See `docs/claude-audit-pure-h3-eval-2026-06-03.md`; no Claude findings were produced.

## Current Product Defaults

Without a config file, Code Diver now applies built-in Pure H3 indexing/search defaults:

```bash
uv run code-diver index /path/to/repo
uv run code-diver search "where is authentication handled"
uv run code-diver evaluate --benchmark codesearchnet-mteb-python-1000 --yes --reindex
```

The no-config Pure H3 defaults:

- index file manifests and summaries;
- disable broad line chunking;
- use hybrid search;
- use BM25, vector, path, symbol, and file-vote signals;
- route weights by query shape;
- avoid default LLM reranking so a normal search does not silently spend API money.

## Remaining Hard Problems

- Add fail-fast gates for auth/model failures and high degraded-case rates.
- Add a quality benchmark profile using the real local embedding model, not hash embeddings.
- Add a cheap LLM rerank profile with Gemini 3.1 Flash Lite after fail-fast gating.
- Add full run manifests: git SHA, dataset hash, config hash, model/provider versions, index hash, and command.
- Keep agentic search as a hard-case escalation path, not the default path.
