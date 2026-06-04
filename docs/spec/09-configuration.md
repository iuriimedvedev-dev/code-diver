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
| `candidate_limit` | `40` |
| `max_preview_chars` | `700` |
| `mode` | `file_first` (∈ `file_first` / `base_rank_prior` / `precision` / `compact`) |
| `include_reasons` | `True` |
| `preserve_top_candidate` | `False` |
| `preserve_top_score_margin` | `0.0` |

**New `HybridSearchConfig` knobs** (see [04](./04-hybrid-search.md)):
`vector_kind_limits` (`{}`), `vector_kind_multipliers` (`{}`), `file_vote_weight`
(`0.0`), `preserve_vector_top` (`False`), `vector_top_score_margin` (`0.0`).

**Default index profile:** `code-diver.yml` now uses the H5-style file locator setup:
`line_chunks: false`, `structural_chunks: false`, `symbol_chunks: false`,
`file_summary_chunks: true`, and `file_manifest_chunks: true`. The persistent index
embeds file metadata, not full source bodies.

**Built-in embedding extractor profiles:** `index --embedding qwen3-0.6b`,
`index --embedding qwen3-4b`, and `index --embedding gemini` override only the embedding
block for that run. In an interactive terminal, `index` can ask for the extractor unless
`--no-embedding-prompt` is passed. Qwen profiles expect a local OpenAI-compatible
vLLM/MLX embedding server on `127.0.0.1:8001`; Gemini is API/Vertex only.

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

13 subcommands dispatched from `main(argv)` / `build_parser()`:

`index` · `index-selected` · `search` · `tree` · `grep` · `rg` · `read` · `symbols` ·
`open` · `chat` · `ask` · `evaluate` · `evaluate-indexing` · `evaluate-search-tools` ·
`experiment`.

**Contract (intended)**: `cli.py` is the argument-parsing + dispatch boundary; business
logic lives in services.
⚠️ **(5.1, High)** Reality: `cli.py` is 1,041 lines and contains evaluation metrics,
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
