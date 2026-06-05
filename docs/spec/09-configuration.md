# 09 — Configuration & CLI

## Configuration system

Files: `config/*` (~18 dataclasses), `settings/defaults.py`, `config/config_loader.py`,
`code-diver.yml` + `configs/*.yml`. Entry env: `env/env_file_loader.py`,
`settings/environment.py`.

### Loading contract

```
YAML file ──▶ ConfigLoader ──▶ AppConfig (dataclass tree) ──▶ subsystems
.env (optional) ──▶ EnvFileLoader ──▶ os.environ ──▶ providers read keys at init
```

`AppConfig` aggregates: `storage`, `embedding`, `generation`, `indexing`, `scanner`,
`search`, `hybrid_search`, `recursive_search`, `graph`, `pi`, `evaluation`,
`experiments`, `metrics`, `ui`, `trace`, `plugins`, plus `root` / `artifact` paths.

### Defaults pattern

Every config field default reads `Defaults.X`; `ConfigLoader` then does
`mapping.get("key", Defaults.X)` — the same constant is referenced in up to three places.

⚠️ Divergences:
- **(1.2, High)** Validation is **structural only** (is-it-a-dict). No semantic checks:
  weight sums (R-5 ships because of this), `dimensions > 0` (`None` propagates),
  `timeout_ms > 0`, `indexing.mode ∈ {scanner,ai,orchestrated}`, `search.strategy ∈
  RetrievalStrategyId`. Typos silently fall back to defaults.
- **(1.3, Medium)** `Defaults.MAX_FILE_BYTES = 1_000_000` is **not referenced** by the 8+
  constructors that hardcode `max_file_bytes: int = 1_000_000` (every inspection service
  + 3 orchestrators + scanner). Changing the default propagates to none of them.
- (1.1) Three-layer default duplication (Defaults / field default / loader `.get`)
  invites silent skew.
- (1.4) Generation provider selection uses raw strings, not an enum.
- **(1.5, High)** ClickHouse password hardcoded, no env indirection (see [07](./07-providers-and-storage.md)).

### New config dataclasses & knobs (2026-06-01)

**`config/llm_rerank_config.py` — `LlmRerankConfig`** (Flash-Lite rerank tuning):

| Field | Default |
|-------|---------|
| `candidate_limit` | `30` |
| `rerank_limit` | `10` |
| `max_preview_chars` | `700` |
| `mode` | `precision` (in `file_first` / `base_rank_prior` / `precision` / `compact`) |
| `include_reasons` | `False` |
| `preserve_top_candidate` | `False` |
| `preserve_top_score_margin` | `0.0` |
| `retry_attempts` | `3` |

**New `HybridSearchConfig` knobs** (see [04](./04-hybrid-search.md)):
`vector_kind_limits` (`{}`), `vector_kind_multipliers` (`{}`), `file_vote_weight`
(`0.0`), `preserve_vector_top` (`False`), `vector_top_score_margin` (`0.0`).

**Default search/index profile:** no-config commands now use the H6.1 file locator
setup:

- `search.strategy: hybrid`;
- local EmbeddingGemma-300M through an OpenAI-compatible endpoint for embeddings;
- calibrated H3 hybrid candidates with vector/lexical/path/symbol/graph weights;
- LLM reranking/Search agent responses are optional experiments on top of this default;
- file-level persistent index only:
`line_chunks: false`, `structural_chunks: false`, `symbol_chunks: false`,
`file_summary_chunks: true`, and `file_manifest_chunks: true`. The persistent index
embeds file metadata, not full source bodies. File enumeration is gitignore-aware via
`rg --files --no-require-git`; if `rg` is unavailable, the scanner falls back to the older
`os.walk` enumerator with built-in excludes.

**Built-in embedding extractor profiles:** `init --embedding qwen3-0.6b`,
`init --embedding qwen3-4b`, `init --embedding qwen3-0.6b-vllm`,
`init --embedding qwen3-4b-vllm`, `init --embedding embeddinggemma-300m`,
`init --embedding embeddinggemma-300m-vllm`, and `init --embedding gemini` write the default
extractor into `.code-diver/runtime.yml`. `index` uses that configured extractor
automatically. Apple profiles use MLX-converted Qwen checkpoints or EmbeddingGemma through
vLLM-Metal; CUDA, ROCm, and CPU profiles use regular Hugging Face checkpoints through vLLM.
EmbeddingGemma requires accepting the Hugging Face Gemma license and exporting `HF_TOKEN`
before first model download. Gemini is API/Vertex only.

**Runtime setup:** `code-diver init` writes `.code-diver/runtime.yml`. In a TTY, it opens an
arrow-key setup wizard for platform, embedding extractor, runtime backend, port, and install
confirmation. Non-interactive automation should pass `--platform`, `--embedding`,
`--runtime`, and usually `--yes`. `--runtime host-uv` installs a platform-specific runtime
venv with `uv` and lets later commands autostart the embedding server subprocess.
`--platform apple-metal` installs the `runtime-apple-metal` dependency group under
`.code-diver/runtime/vllm-metal`; `--platform nvidia-cuda`, `amd-rocm`, and `cpu` install
the `runtime-vllm` dependency group under `.code-diver/runtime/vllm`. `--runtime external`
records that the endpoint is managed outside Code Diver, for example by Docker or a remote
server; later commands only check readiness and fail with an actionable message if it is
down.

**Default vector store:** `code-diver.yml` points Qdrant at `http://localhost:6333` and uses
larger upsert batches for normal development runs. `init`, `index`, `search`, and
`evaluate` treat that local URL as managed infrastructure and start the `qdrant` Docker
Compose service when it is not already reachable. Embedded Qdrant `location:` mode and
remote Qdrant URLs are left unmanaged by design.

**Default collection lifecycle:** when the configured Qdrant collection is the default
`code_diver` base, CLI runtime resolution expands it to a deterministic
repo/model-specific collection alias:
`code_diver__repo_<repo>_<hash>__emb_<provider>_<model>_<settings>_<hash>`. Plain `index`
creates that collection only when it is missing. Existing collections require
`index --update-index` to replace the current repo/model collection or `index --override-repo`
to delete all collections for the current repository namespace before rebuilding. `index
clear` removes the current repository namespace; `index clear --all` removes all default
Code Diver index collections. Explicit non-default collection names in YAML are preserved.

**New `ScannerConfig` knob:** `structural_chunks` (`False`) — see
[02](./02-indexing.md) structural chunking.

Corresponding `Defaults` entries were added for each new field (rerank candidate
limit / preview chars / mode / reasons / preserve-top, hybrid split-vector and
vote/guard knobs, and `STRUCTURAL_CHUNKS`).

### New config knobs (2026-06-02)

- **`HybridSearchConfig.symbol_match_weight`** (`0.0`) — dedicated symbol-name-match
  signal (see [04](./04-hybrid-search.md)). Default `HYBRID_SYMBOL_MATCH_WEIGHT`.
- **`ScannerConfig.line_chunks`** (`True`) and **`ScannerConfig.max_symbols_per_file`**
  (`None`) — deterministic-indexing toggles (see [02](./02-indexing.md)). Defaults
  `LINE_CHUNKS`, `MAX_SYMBOLS_PER_FILE`.
- **`OpenAIEmbeddingProvider.send_dimensions`** (`True`) — opt out of the `dimensions`
  param for models that don't support it (see [07](./07-providers-and-storage.md)).

### Config sprawl

⚠️ **(5.4, Medium)** 13+ root-level YAML files (`code-diver.yml`, `container*.yml`,
`protogen*.yml` ×9) each repeat the full ~200-line schema for minor variations. No
inheritance/overlay. Common blocks (scanner patterns, stop words, graph settings) are
copy-pasted; the primary config re-declares values that defaults already provide.
Documentation-by-repetition, not DRY.

The local-model work added yet more single-purpose YAML configs in `configs/`
(`protogen-vllm-embedding-benchmark.yml`, `intellij-community-vllm-qdrant.yml`,
`protogen-qwen-embedding-local-ranker-*.yml`, `protogen-gemma-e4b-*.yml`) — evidence that
config sprawl is **continuing** (cross-ref finding 5.4).

### Over-engineering note

⚠️ **(5.2, Medium)** `strategies/` holds 24 files averaging ~50 LOC; several are 9–25
line pure data containers (`hybrid_query.py`, `graph_neighbor.py`,
`hybrid_item_profile.py`). 18 config dataclasses + a 347-line loader + 155-line defaults
file is a heavy config surface for ~10k LOC. The "screaming architecture" shows in
*names* but the fine-grained split has not paid off in testability (the data classes are
untested).

## CLI — `cli.py`

The public assignment surface shown by default is:

`init` · `index` · `search` · `evaluate`

`search` is the code-exploration entrypoint; `chat` is kept as a hidden alias for the
same Search agent flow. Advanced inspection/research commands are available behind
`--help-all`:

`index-selected` · `tree` · `grep` · `rg` · `read` · `symbols` · `open` · `chat` · `ask`
· `evaluate-indexing` · `evaluate-search-tools` · `experiment`.

**Contract (intended)**: `cli.py` is the argument-parsing + dispatch boundary; business
logic lives in services.
⚠️ **(5.1, High)** Reality: `cli.py` is 2,169 lines and contains evaluation metrics,
result serialization, graph-indexer construction, search-tool wiring, and experiment
config mutation. It is the de-facto orchestration layer. Top-level error handling is
`print(f"error: {exc}")` (⚠️ 4.4) — tracebacks discarded, no stdlib `logging` anywhere
in the 190 files.

## Config/CLI invariants (intended vs actual)

| # | Intended | Status |
|---|----------|--------|
| 1 | One source of truth per default | ⚠️ 1.1 / 1.3 |
| 2 | Config semantically validated at load (fail-fast) | ❌ 1.2 |
| 3 | All secrets via env | ❌ 1.5 |
| 4 | DRY config with inheritance | ❌ 5.4 |
| 5 | CLI = parse + dispatch only | ❌ 5.1 |
| 6 | Structured logging available | ❌ 4.4 |
