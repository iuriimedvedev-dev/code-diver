# CodeSearchNet Agentic Model Eval - 2026-06-04

This report records the public MTEB CodeSearchNetRetrieval Python checks after adding bounded H3 Agentic behavior.

The short version:

```text
Agents improved top-rank ordering, especially Hit@1.
Agents did not improve recall/Hit@10 on the public 100-case slice.
Pure H3 is still the default, but its public config is not a real quality ceiling because it uses hash embeddings and file-level chunks.
Gemma 4 12B Q4_K_M runs on Apple Silicon through llama.cpp, but the current OpenAI-compatible chat protocol is not usable yet.
```

## Setup

Public benchmark:

```text
mteb/CodeSearchNetRetrieval, Python subset
.code-diver/benchmarks/mteb-codesearchnet-python/codesearchnet_python_1000.jsonl
```

Temporary slices:

```text
.code-diver/tmp/codesearchnet_python_10.jsonl
.code-diver/tmp/codesearchnet_python_100.jsonl
```

Configs:

```text
configs/codesearchnet-mteb-python-pure-h3.yml
configs/codesearchnet-mteb-python-h3-agentic.yml
```

The public agentic config uses the same existing public Pure H3 JSON index and changes only the search mode/model loop. It is therefore a post-retrieval/tool orchestration comparison, not a new embedding benchmark.

## Runtime Changes

Two changes were made before the public rerun:

- H3 Agentic now has a runtime early-stop after a successful `code_diver_rerank`, instead of allowing more broad grep/read/search rounds.
- `openai_compatible` generation now supports `response_format: false`, needed for llama.cpp/Gemma experiments where forced `json_object` caused empty `{}` responses.

The prompt still allows the first candidate pass to fan out into 2-4 parallel `code_diver_h3_search` calls with different LLM-chosen queries. The new guard only stops the loop after a plausible rerank.

## Public Metrics

| Setup | Cases | Valid | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | nDCG@10 | MAP@10 | Mean ms | P95 ms | Cost/usage |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Pure H3 public | 10 | yes | 0.20 | 0.70 | 0.70 | 0.80 | 0.80 | 0.130 | 0.525 | 0.433 | 353 | 1,119 | no LLM |
| Gemini Lite H3 Agentic | 10 | yes | 0.50 | 0.50 | 0.80 | 0.80 | 0.80 | 0.097 | 0.616 | 0.560 | 9,435 | 12,175 | $0.074 |
| Qwen3.5 4B H3 Agentic | 10 | yes | 0.70 | 0.70 | 0.80 | 0.80 | 0.80 | 0.080 | 0.743 | 0.725 | 30,897 | 48,235 | local |
| Gemma 4 E4B H3 Agentic | 10 | yes | 0.40 | 0.60 | 0.70 | 0.70 | 0.70 | 0.070 | 0.552 | 0.503 | 31,418 | 42,364 | local |
| Gemma 4 12B Q4_K_M H3 Agentic | 10 | no | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.000 | 0.000 | 0.000 | 5,956 | 11,779 | invalid protocol |
| Pure H3 public | 100 | yes | 0.31 | 0.62 | 0.71 | 0.76 | 0.76 | 0.125 | 0.548 | 0.478 | 282 | 296 | no LLM |
| Gemini Lite H3 Agentic | 100 | yes | 0.58 | 0.64 | 0.65 | 0.65 | 0.65 | 0.120 | 0.619 | 0.609 | 10,633 | 14,590 | $0.808 |

The 10-case rows are smoke tests only. The 100-case rows are still noisy, but the direction is clear enough to diagnose the failure mode.

## Did Agents Search Better?

Not overall.

Agents were better at **top-rank ordering**:

- On 100 public cases, Gemini Lite Agentic improved Hit@1 from `0.31` to `0.58`.
- MAP improved from `0.478` to `0.609`.
- nDCG improved from `0.548` to `0.619`.

Agents were worse at **recall/Hit@10**:

- Hit@10 dropped from `0.76` to `0.65`.
- Recall@10 dropped from `0.76` to `0.65`.

So the agent is acting like an aggressive reranker: it moves a likely answer to the top when the answer is already in the candidate pool, but it also discards relevant candidates from the tail. That is useful for interactive "give me the best answer" UX, but bad for our stated `Hit@10 0.95` goal.

## Why Old Evals Looked Much Better

The old high numbers and the public numbers are not measuring the same thing.

The strongest saved IntelliJ result used H3 manifest plus Gemini 3.5 Flash and reached Hit@10 `0.976`, but that setup had a much stronger reranker, expensive API inference, IntelliJ-specific structural queries, and answer-set labels that often reward file/path/symbol retrieval.

The public CodeSearchNet run is different:

- The public Pure H3 config uses `embedding.provider: hash`, not Qwen/Gemini semantic embeddings.
- The index is file-level: `file_summary_chunks: true`, `file_manifest_chunks: true`, `line_chunks: false`, `symbol_chunks: false`.
- CodeSearchNet is function-level/docstring retrieval, so file-level manifests dilute the target function.
- Path/symbol weights help IntelliJ navigation but are weak for natural-language function descriptions.
- 10-case smoke metrics have enormous confidence intervals. Pure H3 10-case Hit@10 `0.80` had CI roughly `[0.49, 0.94]`; on 100 cases it settled at `0.76` with CI roughly `[0.67, 0.83]`.

Gemini 3.5 Flash independently reached the same diagnosis in `.code-diver/reports/h3-agentic-2026-06-04/gemini-35-pure-h3-audit.json`: the public profile is hash/file-level and therefore not a semantic quality ceiling.

## Gemma 4 12B Result

Model:

```text
unsloth/gemma-4-12b-it-GGUF
gemma-4-12b-it-Q4_K_M.gguf
size: 7.1GB
runtime: llama.cpp / llama-server on Apple M3 Max Metal
```

Download succeeded, but the first `huggingface-cli` process hung after the file reached the full size. Re-running the same download with resume completed the final move.

The model loads and is fast enough to test:

- prompt eval: hundreds of tokens/sec in server logs;
- decode: roughly `40 tok/s`;
- memory: about 7-8GB resident for the server process.

But the current OpenAI-compatible chat path is invalid:

- with `response_format: json_object`, llama.cpp/Gemma returned `{}` repeatedly;
- with `response_format: false`, llama.cpp returned empty content or only hidden channel markers;
- `--reasoning off`, `--reasoning-budget 0`, `--reasoning-format none`, `--chat-template gemma`, and `--skip-chat-parsing` did not produce valid JSON content in microtests.

Conclusion: Gemma 4 12B Q4_K_M is **not rejected as a model**, but the llama.cpp chat-template/protocol is not ready for our JSON tool loop. Do not include its zero scores in quality comparisons.

## What To Fix Next

1. Build a real public quality index: Qwen3-Embedding 0.6B/4B or Gemini embeddings, not hash embeddings.
2. Add function/symbol chunks for CodeSearchNet. File-level summaries are the wrong granularity for function retrieval.
3. Preserve recall after agent rerank: append deterministic Pure H3 tail after LLM top choices instead of replacing the whole top-10.
4. Evaluate a cascade: Pure H3 first, agent only for low-confidence cases or for final top-1 presentation.
5. Fix Gemma 4 12B serving before benchmarking it: either find a working MLX quant, a llama.cpp template that returns content, or a provider adapter that uses the correct completion format.

Current production recommendation:

```text
Pure H3 remains default for recall.
Agentic H3 should be a gated top-1/rerank layer, not the default retrieval path.
```
