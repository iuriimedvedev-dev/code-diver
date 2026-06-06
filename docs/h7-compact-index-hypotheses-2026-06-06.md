# H7 Compact File-Level Index Hypotheses - 2026-06-06

## Objective

Improve file-level retrieval without returning to persistent code-body chunks.
The target shape stays:

```text
query
-> compact persistent file locator
-> bounded LLM rerank / agent probes
-> read exact code only after files are selected
```

So the index should stay small, hot, and cheap to rebuild.

## Proposed Additions

| ID | Change | Expected Benefit | Cost | Risk | Status |
| --- | --- | --- | --- | --- | --- |
| `H7.1` | Add one `file_api_manifest` vector per file with signatures, identifier terms, symbol counts, and short doc/comment hints. | Better bridge from natural-language/function-docstring queries to the file that owns the relevant API. | About +50% vectors versus H6.1 because H6.1 has two vectors/file and H7.1 has three. | Doc hints can overfit CodeSearchNet-style docstring queries; must validate on repo-local/e2e questions too. | implemented, pending eval |
| `H7.2` | Add query-time identifier expansion: camel/snake/path splitting, exact alias variants, and configurable domain synonyms. | Helps keyword-collapse cases without increasing index size. | Near-zero persistent cost; small query CPU cost. | Synonym noise can hurt precision if global and uncalibrated. | proposed |
| `H7.3` | Add file role metadata: controller/service/repository/model/config/test/entrypoint/plugin based on path + symbols. | Helps informal questions such as "where is auth handled?" by boosting likely architectural roles. | Metadata only, optional ranking feature. | Role heuristics are language/framework-sensitive. | proposed |
| `H7.4` | Add dependency-neighborhood metadata: local imports, exported symbols, fan-in/fan-out counts. | Helps workflow and architecture questions where the target is connected rather than text-similar. | Metadata + graph artifact growth; no extra vectors if kept out of embeddings. | High fanout can add related-but-wrong files. | proposed |
| `H7.5` | Add candidate-only symbol/docstring micro-index over the top 30-50 files after H6.1. | Tests whether deeper local search helps only after the locator narrows the repo. | Per-query build/query cost; no persistent growth if cached ephemerally. | Previous H2B failed when chunks displaced good locator files; must keep file candidates monotonic. | proposed |

## H7.1 Index Text

`file_api_manifest` intentionally does not embed function bodies. It embeds:

- file path and extension;
- symbol count by kind;
- compact API signatures;
- split identifier terms from path, symbol names, and signatures;
- call terms from AST/generic call extraction;
- attribute/import terms;
- resource terms from URLs, domains, SQL/config/file/network-ish strings;
- deterministic effect tags such as `auth`, `database`, `network`,
  `filesystem`, `process`, `message`, and `config`;
- short docstrings or nearby comments.

Example:

```text
file: users.py
filename: users.py
extension: .py
symbol_count: 2 (class=1, method=1)
api_symbols:
- class UserService: class UserService:
- method UserService.update_user: def update_user(self, user_id: str):
identifier_terms: users py user service update id str
call_terms: session post bool
attribute_terms: requests session client post
resource_terms: https api example com users update
effect_tags: auth network
doc_hints:
- UserService: Manage user lifecycle.
- update_user: Update a user profile and authorization state.
```

This should help CodeSearchNet-style queries because the benchmark query often
resembles a docstring or behavior description, while H6.1 can dilute the target
function inside a whole-file summary.

## Evaluation Plan

Hold fixed:

- dataset: CodeSearchNet/MTEB Python 100-case local positive slice first;
- embedding: `google/embeddinggemma-300m`;
- base search: H6.1 calibrated hybrid weights;
- agent/reranker for first agentic check: current best completed local QAT setup,
  `Gemma 4 26B-A4B QAT` via llama.cpp, monotonic candidate guard.

Compare:

| Run | Index | Search/Rerank |
| --- | --- | --- |
| Control | H6.1 `file_summary` + `file_manifest` | same agent/reranker |
| Treatment | H7.1 adds `file_api_manifest` | same agent/reranker |

Required metrics:

- Hit@1/3/5/10;
- Recall@3/5/10;
- Precision@10;
- MRR@10;
- nDCG@10;
- mean/p95 latency;
- model calls, tool calls, tokens;
- index item count, content MB, vector count, build time;
- degraded/error/fallback rates.

Promotion rule:

`H7.1` is worth keeping if it improves Hit@1 or MRR materially without lowering
Hit@10 and without making the persistent index exceed the compact-index budget.
If it only improves CodeSearchNet but hurts repo-local/e2e explanation cases,
keep it as a benchmark-specific variant, not the default.

## Implementation

Current implementation files:

- `src/code_diver/services/file_api_manifest_item_builder.py`;
- `src/code_diver/services/codebase_scanner.py`;
- `src/code_diver/config/scanner_config.py`;
- `src/code_diver/config/config_loader.py`;
- `src/code_diver/domain/code_item_index_kind.py`;
- `configs/benchmarks/codesearchnet-agent-axis-local-100-h7-api-manifest.yml`.

The default H6.1 config remains unchanged because
`file_api_manifest_chunks` defaults to `false`.

Sidecar trace review found the best target failures are CodeSearchNet cases
where the expected file is present around rank 11-30 or has useful vector score
but weak lexical/symbol support. Examples include synthetic filenames with
behavior hidden in API calls or literals: `resetdb`, `WasbHook.load_file`,
`SlackHook.call`, `task_runner.terminate`, and FFmpeg download streams. The
new API/effect sections are designed specifically for those cases.
