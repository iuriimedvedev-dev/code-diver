# Code Diver

`code-diver` is a small CLI sandbox for codebase RAG experiments. The CLI is the entrypoint. Reproducible evals use a direct provider-backed orchestrator; `chat` and `ask` still launch the optional Pi interactive backend.

## Setup

```bash
uv sync
export GEMINI_API_KEY="..."
```

By default `chat` and `ask` launch Pi through `npx -y @earendil-works/pi-coding-agent`.
Secrets can also live in `.env`; the CLI loads it before creating providers. `.env` is ignored by git.

Gemini-backed defaults:

- Pi model: `google/gemini-3.5-flash`
- generation model: `gemini-3.5-flash`
- embedding model: `gemini-embedding-2`
- embedding dimensions: `768`

Configuration lives in `code-diver.yml`. For local, reproducible experiments without an API key, set:

```yaml
embedding:
  provider: hash
  dimensions: 256
```

## Commands

```bash
uv run code-diver index
uv run code-diver search "where is authentication configured?"
uv run code-diver tree
uv run code-diver grep "authenticate"
uv run code-diver rg "auth.*user"
uv run code-diver open "where is authentication configured?"
uv run code-diver chat
uv run code-diver ask "summarize the retrieval pipeline"
uv run code-diver evaluate
uv run code-diver evaluate-indexing
uv run code-diver evaluate-search-tools
uv run code-diver experiment
```

## Retrieval Experiments

`code-diver.yml` controls storage and retrieval strategy:

```yaml
storage:
  provider: json # or qdrant

search:
  strategy: vector # vector, recursive, graph
```

See [docs/assignment-plan-progress.md](docs/assignment-plan-progress.md) for the assignment plan, estimates, progress log, and deliverable map. See [docs/research.md](docs/research.md) for the current codebase RAG research notes and experiment plan, [docs/metrics.md](docs/metrics.md) for metric definitions and current run comparisons, and [docs/optimization-audit.md](docs/optimization-audit.md) for the latest optimization audit and roadmap.

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

`configs/protogen.yml` indexes the sibling `../protogen` repo into local Code Diver artifacts while keeping the source repo read-only:

```bash
uv run code-diver --config configs/protogen.yml index
uv run code-diver --config configs/protogen.yml search "where is the arena runner implemented?"
uv run code-diver --config configs/protogen.yml evaluate --json
uv run code-diver --config configs/protogen.yml experiment
```

The config uses deterministic hash embeddings for repeatable local testing. Switch `embedding.provider` to `gemini` and `storage.provider` to `qdrant` when running live Gemini/Qdrant experiments.

For model-orchestrated indexing, use `indexing.mode: orchestrated`. The generation model sees repository structure, file names, aggregate stats, config constraints, and index metadata. It does not receive source code contents. Local scanners build chunks, and embedding providers create retrieval vectors from those chunks.

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
  model: gemini-3.5-flash
  timeout_ms: 20000

embedding:
  provider: gemini # openai or hash also supported
  model: gemini-embedding-2
  batch_size: 32
  workers: 1
  max_input_chars:
```

For OpenAI, set `OPENAI_API_KEY` and use `generation.provider: openai` plus `embedding.provider: openai`. Defaults are `gpt-5.1` and `text-embedding-3-large`.

Gemini Embedding 2 is not wire-compatible with `gemini-embedding-001`: existing Gemini embedding artifacts must be rebuilt after switching models.

For local embeddings on Apple Silicon, use an OpenAI-compatible embedding server backed by vLLM/MLX. The current preferred path is vLLM pooling on `http://127.0.0.1:8001/v1/embeddings`, with Gemini or Vertex kept for orchestration/reranking experiments. `configs/protogen-local.yml` is kept for fully local OpenAI-compatible experiments on `http://localhost:1234/v1`.

Local embedding configs can set `embedding.workers` for parallel embedding requests and `embedding.max_input_chars` to fit smaller local model context windows. For small local embedding contexts, use `batch_size: 1` and increase `workers` instead of sending large multi-input batches.

```bash
uv run code-diver --config configs/protogen-local.yml index
uv run code-diver --config configs/protogen-local.yml experiment

VLLM_HOST_IP=127.0.0.1 \
GLOO_SOCKET_IFNAME=lo0 \
VLLM_METAL_MEMORY_FRACTION=0.55 \
.venv-vllm-metal-official/bin/vllm serve mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ \
  --runner pooling \
  --host 127.0.0.1 \
  --port 8001 \
  --max-model-len 512

uv run code-diver --config configs/intellij-community-vllm-qdrant.yml index
uv run code-diver --config configs/intellij-community-vllm-qdrant.yml experiment
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

Start the local runtime stack before Qdrant/metrics-backed experiment runs:

```bash
docker compose up -d qdrant clickhouse grafana
curl -fsS http://localhost:6333/collections
curl -fsS http://localhost:18123/ping
```

If another Qdrant is already bound to `6333`, either reuse that running instance or start this stack on alternate host ports:

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

Pi arguments and the active tool allowlist are configured in `code-diver.yml`:

```yaml
pi:
  binary: npx
  launcher_args:
    - -y
    - "@earendil-works/pi-coding-agent"
  extension: .pi/extensions/code-diver-rag.ts
  prompt_template: .pi/prompts/code-diver-rag.md
  provider: google
  model: google/gemini-3.5-flash
  fallback_models:
    - google/gemini-3-flash-preview
    - google/gemini-2.5-flash
  tools:
    - code_diver_search
```

The tool allowlist should stay read-only. Do not add `bash` or editing tools for this assistant; use the `code_diver_*` tools for repository inspection.

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
