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
