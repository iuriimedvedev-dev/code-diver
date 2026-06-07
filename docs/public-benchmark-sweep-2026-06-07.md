# Public Benchmark Sweep - 2026-06-07

## Scope

This sweep expands the public benchmark coverage beyond the original Python-only local positive slice.

The goal is not an official leaderboard claim. The goal is to stress Code Diver on lightweight, reproducible, open datasets that a reviewer can download and rerun.

## Benchmarks Found

| Benchmark | Status | Why it matters | Current action |
| --- | --- | --- | --- |
| `mteb/CodeSearchNetRetrieval` | run | Classic text-to-code retrieval across Python, Java, JavaScript, Go, PHP, Ruby. | Prepared and ran 100-case slices for five new languages plus existing Python 1,000. |
| `mteb/SWEbenchCodeRetrieval` | run | Issue-text to source-file retrieval based on SWE-bench Verified-style software-engineering tasks. Better product fit than docstring/function retrieval. | Prepared and ran 100 qrels / 71 files smoke slice. |
| CoIR | found, not yet integrated | Broader code IR benchmark family with CodeSearchNet, CosQA, StackOverflowQA, CodeFeedback, etc. | Needs generic CoIR preparer for split names `corpus`, `queries`, qrels variants. |
| CodeXGLUE / CoSQA / WebQueryTest | found, not yet integrated | Human/web-query code search data; useful for natural developer-like queries. | Needs CodeXGLUE/CoSQA JSON adapter. |
| CoREB | found, not yet integrated | Newer reranking-oriented benchmark; likely useful for H8/H9 reranker work. | Needs adapter and license/size check. |

## What Was Actually Run

All rows below use the local deterministic H6.1 file-locator stack unless otherwise noted:

- embedding: `google/embeddinggemma-300m`
- index shape: `file_summary` + `file_manifest`
- search: calibrated hybrid retrieval, no LLM rerank
- storage: local JSON artifact

The Python Gemini Lite row is included as the current API quality reference.

| Benchmark | Cases | Files | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 | nDCG@10 | P@10 | P@R | Mean ms | Failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| CodeSearchNet Python H8 Gemini Lite | 1,000 | 1,000 | 0.911 | 0.978 | 0.988 | 0.989 | 0.944 | 0.956 | 0.155 | 0.911 | 3487.8 | 0 |
| CodeSearchNet Python H6 local | 1,000 | 1,000 | 0.856 | 0.960 | 0.982 | 0.987 | 0.909 | 0.929 | 0.152 | 0.856 | 3145.7 | 0 |
| CodeSearchNet JavaScript H6 local | 100 | 100 | 0.850 | 0.930 | 0.940 | 0.960 | 0.895 | 0.911 | 0.177 | 0.850 | 1232.4 | 0 |
| CodeSearchNet Java H6 local | 100 | 100 | 0.910 | 0.990 | 1.000 | 1.000 | 0.951 | 0.963 | 0.187 | 0.910 | 1282.3 | 0 |
| CodeSearchNet Go H6 local | 100 | 100 | 0.960 | 0.990 | 0.990 | 0.990 | 0.973 | 0.978 | 0.100 | 0.960 | 1227.8 | 0 |
| CodeSearchNet PHP H6 local | 100 | 100 | 0.730 | 0.840 | 0.860 | 0.870 | 0.785 | 0.806 | 0.087 | 0.730 | 841.0 | 0 |
| CodeSearchNet Ruby H6 local | 100 | 100 | 0.920 | 0.980 | 0.980 | 0.990 | 0.949 | 0.959 | 0.176 | 0.920 | 842.3 | 0 |
| SWEbenchCodeRetrieval H6 local | 100 | 71 | 0.610 | 0.920 | 0.960 | 0.960 | 0.752 | 0.804 | 0.185 | 0.610 | 776.1 | 0 |

## Interpretation

The deterministic local stack is stronger than expected on lightweight CodeSearchNet language slices:

- Java, Go, and Ruby are already very high on top-k candidate recall.
- JavaScript is acceptable but leaves head-ranking room.
- PHP is the weak language in this sweep.
- SWEbenchCodeRetrieval is much harder at Hit@1, but still has Hit@5/10 `0.96`, which means candidate recall is decent and reranking/context inspection should help.

The timing numbers from the multi-language rows should not be used as strict performance comparisons. These runs were launched in parallel and `sentence_transformers` loaded model weights multiple times. For reliable latency, rerun sequentially with `evaluation.workers=1`.

## Local Versus Gemini Lite

Question: did calibrated/local reranking succeed if it does not beat Gemini Lite?

Answer: partially, but not as the default.

Same-family Python results:

| Setup | Cases | Hit@1 | Hit@10 | MRR@10 | nDCG@10 | Mean ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| H6 static local | 200 | 0.800 | 0.975 | 0.870 | 0.896 | 872.3 |
| Gemma E4B local rerank after base prior | 200 | 0.810 | 0.975 | 0.876 | 0.901 | 8818.8 |
| Gemini Lite rerank, first 200 cases | 200 | 0.860 | 0.980 | 0.911 | 0.929 | not isolated |

So:

- Local Gemma E4B reranking can improve H6 static slightly.
- It is still below Gemini Lite quality on comparable first-100/first-200 slices.
- It is much slower in the current serving path.
- The best local-only value right now is H6.1 candidate generation, not generative local reranking.

The next local reranker to test seriously is a dedicated cross-encoder/reranker such as Qwen3-Reranker, not a generative instruction model.

## Why SWEbench Matters

SWEbenchCodeRetrieval is issue-text to source-file retrieval, so it resembles our product better than CodeSearchNet docstring-to-function lookup. The H6 local row has low Hit@1 (`0.610`) but high Hit@5/10 (`0.960`). That is exactly the shape where a good reranker or file-inspection agent can matter.

This becomes the better quick benchmark for H8/H9:

1. Use H6/H9 to get the right file into top 5.
2. Use local cross-encoder or Gemini Lite to rerank.
3. Use the answer/explanation pipeline to inspect the selected files.

## Repro Artifacts

Prepared datasets:

- `.code-diver/benchmarks/mteb-codesearchnet-javascript-100/codesearchnet_javascript_100.jsonl`
- `.code-diver/benchmarks/mteb-codesearchnet-java-100/codesearchnet_java_100.jsonl`
- `.code-diver/benchmarks/mteb-codesearchnet-go-100/codesearchnet_go_100.jsonl`
- `.code-diver/benchmarks/mteb-codesearchnet-php-100/codesearchnet_php_100.jsonl`
- `.code-diver/benchmarks/mteb-codesearchnet-ruby-100/codesearchnet_ruby_100.jsonl`
- `.code-diver/benchmarks/mteb-swebench-code-retrieval-100/swebench_code_retrieval_100.jsonl`

Reports:

- `.code-diver/reports/codesearchnet-javascript-100-h6-embeddinggemma.json`
- `.code-diver/reports/codesearchnet-java-100-h6-embeddinggemma.json`
- `.code-diver/reports/codesearchnet-go-100-h6-embeddinggemma.json`
- `.code-diver/reports/codesearchnet-php-100-h6-embeddinggemma.json`
- `.code-diver/reports/codesearchnet-ruby-100-h6-embeddinggemma.json`
- `.code-diver/reports/swebench-code-retrieval-100-h6-embeddinggemma.json`

Implementation note:

- `MtebCodeSearchNetPreparer` now writes language-correct file extensions (`.java`, `.js`, `.go`, `.php`, `.rb`) instead of hardcoding `.py`.

## Next

1. Add first-class benchmark profiles for the new CodeSearchNet language slices and SWEbenchCodeRetrieval.
2. Rerun the sweep sequentially for clean latency numbers.
3. Add a generic MTEB three-config preparer (`corpus`, `queries`, `default`) for SWEbenchCodeRetrieval.
4. Add CoIR and CodeXGLUE/CoSQA adapters.
5. Run H8/H9 rerank experiments on SWEbenchCodeRetrieval first, because its Hit@5/Hit@10 profile leaves meaningful rerank headroom.
