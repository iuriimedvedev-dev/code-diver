# Symbols-First Ordering — WHERE-79 Breakthrough

## Result
**H52v2 symbols-first: recall@10 = 0.7650** — beats jbcontext (0.685) on WHERE-79.

## Changes Made

### 1. Symbols-first summary ordering
`FileSummaryItemBuilder.build()` now puts `_symbols_section` BEFORE `_head_section`:
- Before: `file → extension → head → symbols → imports`
- After: `file → extension → symbols → head → imports`

With `max_input_chars: 500`, the first 500 chars now include method signatures
instead of class declaration. Method signatures are the most useful signal for
WHERE queries (e.g., "project opening" → `openProject()`).

### 2. Import cap in head section
`max_head_import_lines = 5` limits imports in the head section to prevent them
from dominating the 24-line budget. The class declaration now fits.

### 3. KDoc/Javadoc regex fix
`LICENSE_OR_COPYRIGHT_RE` changed from `^\s*/\*` to `^\s*/\*(?!\*)` to not match
`/** KDoc */` as boilerplate.

### 4. Token-aware truncation fix
`truncate_embedding_text` now uses `_MODEL_MAX_TOKENS = 512` (model's actual
token limit) instead of `max_input_chars` (character limit). The `_bounded_prefixed`
method in `openai_embedding_provider.py` also uses `_MODEL_MAX_TOKENS = 512`.

## Eval Results

### WHERE-79 (n=79)
| System | recall@10 | MRR@10 | hits |
|---|---|---|---|
| H46 baseline (hybrid only) | 0.503 | 0.285 | 44/79 |
| H46 + listwise | 0.548 | 0.270 | — |
| H52 hybrid only | 0.516 | 0.286 | — |
| **H52v2 full pipeline** | **0.765** | **0.298** | **64/79** |
| jbcontext | 0.685 | 0.347 | — |

### Holdout 36 (n=36)
- recall@10 = 0.722 (same as previous H52)
- MRR@10 = 0.315
- hits = 26/36

### Pool Analysis
- H52v2 gold-in-pool@20 = 54/79 (vs H46's 57/79)
- The improvement comes from graph-file search stage, not hybrid search
- Graph-file search expands the pool and finds gold files outside hybrid top-20

## Key Insight
The improvement is from **symbols-first ordering in the summary text**, not from
any embedding config change. The 500-char budget now includes method signatures
like `openProject()`, `closeProject()`, which directly match WHERE query intents
like "where is project opening orchestrated".

## Pending
- 1065 eval (killed after 43min, stuck). Needs re-run with different approach.
- Listwise on H52v2 pool (no LiteLLM server available).
- Champion YAML not flipped — need 1065 results first.