# Local Model Axis Experiments

Date: 2026-06-04

## Experiment Rule

Code Diver has three independent model axes:

1. Embedding model: controls H3/H5 candidate recall and initial ordering.
2. Reranker model: controls ordering of a bounded candidate list.
3. Agent model: controls query planning, tool use, verification, and answer synthesis.

Experiments must change one axis at a time. If two or three axes change together, the result is not causal enough to choose a default.

## Validity Fixes Found During This Pass

Two experiment-infrastructure issues were found while setting up the H6/model-axis matrix:

1. `scripts/benchmark_embedding_models.py` isolated Qdrant collection, graph, and trace paths per embedding model, but did not isolate the JSON `artifact` path. With `storage.provider: json`, a later model run could overwrite an earlier model's index file. This happened locally: `index-h5-qwen3-0_6b-quality.json` contained `provider=sentence_transformers`, `model=google/embeddinggemma-300m`, `dimensions=768`.
2. Existing index metadata was not checked against the active YAML config before query/eval provider creation. A stale artifact could therefore be evaluated under the wrong model label.

Both are fixed in code:

- embedding benchmark runs now suffix JSON artifacts per model;
- `make_embedding_provider` fails fast when artifact provider/model/dimensions disagree with the config.

Impact: old Qwen/H6 reports that relied on `index-pure-h3.json` or `index-h5-qwen3-0_6b-quality.json` are suspect unless they are rerun after reindexing. The EmbeddingGemma report remains valid because its artifact metadata matches its config.

The Qwen3-Reranker llama.cpp setup also needed a runtime correction. `llama-server --ctx-size 2048 --parallel 4` gives roughly `512` tokens per slot, causing CodeSearchNet docstring queries to fail at `/v1/rerank`. The valid reranker gate uses `--ctx-size 8192 --parallel 4` so each slot has enough context.

## H6.1 / H6.2 Calibration Status

H6.1 calibrated fixed hybrid weights on the 700/300 CodeSearchNet split. It improved head ranking slightly, but did not improve candidate coverage:

| Profile | file Hit@1 | file Hit@5 | file Hit@10 | file MRR@10 |
| --- | ---: | ---: | ---: | ---: |
| Manual H5 weights | 0.837 | 0.947 | 0.960 | 0.888 |
| Best calibrated weights | 0.843 | 0.953 | 0.960 | 0.893 |

H6.2 now has two MLP modes:

| Mode | Meaning | 80/20 smoke result |
| --- | --- | --- |
| `scalar` | Predict one score per candidate. | Worse than fixed weights: file Hit@10 `0.550`. |
| `weights` | Predict a dynamic vector over hybrid signals, then score by weighted sum. | Preserved file Hit@10 `0.850`, but worsened file Hit@3/5 and MRR. |

Decision: keep H6.1 as an active calibration candidate. Keep H6.2 as research only until a better listwise/pairwise loss beats H6.1 on held-out data.

## 2026-06-05 Sequential Calibration Update

The medium-grid calibration was rerun sequentially after the performance-measurement correction. No eval/index/model benchmark processes were run in parallel while measuring these rows.

Current public benchmark limit: the available `mteb/CodeSearchNetRetrieval` Python slice contains `1000` positive qrels, so the "large" calibration sample for this dataset is all 1000 cases. The split below is `800` train / `200` validation with seed `17`, grid step `medium`, and `12,500` static profiles per embedding family.

Reports:

```text
.code-diver/reports/h6-1-medium-qwen0_6b-codesearchnet-1000.json
.code-diver/reports/h6-1-medium-embeddinggemma-codesearchnet-1000.json
```

Validation results:

| Embedding | Profile | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@R | MRR@10 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Qwen3-Embedding-0.6B 4-bit | Manual H5/H3 weights | 0.745 | 0.900 | 0.920 | 0.950 | 0.950 | 0.745 | 0.825 |
| Qwen3-Embedding-0.6B 4-bit | H6.1 best static | 0.755 | 0.900 | 0.925 | 0.950 | 0.950 | 0.755 | 0.833 |
| Qwen3-Embedding-0.6B 4-bit | H6.2 dynamic-weight MLP | 0.750 | 0.890 | 0.920 | 0.960 | 0.960 | 0.750 | 0.823 |
| EmbeddingGemma-300M | Manual H5/H3 weights | 0.820 | 0.930 | 0.955 | 0.975 | 0.975 | 0.820 | 0.877 |
| EmbeddingGemma-300M | H6.1 best static | 0.830 | 0.940 | 0.965 | 0.975 | 0.975 | 0.830 | 0.889 |
| EmbeddingGemma-300M | H6.2 dynamic-weight MLP | 0.810 | 0.945 | 0.955 | 0.975 | 0.975 | 0.810 | 0.878 |

Best Qwen3-Embedding-0.6B static weights:

```yaml
vector_weight: 0.49019607843137253
lexical_weight: 0.39215686274509803
path_weight: 0.058823529411764705
symbol_weight: 0.029411764705882353
symbol_match_weight: 0.029411764705882353
graph_weight: 0.0
file_vote_weight: 0.0
```

Best EmbeddingGemma static weights:

```yaml
vector_weight: 0.6172839506172839
lexical_weight: 0.19753086419753085
path_weight: 0.07407407407407407
symbol_weight: 0.037037037037037035
symbol_match_weight: 0.037037037037037035
graph_weight: 0.037037037037037035
file_vote_weight: 0.0
```

Interpretation:

- EmbeddingGemma is the stronger embedding family under the same calibration protocol, especially for Hit@3, Hit@5, Recall@10, and MRR.
- H6.1 static calibration gives small but real head-ranking improvements. For EmbeddingGemma it adds `+0.010` Hit@3, `+0.010` Hit@5, and about `+0.011` MRR@10 over manual weights.
- H6.2 dynamic-weight MLP is still not a default. It does not clear the requested `+0.05` lift threshold. On Qwen it improves Hit@10 by `+0.010` but hurts Hit@3/MRR; on EmbeddingGemma it improves Hit@3 by `+0.015` over manual but hurts Hit@1/MRR and does not improve Hit@5/10.
- Calibration runtime was about `55.0` minutes for Qwen and `53.6` minutes for EmbeddingGemma using cached feature files. This is acceptable as a one-time offline training/calibration step, not as an interactive path.

## H6.2 On Pure H3

Report:

```text
.code-diver/reports/h6-2-mlp-weights-pure-h3-qwen-fresh-codesearchnet-1000.json
```

Feature cache:

```text
.code-diver/tmp/h6-pure-h3-qwen-fresh-codesearchnet-1000-features.json
```

Fixed variables:

| Axis | Value |
| --- | --- |
| Base config | `configs/codesearchnet-mteb-python-pure-h3.yml` |
| Embedding model | `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ` |
| Candidate generator | H3 file-metadata hybrid retrieval |
| Dataset split | 700 train / 300 validation, seed `17` |
| MLP output | dynamic vector over hybrid signals |

Validation results:

| Profile | file Hit@1 | file Hit@3 | file Hit@5 | file Hit@10 | file MRR@10 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Manual routed H3 weights | 0.757 | 0.907 | 0.930 | 0.950 | 0.833 |
| H6.2 dynamic-weight MLP | 0.757 | 0.910 | 0.930 | 0.950 | 0.835 |
| H6.1 best static/grid profile | 0.770 | 0.917 | 0.937 | 0.957 | 0.845 |

Best static/grid profile:

```yaml
vector_weight: 0.46551724137931033
lexical_weight: 0.3620689655172413
path_weight: 0.06896551724137931
symbol_weight: 0.034482758620689655
symbol_match_weight: 0.034482758620689655
graph_weight: 0.0
file_vote_weight: 0.034482758620689655
```

Interpretation:

- The earlier Qwen H6.2 table was invalid because stale JSON artifacts were found. This fresh run used a rebuilt Qwen3-Embedding-0.6B index.
- H6.2 does not pass the requested `+0.05` threshold: file Hit@10 is unchanged at `0.950`, and file MRR@10 improves only `+0.0016`.
- H6.1 static/grid calibration is still stronger, but the gain is small: `+0.0067` file Hit@10 and `+0.0116` file MRR@10 over manual routed H3.
- Next H6.2 step should be a listwise or pairwise ranking loss over the cached per-query candidates, not another candidate-level binary classifier.

Decision: reject the current H6.2 binary-loss dynamic-weight MLP as a default. It does not clear the `+0.05` threshold under a valid same-index comparison. Use H6.1 static/grid only as a small calibrated improvement; the bigger lever remains embedding model quality.

## Embedding Axis Under H6

The next run changed only the embedding model and reran the same H3/H6 calibration protocol.

EmbeddingGemma report:

```text
.code-diver/reports/h6-2-mlp-weights-embeddinggemma-codesearchnet-1000.json
```

EmbeddingGemma feature cache:

```text
.code-diver/tmp/h6-embeddinggemma-codesearchnet-1000-features.json
```

Validation comparison:

| Embedding | Scorer | file Hit@1 | file Hit@3 | file Hit@5 | file Hit@10 | file MRR@10 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Qwen3-Embedding-0.6B 4-bit | Manual routed H3 | 0.757 | 0.907 | 0.930 | 0.950 | 0.833 |
| Qwen3-Embedding-0.6B 4-bit | H6.2 dynamic-weight MLP | 0.757 | 0.910 | 0.930 | 0.950 | 0.835 |
| Qwen3-Embedding-0.6B 4-bit | H6.1 static/grid | 0.770 | 0.917 | 0.937 | 0.957 | 0.845 |
| EmbeddingGemma-300M | Manual routed H3 | 0.853 | 0.947 | 0.963 | 0.983 | 0.902 |
| EmbeddingGemma-300M | H6.2 dynamic-weight MLP | 0.843 | 0.937 | 0.957 | 0.980 | 0.894 |
| EmbeddingGemma-300M | H6.1 static/grid | 0.863 | 0.953 | 0.973 | 0.983 | 0.911 |

Best EmbeddingGemma H6.1 weights:

```yaml
vector_weight: 0.5625
lexical_weight: 0.1875
path_weight: 0.08333333333333334
symbol_weight: 0.04166666666666667
symbol_match_weight: 0.04166666666666667
graph_weight: 0.08333333333333334
file_vote_weight: 0.0
```

Interpretation:

- Embedding model is still a bigger factor than H6.2 on this benchmark.
- EmbeddingGemma-300M with manual routed H3 still beats Qwen0.6B with H6.1 static/grid.
- H6.2 does not clear the improvement threshold for either Qwen0.6B or EmbeddingGemma under valid same-index runs.
- The current best candidate generator is EmbeddingGemma-300M + H6.1 static/grid weights.
- H6.2 should be tested next with a pairwise/listwise ranking loss, but the current binary-loss MLP is not the default.

## Embedding Axis: 100-Case Smoke

Suite:

```bash
uv run --group runtime-sentence-transformers python scripts/benchmark_embedding_models.py \
  --suite configs/codesearchnet-local-embedding-axis-100.yml
```

Report:

```text
.code-diver/reports/codesearchnet-local-embedding-axis-100.json
```

Fixed variables:

| Axis | Value |
| --- | --- |
| Search/index shape | H5 file metadata: `file_summary` + `file_manifest`, no code-body vectors |
| Search strategy | deterministic `hybrid`, no LLM reranker |
| Dataset | `.code-diver/tmp/codesearchnet_python_100.jsonl` |
| Hybrid weights | H5 manual weights |

Changed variable: embedding model.

| Embedding model | Provider | Index seconds | file Hit@1 | file Hit@3 | file Hit@5 | file Hit@10 | file MRR@10 | nDCG@10 | mean search ms | semantic file Hit@1 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ` | `openai_compatible` | 44.2 | 0.750 | 0.930 | 0.940 | 0.950 | 0.843 | 0.870 | 557.9 | 0.500 |
| `google/embeddinggemma-300m` | `sentence_transformers` | 56.5 | 0.810 | 0.930 | 0.940 | 0.950 | 0.873 | 0.892 | 853.0 | 0.643 |

Interpretation:

- EmbeddingGemma is a real candidate. It improved head ranking and semantic-query head accuracy on this split.
- Hit@10 tied at `0.950`, so this smoke does not prove better candidate coverage.
- The confidence intervals are wide on 100 cases. This is a promotion signal to 1,000 cases, not a final winner.
- The current `sentence_transformers` provider is in-process and slower for query encoding than the already-hot Qwen embedding server. If EmbeddingGemma wins quality on 1,000 cases, the next runtime task is to keep it hot behind a server or persistent worker.

## Embedding Axis: 1000-Case Sequential Comparison

Suite:

```bash
uv run --group runtime-sentence-transformers python scripts/benchmark_embedding_models.py \
  --suite configs/codesearchnet-local-embedding-axis-1000.yml
```

Report:

```text
.code-diver/reports/codesearchnet-local-embedding-axis-1000.json
```

Fixed variables:

| Axis | Value |
| --- | --- |
| Search/index shape | H5 file metadata: `file_summary` + `file_manifest`, no code-body vectors |
| Search strategy | deterministic `hybrid`, no LLM reranker |
| Dataset | `.code-diver/benchmarks/mteb-codesearchnet-python/codesearchnet_python_1000.jsonl` |
| Hybrid weights | H5 manual weights |
| Execution | sequential model runs; no parallel benchmark processes |
| Retrieval unit | files; each benchmark case has one expected file |

Changed variable: embedding model.

| Embedding model | Provider/runtime | Index seconds | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | Precision@R | MRR@10 | nDCG@10 | Mean search ms | p95 ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ` | local OpenAI-compatible MLX/vLLM endpoint | 42.6 | 0.822 | 0.928 | 0.950 | 0.960 | 0.960 | 0.176 | 0.822 | 0.878 | 0.898 | 557 | 597 |
| `google/embeddinggemma-300m` | local `sentence_transformers` in-process | 61.1 | 0.848 | 0.947 | 0.964 | 0.975 | 0.975 | 0.173 | 0.848 | 0.899 | 0.918 | 787 | 874 |

EmbeddingGemma delta vs Qwen3-Embedding-0.6B:

| Metric | Delta |
| --- | ---: |
| Hit@1 | `+0.026` |
| Hit@3 | `+0.019` |
| Hit@5 | `+0.014` |
| Hit@10 / Recall@10 | `+0.015` |
| MRR@10 | `+0.021` |
| nDCG@10 | `+0.020` |
| Precision@10 | `-0.003` |
| Index build latency | `+18.5s` slower |
| Mean search latency | `+230.7ms` slower |
| p95 search latency | `+277.1ms` slower |

Interpretation:

- EmbeddingGemma is the better quality embedding model on the public 1000-case slice with an identical H5 file-metadata setup.
- Qwen3-Embedding-0.6B remains the lower-latency local embedding baseline.
- Since CodeSearchNet has one expected file per query in this slice, file Recall@3/5 equals Hit@3/5. For multi-file repo-local tasks, precision/recall must be read from the multi-answer datasets rather than this benchmark alone.
- The weak `Precision@10` values are expected for a single-positive benchmark: returning ten files gives at most `0.1` exact precision before credit from duplicate/chunk-level matches. For product UX we should optimize `Hit@3/5`, `Recall@5/10`, and `Precision@R` more than raw `Precision@10`.
- The current quality-first default should move toward EmbeddingGemma + calibrated H6.1 weights. The current latency-first local default can remain Qwen3-Embedding-0.6B until EmbeddingGemma is served through a hot embedding worker.

## Next Matrix

Embedding axis:

| Candidate | Status |
| --- | --- |
| Qwen3-Embedding-0.6B 4-bit | baseline, integrated |
| EmbeddingGemma-300M | integrated through `sentence_transformers`, promote to 1,000-case run |
| Qwen3-Embedding-4B | pending runtime/download validation |

Reranker axis:

| Candidate | Status |
| --- | --- |
| Gemini 3.1 Flash Lite | API quality/cost baseline |
| Qwen3-Reranker-0.6B cross-encoder | valid 100-case gate complete; improves top-10 recall but hurts head precision/latency |
| Qwen3-Reranker-4B cross-encoder | pending model/runtime |
| Qwen3.5 4B listwise | local fallback, slower in prior runs |
| Gemma E2B/E4B listwise | configs exist, needs same 100-case reranker-axis run |

Agent axis:

| Candidate | Status |
| --- | --- |
| Gemini 3.1 Flash Lite | API control |
| Qwen3.5 4B | local agent candidate |
| Gemma E2B/E4B | local agent candidate |

The next valid experiments should hold the embedding axis fixed and compare rerankers, then hold embedding+reranker fixed and compare agent models.

## Agent Axis Runtime Preparation

Gemma 4 12B IT was downloaded as a local GGUF candidate:

```text
.code-diver/models/gemma-4-12b-it-GGUF/gemma-4-12b-it-Q4_K_M.gguf
```

Source repo:

```text
unsloth/gemma-4-12b-it-GGUF
```

Runtime smoke:

```bash
llama-server \
  -m .code-diver/models/gemma-4-12b-it-GGUF/gemma-4-12b-it-Q4_K_M.gguf \
  --host 127.0.0.1 \
  --port 8014 \
  -c 8192 \
  -ngl all \
  --jinja
```

Observed smoke result on MacBook M3 Max:

| Check | Result |
| --- | --- |
| Server startup | ok |
| Metal offload | ok, Apple M3 Max visible |
| OpenAI-compatible `/v1/chat/completions` | ok |
| Visible JSON response | ok with `max_tokens=160` |
| Generation speed in smoke | about `40 tok/s` |
| Note | Response includes `reasoning_content`; parsers must use visible `message.content` for final JSON. |

Decision: Gemma 4 12B Q4_K_M is technically ready for agent-axis smoke. It should be compared against Qwen3.5 4B and Gemma E4B with the same fixed candidate generator and the same tool budget.

## Agent Axis: H6.1 Candidate Tool + Gemini Lite Rerank

Fixed variables:

| Axis | Value |
| --- | --- |
| Dataset | CodeSearchNet/MTEB Python local positive slice |
| Candidate generator | H6.1 EmbeddingGemma file-metadata hybrid (`file_summary` + `file_manifest`) |
| Reranker tool | Gemini 3.1 Flash Lite through Gemini API key |
| Toolset | `code_diver_h3_search`, outline/symbol/rg/grep/read, `code_diver_rerank` |
| Changed variable | Agent/planner model only |

Valid reports:

```text
.code-diver/reports/codesearchnet-agent-axis-gemini-lite-api-25.json
.code-diver/reports/codesearchnet-agent-axis-qwen35-4b-api-rerank-10.json
.code-diver/reports/codesearchnet-agent-axis-gemma4-e4b-api-rerank-10.json
.code-diver/reports/codesearchnet-agent-axis-gemma4-e2b-api-rerank-10.json
```

Results:

| Agent model | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 | nDCG@10 | Precision@10 | Mean ms | p95 ms | Cost estimator | Errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Gemini 3.1 Flash Lite | 25 | 0.760 | 0.920 | 0.920 | 0.920 | 0.833 | 0.856 | 0.232 | 11,320 | 20,022 | $0.206 | 0 |
| Qwen3.5 4B OptiQ 4-bit | 10 | 0.800 | 1.000 | 1.000 | 1.000 | 0.883 | 0.913 | 0.100 | 37,020 | 47,739 | $0.468 estimator | 0 |
| Gemma 4 E2B 4-bit | 10 | 0.700 | 0.900 | 0.900 | 0.900 | 0.783 | 0.813 | 0.150 | 18,001 | 25,362 | $0.582 estimator | 0 |
| Gemma 4 E4B OptiQ 4-bit | 10 | 0.800 | 0.900 | 0.900 | 0.900 | 0.833 | 0.850 | 0.450 | 56,573 | 77,396 | $0.686 estimator | 0 |
| Gemma 4 12B IT Q4_K_M | 0 completed | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | runtime failure |

Interpretation:

- H6.2 is not the baseline for this axis. The agent-axis runs are built on the better H6.1 EmbeddingGemma candidate generator.
- Qwen3.5 4B produced the best 10-case quality row, but the sample is too small and the confidence interval is wide. It is a promotion candidate, not a winner.
- Gemini Lite remains the practical interactive planner because it is 3-5x faster than the local planners in this setup.
- Gemma E2B is the first local Gemma planner worth keeping in the matrix: it is much faster than E4B and preserved Hit@3/5/10 at `0.900` on the same 10-case gate. Its Hit@1/MRR are weaker, so it needs a 100-case run before promotion.
- Gemma E4B follows the protocol after increasing `max_tokens` and adding a no-Markdown-fence prompt guard, but its latency is too high for the default planner role.
- Gemma 4 12B started and generated valid tool calls, but with llama.cpp loaded it blocked the local retrieval path after the first H3 tool call for more than 4 minutes. Treat this as runtime-not-viable until the planner and embedding/search runtimes are isolated.

Invalid or partial reports retained only for debugging:

| Report | Why invalid |
| --- | --- |
| `.code-diver/reports/codesearchnet-agent-axis-gemini-lite-100.INVALID-vertex-auth.json` | Vertex ADC expired mid-run; later cases became authentication misses. |
| `.code-diver/reports/codesearchnet-agent-axis-gemini-lite-api-25.INVALID-api-version.json` | Gemini API was run with Vertex-oriented `api_version: v1`; all cases failed with generation-config schema errors. |
| `.code-diver/reports/codesearchnet-agent-axis-qwen35-4b-partial.json` | Early 6-case latency smoke before switching rerank transport from Vertex to Gemini API. |
| `.code-diver/reports/codesearchnet-agent-axis-gemma4-12b-api-rerank-3.RUNTIME-FAIL.json` | 12B runtime stalled before completing a case. |

Decision:

- Do not adopt H6.2 as the default; it missed the requested `+0.05` quality threshold.
- Use H6.1 static/grid weights over EmbeddingGemma as the current best candidate-generator baseline.
- Promote Qwen3.5 4B and Gemini Lite to a larger same-cases agent-axis comparison only after adding stricter wall-clock/tool-call caps.
- Do not promote Gemma 12B on the current Mac runtime. Re-test only with runtime isolation or a separate machine/GPU.

## Reranker Axis: Qwen3-Reranker 0.6B Cross-Encoder Gate

Report:

```text
.code-diver/reports/codesearchnet-h6-embeddinggemma-reranker-100.json
```

Trace:

```text
.code-diver/traces/codesearchnet-h6-embeddinggemma-reranker-100.jsonl
```

Fixed variables:

| Axis | Value |
| --- | --- |
| Embedding model | `google/embeddinggemma-300m` |
| Candidate generator | H6.1 calibrated EmbeddingGemma file-summary/file-manifest hybrid |
| Dataset | `.code-diver/tmp/codesearchnet_python_100.jsonl` |
| Candidate limit | 30 |
| Reranker runtime | llama.cpp `/v1/rerank`, `Qwen3-Reranker-0.6B-Q4_K_M.gguf` |
| Validity gate | `cross_encoder_rerank_response=100`, `cross_encoder_rerank_error=0` |

Results:

| Strategy | file Hit@1 | Hit@3 | Hit@5 | Hit@10 | file MRR@10 | nDCG@10 | precision@R | mean ms | p95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H6.1 static EmbeddingGemma hybrid | 0.810 | 0.920 | 0.960 | 0.970 | 0.876 | 0.899 | 0.810 | 867 | 860 |
| + Qwen3-Reranker 0.6B | 0.780 | 0.950 | 0.990 | 0.990 | 0.864 | 0.896 | 0.780 | 2881 | 5063 |

Interpretation:

- The dedicated local reranker is not a blanket default for this file-level task: it improves candidate recall in the top 3/5/10, but demotes too many already-correct first results.
- Latency is about 3.3x worse on the 100-case gate.
- This model is still useful as a cascade candidate when the goal is top-5/top-10 coverage and the deterministic top result has low confidence.
- Next reranker tests should include Qwen3-Reranker 4B and a confidence gate that preserves high-margin deterministic top-1 hits.

## Reranker Axis: Gemma E4B 100-Case Smoke

Suite:

```bash
uv run python scripts/benchmark_generation_models.py \
  --suite configs/codesearchnet-local-gemma-ranker-slice.yml \
  --only gemma4_e4b_it_optiq_4bit
```

Report:

```text
.code-diver/reports/codesearchnet-local-gemma-ranker-slice.json
```

Fixed variables:

| Axis | Value |
| --- | --- |
| Embedding model | `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ` |
| Candidate generator | H5/H3 Qwen file-metadata index |
| Dataset | `.code-diver/tmp/codesearchnet_python_100.jsonl` |
| Rerank input | top-30 candidates, top-10 output, compact previews |

Changed variable: reranker model.

| Reranker | Runtime | file Hit@1 | file Hit@3 | file Hit@5 | file Hit@10 | file MRR@10 | mean search ms | p95 ms | calls | tokens | est. cost |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Pure H3, no rerank | Qwen embedding server only | 0.750 | 0.930 | 0.940 | 0.950 | 0.843 | 557.9 | 583.5 | 0 | 0 | 0 |
| Gemma 4 E4B OptiQ 4-bit listwise | `mlx_lm` | 0.560 | 0.590 | 0.590 | 0.590 | 0.573 | 8049.1 | 9332.2 | 100 | 1,050,072 | 1.616 |

Interpretation:

- This local generative Gemma E4B reranker is a clear rejection in the current H5 protocol.
- It degraded candidate coverage and ordering instead of improving them.
- It is about `14.4x` slower than Pure H3 on the same 100-case split.
- The most likely failure mode is not model startup: the server ran and returned 100 successful calls. The problem is ranking behavior/protocol fit.
- Next reranker work should prioritize dedicated cross-encoders such as Qwen3-Reranker over local generative listwise ranking.
