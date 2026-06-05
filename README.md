# Code Diver

`code-diver` is a local code exploration assistant and retrieval-evaluation sandbox. It indexes a repository into local artifacts, answers natural-language code-navigation queries with cited files/snippets, and runs reproducible retrieval evaluations.

## Setup

```bash
uv sync
export GEMINI_API_KEY="..."
uv run code-diver init --platform apple-metal --embedding embeddinggemma-300m --yes --start
```

The default quality profile is H6.1: local EmbeddingGemma-300M file-metadata
embeddings plus calibrated hybrid retrieval and Gemini 3.1 Flash Lite reranking.
The fast local fallback is the same H6.1 hybrid locator without LLM rerank.
For the Gemini side, provide one of:

```bash
export GEMINI_API_KEY="..."
```

or Google ADC credentials:

```bash
gcloud auth application-default login
```

Secrets can live in `.env`; the CLI loads it before creating providers. `.env` is ignored by git. Advanced research commands, visible with `--help-all`, can still integrate optional orchestration backends.

The no-config indexing path is intentionally local-first:

- indexing default: H6.1 file-first artifacts over file summaries/manifests;
- quality benchmark default: H6.1 hybrid retrieval plus Gemini 3.1 Flash Lite rerank;
- fast/local search fallback: H6.1 hybrid retrieval without LLM rerank;
- local embedding default for quality runs: EmbeddingGemma-300M through an OpenAI-compatible local server;
- no-key smoke checks are explicit and use the separate hash benchmark profile.

Configuration lives in `code-diver.yml`. For no-key smoke tests only, set:

```yaml
embedding:
  provider: hash
  dimensions: 256
```

Do not use `hash` embeddings for quality metrics; they exist only to verify
CLI/evaluation plumbing without a model server.

## Commands

```bash
uv run code-diver index /path/to/repo
uv run code-diver search "where is authentication configured?"
uv run code-diver evaluate --benchmark codesearchnet-mteb-python-1000
```

The public CLI intentionally exposes the assignment surface: `index`, `search`, and `evaluate`. Research and inspection commands are still available behind `--help-all`.

### Quickstart

```bash
uv sync
export GEMINI_API_KEY="..."
uv run code-diver init --platform apple-metal --embedding embeddinggemma-300m --yes --start
uv run code-diver index .
uv run code-diver search "how does indexing work?"
uv run code-diver evaluate --benchmark sample --json
```

`code-diver init` installs Search agent npm dependencies and configures the
embedding runtime. Use `--skip-install` only when dependencies are already present
or when you are running a docs/config dry run. For local embeddings, pick a local
profile instead, for example `uv run code-diver init --platform apple-metal --embedding embeddinggemma-300m --yes --start`.
`qwen3-0.6b` remains a fast control profile.

`index` shows a compact progress UI by default: index profile, what is embedded, file
discovery, scan, embedding batches, save, and graph build. Long operations without their own
progress bar show an animated spinner at the end of the status phrase, so provider startup,
runtime checks, graph build, and agent runs do not look frozen. Disable progress when
scripting:

```bash
uv run code-diver index . --no-progress
uv run code-diver index . --quiet
```

Qdrant indexes are namespaced by repository and embedding extractor when the default
collection base is used. A plain `index` creates a new missing repo/model collection and
refuses to overwrite an existing one. Use explicit lifecycle flags when replacing data:

```bash
uv run code-diver index ../my-repo --update-index
uv run code-diver index ../my-repo --override-repo
uv run code-diver index clear
uv run code-diver index clear --all
```

`--update-index` replaces only the current repo/model collection through the staged Qdrant
write path. `--override-repo` removes all collections for the current repository namespace
before indexing. `index clear` removes the current repository namespace without rebuilding;
`index clear --all` removes every Code Diver index collection using the default
`code_diver` prefix.

The scanner enumerates files through `rg --files --no-require-git`, so it honors
`.gitignore` for both Git repositories and unpacked source trees. The default config uses
local Qdrant at `http://localhost:6333`; `init`, `index`, `search`, and `evaluate` check
that service and start `docker compose up -d qdrant` automatically when Docker is available.
Embedded local Qdrant storage is only suitable for small smoke indexes and gets slow above
tens of thousands of points.

`search` is the code-exploration entrypoint: it launches the configured read-only Search agent, which searches, verifies with bounded reads/grep/symbol tools, and explains the code with file/line citations. It prints a preflight summary first: root, config, index store, model, tools, and missing-index guidance when needed.

For interactive exploration:

```bash
uv run code-diver search -i "how does indexing work?"
```

For raw retrieval candidates:

```bash
uv run code-diver search "how does indexing work?" -j
```

For the public benchmark slice:

```bash
uv run code-diver evaluate \
  --benchmark codesearchnet-mteb-python-1000 \
  --yes \
  --reindex
```

This benchmark profile uses the EmbeddingGemma-backed H6.1 quality config. Run
`uv run code-diver init --platform apple-metal --embedding embeddinggemma-300m --yes --start`
first for the default local embedding setup and set `GEMINI_API_KEY` or Google
ADC credentials for Gemini Lite reranking. For a no-key smoke check only, use
`--benchmark codesearchnet-mteb-python-hash-smoke`.

Without `--yes`, the CLI asks before downloading missing benchmark assets.

For a quick repository-local sanity benchmark, generate a small dataset from the
selected codebase and immediately evaluate against it:

```bash
uv run code-diver --root ../my-repo evaluate --generate-dataset --cases 50 --reindex
```

By default this writes `.code-diver/eval/local_eval.jsonl` inside the target repo.
Pass `--dataset path/to/eval.jsonl` with `--generate-dataset` to choose the output
path. Generated local cases are deterministic and useful for regression checks, but
they are not a replacement for a curated semantic benchmark because queries are
derived from file paths and symbols.

For code-explanation evaluation, use the advanced CodeXGLUE code-to-text lane:

```bash
uv run code-diver --help-all evaluate-explanations \
  --benchmark codexglue-code-to-text-python \
  --cases 50 \
  --yes \
  --judge \
  --judge-prompt prompts/code-explanation-judge.md \
  --judge-model gemini-3.1-flash-lite
```

This prepares a public Python function/docstring benchmark, generates developer-facing
code explanations, scores token/key-token/bigram overlap against the reference
docstring, and can add LLM-as-judge questionnaire scores with a weighted final
grade. The default editable judge prompt lives at
`prompts/code-explanation-judge.md`. See
[docs/code-explanation-eval-2026-06-05.md](docs/code-explanation-eval-2026-06-05.md).

For full answer-agent evaluation, use the advanced repo-level E2E lane:

```bash
uv run code-diver --root ../checked-out-repo --help-all evaluate-answers \
  --benchmark swe-qa-pro \
  --repo owner/name \
  --cases 20 \
  --yes \
  --judge \
  --judge-prompt prompts/code-answer-judge.md \
  --judge-model gemini-3.1-flash-lite
```

This measures the product path: retrieval/rerank, bounded file context reads,
final answer generation, and optional LLM-as-judge scoring against a reference
answer. The SWE-QA-Pro adapter prepares public repo-question cases, but the first
E2E runner expects `--root` to point at the matching repository checkout. See
[docs/e2e-answer-eval-2026-06-05.md](docs/e2e-answer-eval-2026-06-05.md).

## Retrieval Experiments

`code-diver.yml` controls storage and retrieval strategy:

```yaml
storage:
  provider: qdrant

search:
  strategy: hybrid_rerank # quality default: H6.1 candidates + Gemini Lite rerank

embedding:
  provider: openai_compatible
  model: google/embeddinggemma-300m
```

See [docs/assignment-plan-progress.md](docs/assignment-plan-progress.md) for the assignment plan, estimates, progress log, and deliverable map. See [docs/current-research-state-2026-06-04.md](docs/current-research-state-2026-06-04.md) for the current research conclusion, [docs/final-report-2026-06-03.md](docs/final-report-2026-06-03.md) for the compact final report, [docs/metrics.md](docs/metrics.md) for metric definitions, and [docs/Explanation.md](docs/Explanation.md) for a plain-language explanation of the retrieval strategies.
See [docs/code-embedding-model-research-2026-06-04.md](docs/code-embedding-model-research-2026-06-04.md) for the current code embedding model shortlist, including EmbeddingGemma.

## Tests

```bash
uv run pytest
uv run pytest -m unit
uv run pytest -m e2e
uv run pytest -m smoke
uv run pytest -m protogen
```

The `protogen` marker targets the optional sibling repository at `../protogen`. It is skipped when that repo is not present.

## Protogen Evaluation

`configs/protogen.yml` is a historical small-repo config for the optional sibling
`../protogen` repo. For normal no-config usage, run the default H6.1 profile directly:

```bash
uv run code-diver --root ../protogen index
uv run code-diver --root ../protogen search -i "where is the arena runner implemented?"
uv run code-diver --root ../protogen evaluate --generate-dataset --cases 50 --reindex
```

The legacy config path still works for controlled experiments:

```bash
uv run code-diver --config configs/protogen.yml index
uv run code-diver --config configs/protogen.yml search "where is the arena runner implemented?"
uv run code-diver --config configs/protogen.yml evaluate --json
uv run code-diver --config configs/protogen.yml experiment
```

Some legacy experiment configs intentionally use deterministic hash embeddings for
repeatable plumbing tests. They are not quality configs. The product quality default is
H6.1 with local EmbeddingGemma embeddings, calibrated hybrid retrieval, and Gemini Lite
reranking. The fast local fallback uses the same H6.1 index without LLM rerank.

The default indexing profile is file-first. It stores compact `file_summary` and `file_manifest` items for each source file, then returns ranked files for targeted code exploration. It does not permanently embed full source chunks by default; the agent can inspect candidate files later with grep, symbol, read, and optional localized deep-index tools.

For model-orchestrated indexing, use `indexing.mode: orchestrated`. The generation model sees repository structure, file names, aggregate stats, config constraints, and index metadata. It does not receive source code contents. Local scanners still build the final trusted index items.

```bash
export GEMINI_API_KEY="..."
uv run code-diver --config configs/protogen-ai.yml index
uv run code-diver --config configs/protogen-ai.yml experiment
```

The generic AI discovery patterns live in YAML. Add project-specific patterns in a separate config only when running a targeted experiment.

Provider selection is config-driven:

```yaml
generation:
  provider: gemini # or openai
  model: gemini-3.1-flash-lite
  timeout_ms: 30000

embedding:
  provider: openai_compatible # gemini, openai, or hash also supported
  model: mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ
  url: http://127.0.0.1:8001/v1/embeddings
  batch_size: 128
  workers: 1
  max_input_chars: 400
```

For OpenAI, set `OPENAI_API_KEY` and use `generation.provider: openai` plus `embedding.provider: openai`. Defaults are `gpt-5.1` and `text-embedding-3-large`.

Gemini Embedding 2 is not wire-compatible with `gemini-embedding-001`: existing Gemini embedding artifacts must be rebuilt after switching models.

For local embeddings on Apple Silicon, use an OpenAI-compatible embedding server backed by
vLLM-Metal. The current preferred path is vLLM pooling on
`http://127.0.0.1:8001/v1/embeddings`, with Gemini or Vertex kept for
orchestration/reranking experiments. `configs/protogen-local.yml` is kept for fully local
OpenAI-compatible experiments on `http://localhost:1234/v1`.

Gemini embeddings are not available as a local downloadable model in this project. The local embedding profiles are Qwen/MLX/vLLM-compatible models; Gemini Embedding 2 is API/Vertex only and requires `GEMINI_API_KEY` or gcloud ADC.

Run setup once before local embedding indexing. The default path is the interactive
arrow-key TUI wizard:

```bash
uv run code-diver init
```

The wizard asks for platform, embedding extractor, runtime backend, port, and install
confirmation. Use arrow keys to move, Enter to select, and Ctrl-C to cancel. In `host-uv`
mode Code Diver creates a platform-specific runtime venv with `uv`, installs the matching
dependency group, downloads the selected model on first serve, starts the embedding server
as a subprocess, and writes logs to `.code-diver/runtime/logs/embedding-server.log`.

Runtime dependency groups:

| Platform | Runtime group | Install dir |
| --- | --- | --- |
| `apple-metal` | `runtime-apple-metal` | `.code-diver/runtime/vllm-metal` |
| `nvidia-cuda`, `amd-rocm`, `cpu` | `runtime-vllm` | `.code-diver/runtime/vllm` |

For CI, containers, or scripted setup, pass explicit flags:

```bash
uv run code-diver init --platform apple-metal --embedding embeddinggemma-300m --runtime host-uv --yes --start
uv run code-diver index ../my-repo
```

For Nvidia CUDA or AMD ROCm hosts, use regular Hugging Face checkpoints through vLLM:

```bash
uv run code-diver init --platform nvidia-cuda --embedding embeddinggemma-300m-vllm --runtime host-uv --yes --start
uv run code-diver init --platform amd-rocm --embedding embeddinggemma-300m-vllm --runtime host-uv --yes --start
```

For the latest small Gemma-family embedding model, use EmbeddingGemma. It is a gated
Hugging Face model, so accept the model license and export `HF_TOKEN` before first start:

```bash
export HF_TOKEN="..."
uv run code-diver init --platform apple-metal --embedding embeddinggemma-300m --runtime host-uv --yes --start
uv run code-diver init --platform nvidia-cuda --embedding embeddinggemma-300m-vllm --runtime host-uv --yes --start
```

If you already run a compatible `/v1/embeddings` endpoint in Docker or on another host, use
`external` mode. Code Diver will not install or start a model process; later commands will
only check that the endpoint is reachable.

```bash
uv run code-diver init --embedding qwen3-0.6b --runtime external --skip-install --yes
```

After `init`, `index` uses the configured extractor automatically:

```bash
uv run code-diver index ../my-repo
```

Available built-in extractor profiles:

| Profile | Backend | Notes |
| --- | --- | --- |
| `embeddinggemma-300m` | `google/embeddinggemma-300m` via vLLM-Metal | Current quality default on Apple Silicon; gated HF license; uses code-retrieval prompts. |
| `embeddinggemma-300m-vllm` | `google/embeddinggemma-300m` via vLLM | Nvidia CUDA, AMD ROCm, or CPU profile for the quality default. |
| `qwen3-0.6b` | `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ` via vLLM-Metal | Fast local control profile on Apple Silicon. |
| `qwen3-4b` | `mlx-community/Qwen3-Embedding-4B-4bit-DWQ` via vLLM-Metal | Stronger raw candidate generator, much slower; downloads on first serve if missing. |
| `qwen3-0.6b-vllm` | `Qwen/Qwen3-Embedding-0.6B` via vLLM | Nvidia CUDA, AMD ROCm, or CPU profile. |
| `qwen3-4b-vllm` | `Qwen/Qwen3-Embedding-4B` via vLLM | Stronger CUDA/ROCm/CPU profile. |
| `gemini` | `gemini-embedding-2` API | Remote API/Vertex path; no local Gemini embedding model. |

Local embedding configs can still set `embedding.workers` for parallel embedding requests
and `embedding.max_input_chars` to fit smaller local model context windows. For small local
embedding contexts, use `batch_size: 1` and increase `workers` instead of sending large
multi-input batches.

```bash
uv run code-diver --config configs/protogen-local.yml index
uv run code-diver --config configs/protogen-local.yml experiment
```

For local reranking, use llama.cpp with a dedicated reranker model:

```bash
llama-server \
  --model .code-diver/models/rerankers/qwen3-reranker-4b/Qwen3-Reranker-4B-Q4_K_M.gguf \
  --host 127.0.0.1 \
  --port 8080 \
  --embedding \
  --reranking \
  --pooling rank
```

`experiment` runs the configured retrieval hypotheses from YAML:

```yaml
experiments:
  suite: protogen-local
  strategies:
    - vector
    - recursive
    - graph
```

`code-diver` starts the `qdrant` service automatically for the default local vector store.
Start the full local runtime stack manually only when you also want ClickHouse metrics and
Grafana dashboards:

```bash
docker compose up -d qdrant clickhouse grafana
curl -fsS http://localhost:6333/collections
curl -fsS http://localhost:18123/ping
```

If another Qdrant is already bound to `6333`, either reuse that running instance or start
this stack on alternate host ports and update `storage.qdrant.url` in YAML:

```bash
QDRANT_PORT=6335 QDRANT_GRPC_PORT=6336 docker compose up -d qdrant
```

The root `docker-compose.yml` stores service data under `.code-diver/docker/` so index size is visible with:

```bash
du -sh .code-diver/docker/*
```

Default local ports:

- Qdrant HTTP: `6333`
- Qdrant gRPC: `6334`
- ClickHouse HTTP: `18123`
- ClickHouse native: `19000`
- Grafana: `3000`

Local Metal model runtimes stay on the host, not in Docker:

- vLLM/MLX embeddings: `http://127.0.0.1:8001/v1/embeddings`
- llama.cpp rerank: `http://127.0.0.1:8080/v1/rerank`

The older metrics-only stack is still available if Qdrant is not needed:

```bash
docker compose -f ops/metrics/docker-compose.yml up -d
uv run code-diver --config configs/protogen.yml experiment
```

The stack runs ClickHouse for metrics storage and Grafana with a provisioned dashboard. Tables use the configured `metrics.retention_days` TTL, and the compose file caps ClickHouse memory/CPU for local experimentation.

Static reports can be generated from JSON eval output:

```bash
uv run code-diver --config configs/intellij-community-vllm-qdrant.yml experiment --json \
  > .code-diver/reports/intellij-hypotheses.json
uv run python scripts/build_eval_report.py \
  .code-diver/reports/intellij-hypotheses.json \
  --output .code-diver/reports/intellij-hypotheses.html
```

The report includes metric tables, confidence intervals, per-metric charts, and per-case distributions when detailed results are present. The Grafana dashboard shows the same comparison over stored ClickHouse runs.
Stored ClickHouse case rows include file-level metrics, query buckets, and result-kind fields, so Grafana can show where each strategy wins or fails instead of only reporting one average.

For isolated runs, use the Alpine runtime container in `ops/runtime`. It mounts a target codebase at `/workspace`, writes artifacts under `/artifacts`, uses Qdrant for vectors, and writes metrics to ClickHouse over the compose network:

```bash
docker compose -f ops/runtime/docker-compose.yml build code-diver
CODEBASE_PATH=/absolute/path/to/repo \
ARTIFACTS_PATH=/absolute/path/to/artifacts \
docker compose -f ops/runtime/docker-compose.yml run --rm code-diver index
```

`evaluate-indexing` and `evaluate-search-tools` run the direct orchestrator against YAML hypotheses and write full JSONL transcripts under `.code-diver/traces`.

`chat` starts interactive Pi. `ask` runs Pi in print mode. Both load `.pi/extensions/code-diver-rag.ts`, which registers:

- `code_diver_index`
- `code_diver_search`
- `code_diver_inspect`
- `code_diver_open`
- `code_diver_evaluate`
- `code_diver_experiment`
- `code_diver_tree`
- `code_diver_grep`
- `code_diver_rg`
- `code_diver_read`
- `code_diver_symbols`
- `code_diver_record_failure`
- `code_diver_record_success`

Pi arguments and the active tool allowlist are configured in `code-diver.yml`:

```yaml
pi:
  binary: npm
  launcher_args:
    - exec
    - --
    - pi
  extension: .pi/extensions/code-diver-rag.ts
  prompt_template: .pi/prompts/code-diver-rag.md
  provider: google
  model: google/gemini-3.1-flash-lite
  fallback_models:
    - google/gemini-2.5-flash
  session_dir: .code-diver/pi-sessions
  env:
    PI_CACHE_RETENTION: long
  tools:
    - code_diver_search
```

The tool allowlist should stay read-only. Do not add `bash` or editing tools for this assistant; use the `code_diver_*` tools for repository inspection. Pi sessions, compaction, cache accounting, and interactive rendering are handled by Pi; Code Diver supplies the read-only tools, the code-search prompt, and a project-local session directory.

When the user explicitly corrects or confirms a Search agent answer, the agent can
record feedback under `.code-diver/feedback/fail-cases.jsonl` or
`.code-diver/feedback/success-cases.jsonl`. Tool results are rendered compactly in
the Pi UI; the model still receives the structured tool payload.

Useful chat session commands:

```bash
uv run code-diver chat --name "Team builder investigation"
uv run code-diver chat continue
uv run code-diver chat resume
uv run code-diver chat resume <partial-session-id>
uv run code-diver chat --session <path-or-id>
```

`search` renders colored, syntax-highlighted snippets and uses a pager for larger result sets. Editor opening is configured in `code-diver.yml`:

```yaml
ui:
  pager: auto
  links: true
  editor:
    command: code
    args: ["-g", "{path}:{line}"]
```

## Dataset Format

Evaluation datasets are JSONL. Each line is one retrieval task:

```json
{"id":"scanner-basic","query":"code that scans repository files","expected":["src/code_diver/services/codebase_scanner.py"]}
```

`expected` entries can match an indexed item id exactly, or be a path prefix such as `src/code_diver/services/codebase_scanner.py`.

## Plugin Hooks

Add one or more plugin files to `code-diver.yml`. A plugin can define any of these functions:

```yaml
plugins:
  - path/to/plugin.py
```

```python
def collect_items(root, config):
    yield {"id": "docs:intro", "path": "README.md", "title": "Intro", "content": "...", "metadata": {}}

def transform_item(item):
    item["content"] = item["content"].strip()
    return item

def prepare_query(query):
    return query
```

The core scanner always runs first. Plugins can add extra items, transform all items, and normalize queries.
