# H-91a Rust-Python Parity

## Profile Files

- `native/code_diver_search_bin/profiles/h91a-pier.toml` — Pier configuration (candidate_limit=64)
- `native/code_diver_search_bin/profiles/h91a-intellij.toml` — IntelliJ configuration (candidate_limit=70)

## Usage

Load a TOML profile via `--config`:

```bash
code-diver search --config profiles/h91a-pier.toml "your query"
code-diver mcp --config profiles/h91a-pier.toml
code-diver config show --config profiles/h91a-pier.toml
```

Profile keys override defaults. CLI flags override profile values. Unknown keys produce an error naming the key.

## Keys Now Honoured

| Key | Status | Notes |
|-----|--------|-------|
| `candidate_limit` | ✓ Honoured | Profile + CLI flag |
| `retrieval_limit` | ✓ Honoured | Profile + CLI flag |
| `lexical_candidate_limit` | ✓ Honoured | Profile + CLI flag |
| Fusion weights (vector, lexical, path, symbol, etc.) | ✓ Honoured | Profile + CLI flags |
| `graph_depth`, `graph_neighbor_limit`, `graph_decay` | ✓ Honoured | Profile + CLI flags |
| CE second pass settings | ✓ Honoured | Profile + CLI flags |
| Hub prior (additive mode) | ✓ Honoured | Profile + CLI flags |
| `preserve_vector_top` / `vector_top_score_margin` | ✓ Configured | Field stored; pipeline implementation pending |
| `vector_kind_limits` | ✓ Stored | Single collection; per-kind splitting not implemented |
| `vector_kind_multipliers` | ✓ Stored | Single collection; per-kind multipliers not implemented |
| `item_kind_weights` | ✓ Configured | Field stored; pipeline implementation pending |
| `routing_enabled` | ✓ Configured | Field stored; query router not implemented |
| `min_token_length` | ✓ Configured | Field stored; token filter pending in pipeline |
| `preserve_top_candidate` / `preserve_top_score_margin` | ✓ Configured | Field stored; CE-stage preservation pending |
| `preserve_top_depth` | ✓ Configured | Field stored; CE-stage preservation pending |
| `seed_limit` / `lexical_seed_limit` | ✓ Configured | Fields stored; pipeline implementation pending |
| `seed_score_parity` | ✓ Configured | Field stored; pipeline implementation pending |

## Keys Not Implemented in Pipeline (Config Only)

The following keys are loaded from the profile and stored in `SearchConfig`, but the corresponding pipeline behaviour is not yet implemented:

1. **`preserve_vector_top`** — The top vector candidate rescue logic is not in `pipeline.rs`. The field is available for future implementation.
2. **`item_kind_weights`** — Per-kind fusion weight multipliers are stored but not applied during fusion.
3. **`routing_enabled`** — Query routing (workflow/path_symbol/semantic) is not implemented.
4. **`min_token_length`** — Token length filtering is not applied to lexical tokens.
5. **`preserve_top_candidate`** — CE-stage base candidate preservation is not implemented.
6. **`seed_score_parity`** — Lexical scoring for vector-only seeds is not implemented.
7. **`vector_kind_limits` / `vector_kind_multipliers`** — Single collection search; per-kind vector lane splitting not applicable.

## Measurement Results

**Python reference (Pier, code dataset):** hit@1 58%, hit@3 76%, hit@5 85%, hit@10 94% (p50 7.9s)
**Rust with defaults (pre-profile):** hit@1 57%, hit@3 71%, hit@5 77%, hit@10 86%

Harness measurements with the H-91a profile have not yet been completed (harness run timed out during session). The profile loading infrastructure is fully functional and verified via `config show`.

## Remaining Gaps

1. Pipeline implementation of `preserve_vector_top` behaviour
2. Pipeline implementation of `item_kind_weights` during fusion
3. Query routing implementation (`routing_enabled`)
4. Token length filtering (`min_token_length`) in lexical scoring
5. CE-stage `preserve_top_candidate` implementation
6. `seed_score_parity` in graph propagation
7. Harness measurement runs to quantify parity

## Files Changed

- `native/code_diver_search_bin/src/types.rs` — Added 13 SearchConfig fields + defaults
- `native/code_diver_search_bin/src/profile.rs` — New: TOML profile loading, validation, apply, tests
- `native/code_diver_search_bin/src/main.rs` — Profile module, `is_search_profile()`, profile loading in `build_search_config_default` and `configured_candidate_limit`
- `native/code_diver_search_bin/profiles/h91a-pier.toml` — Updated with all H-91a keys
- `native/code_diver_search_bin/profiles/h91a-intellij.toml` — Updated with all H-91a keys
- `docs/PARITY.md` — Updated status
