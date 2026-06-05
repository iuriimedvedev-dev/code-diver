# Final Report - 2026-06-03

This is the compact final report for the current Code Diver research slice.

Current state snapshot: see `docs/current-research-state-2026-06-04.md`.

## What Problems We Solved

We started with a broad code RAG sandbox and narrowed it into a reproducible code-search system:

- CLI reduced toward the required public surface: `index`, `search`, `evaluate`.
- Research commands remain available through `--help-all`, but are not the first thing a reviewer sees.
- Search output already has readable Rich rendering; `evaluate` now also has a readable Rich summary and stable JSON.
- `evaluate --benchmark ...` now supports first-class benchmark profiles.
- Public benchmark assets can be prepared automatically, but the CLI asks before downloading unless `--yes` is passed.
- The default no-config repository path now applies a built-in H5 profile instead of requiring a hand-written YAML.

## Hypotheses We Tested And Rejected

| Hypothesis | Result | Decision |
| --- | --- | --- |
| Full agentic search for every query | Worse than deterministic H3 on valid 100-case calibration; more model calls, more cost, more latency. | Not default. Keep as research/hard-case path only. |
| Ephemeral deep vector index over candidate files | Branch B was consistently worse than structured grep/read/tool probing in the saved matrix. | Rejected as default. Useful only if later evidence changes. |
| Gemini 3.5 Flash everywhere | Best quality ceiling, but too expensive for repeated 1000-case sweeps. | Oracle only, not routine. |
| Local Qwen3.5 4B as agent/reranker | Usable but too slow in the current loop: 100-case bounded run mean was 44.57s/query. | Not interactive default. |
| `protogen` as public benchmark | Not acceptable because reviewers will only have this repository. | Removed from public benchmark path. |

## Why H5 Wins As The Default

H5 is Pure H3 candidate generation plus an explicit LLM top-10 ranking layer. The persistent index stays compact and file-first:

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

Best historical oracle result:

| Setup | Dataset | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | MRR@10 | nDCG@10 | Mean ms | Cost | Degraded |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H3 manifest + Gemini 3.5 Flash | `datasets/intellij_eval_1000.answer_sets.jsonl` | 1000 | 0.871 | 0.903 | 0.943 | 0.976 | 0.964 | 0.419 | 0.898 | 0.908 | 6542 | $34.94 | 0 |

This proved the `Hit@10 >= 0.95` goal was reachable on the IntelliJ internal eval. The cost means Gemini 3.5 Flash remains an oracle, not the default loop. The current public-slice winner is now H5 with Gemini 3.1 Flash Lite over the Qwen H3 index.

## Public Benchmark

The public benchmark path is now a local positive-slice of **MTEB CodeSearchNetRetrieval Python**.

Important scope note: this is not an official full-corpus MTEB score. The current adapter materializes a reproducible local slice of positive qrels as synthetic files so we can compare our pipeline quickly and repeatably.

Command:

```bash
uv run code-diver \
  --config configs/benchmarks/codesearchnet-mteb-python-h5-qwen-quality.yml \
  evaluate \
  --benchmark codesearchnet-mteb-python-1000 \
  --limit 10 \
  --json \
  --yes \
  --reindex
```

Without `--yes`, the CLI asks before downloading missing assets.

Current quality slice, 1000 cases:

| Setup | Index | Ranker | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | MRR@10 | nDCG@10 | Mean ms/query | Status |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Pure H3 quality | Qwen3-Embedding-0.6B file metadata | none | 0.823 | 0.919 | 0.944 | 0.961 | 0.961 | 0.177 | 0.875 | 0.900 | 555 | valid |
| H5 quality | Qwen3-Embedding-0.6B file metadata | Gemini 3.1 Flash Lite top-10 | 0.904 | 0.965 | 0.977 | 0.982 | 0.982 | 0.182 | 0.933 | 0.948 | 3020 | valid |
| H5 local | Qwen3-Embedding-0.6B file metadata | Qwen3.5 4B compact top-10 | 0.842 | 0.936 | 0.953 | 0.967 | 0.967 | 0.176 | 0.890 | 0.913 | 7708 | valid |

This is the first public-slice result that should be treated as a quality signal. It uses local Qwen embeddings and file-level metadata indexing; H5 adds an LLM ranker after deterministic H3 candidate generation. All three valid 1000-case quality runs exceed the `Hit@10 >= 0.95` target.

SOTA status: this is not an official SOTA claim. The runner uses a local positive-slice of CodeSearchNet/MTEB, not the full official corpus and official scorer. Treat these numbers as our internal architecture comparison until a full-corpus or large-negative public profile is run.

Current winners:

- Best quality: H5 Qwen index + Gemini 3.1 Flash Lite (`Hit@1 0.904`, `Hit@10 0.982`, `nDCG@10 0.948`).
- Fastest and cheapest wall-clock/API path: Pure H3 Qwen index (`555ms/query`, no LLM API call).
- No-API LLM ranker: H5 Qwen index + compact local Qwen3.5 4B (`Hit@10 0.967`, but `7708ms/query`).
- Quality-focused default: H5 Qwen index + Gemini Flash Lite. It costs latency and API tokens, but gives the best top-ordering.

Additional public CodeSearchNet comparison is in `docs/codesearchnet-market-comparison-2026-06-03.md`.

Discarded hash harness:

| Setup | Hit@1 | Hit@3 | Hit@5 | Hit@10 | nDCG@10 | Mean ms/query | Status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Vector chunks | 0.164 | 0.300 | 0.364 | 0.476 | 0.304 | 86 | Reproducibility harness only. |
| H2 line+symbol hybrid | 0.295 | 0.510 | 0.595 | 0.708 | 0.493 | 195 | Reproducibility harness only; unstable across repeated runs. |
| Pure H3 hash | 0.320 | 0.607 | 0.681 | 0.775 | 0.552 | 316 | Reproducibility harness only. |

The hash rows are useful only as a controlled proof that real semantic embeddings are necessary. They are removed from quality conclusions.

Market comparison: public MTEB `CodeSearchNetRetrieval` Python rows for strong embedding models are around `0.94-0.967` official score, with `voyage-code-3`, `Qwen3-Embedding-8B`, `gemini-embedding-001`, `embeddinggemma-300m`, and `Qwen3-Embedding-4B` all strong candidates. Our local positive-slice H5 quality run is now in the right range for Hit@10, but it is not directly comparable to official full-corpus MTEB.

Evaluation caveat: `h2_line_symbol_hybrid` produced different results across deterministic no-key runs (`Hit@10` ranged from `0.622` to `0.708`, verify single-run `0.675`). Treat that as an eval/retrieval determinism bug, likely unstable candidate ordering or tie-breaking in hybrid ranking. Fix it before using repeated-run variance as a quality claim.

Claude audit status: attempted with Claude Code Opus 4.8, but the CLI returned `Not logged in · Please run /login`. See `docs/claude-audit-pure-h3-eval-2026-06-03.md`; no Claude findings were produced.

## Current Product Defaults

Without a config file, Code Diver now applies built-in H6.1 indexing/search defaults:

```bash
uv run code-diver index /path/to/repo
uv run code-diver search "where is authentication handled"
uv run code-diver evaluate --benchmark codesearchnet-mteb-python-1000 --yes --reindex
```

The no-config H6.1 defaults:

- index file manifests and summaries;
- disable broad line chunking;
- use calibrated hybrid candidate generation;
- use BM25, vector, path, symbol, and file-vote signals;
- route weights by query shape;
- run Gemini 3.1 Flash Lite top-10 LLM reranking for best measured quality.

As of 2026-06-05, `codesearchnet-mteb-python-1000` points at the
EmbeddingGemma-backed H6.1 quality profile with Gemini 3.1 Flash Lite rerank.
The old hash profile is exposed only as
`codesearchnet-mteb-python-hash-smoke` and is not used for quality conclusions.

## Remaining Hard Problems

- Add fail-fast gates for auth/model failures and high degraded-case rates.
- Run the Qwen quality profile on all 1000 public-slice cases.
- Compare the top local and API rankers over the same Qwen quality index.
- Add full run manifests: git SHA, dataset hash, config hash, model/provider versions, index hash, and command.
- Keep agentic search as a hard-case escalation path, not the default path.
