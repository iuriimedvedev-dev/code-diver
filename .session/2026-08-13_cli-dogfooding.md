# 2026-08-13 — CLI dogfooding: `answer` lands, two defects found by using it

Plan: `.plans/2026-08-13_answering-core-extraction.md` (phases 1-4).

## Shipped

- `code-diver answer` runs live end to end on this repository (tasks #41-#43 closed). Answer +
  citations + timing trace; `--json` for machine consumption; fails fast when no index exists.
- `ask` now defaults to the **answering core**, not the pi agent. `--agent` opts back into pi.
  `chat` stays on pi — it is the interactive surface, not the answer engine.
- Answer flags live in one `add_answer_arguments()` so `answer` and `ask` cannot drift apart.
- pi extension (`.pi/extensions/code-diver-rag.ts`): added the missing `code_diver_answer` tool,
  replaced `uv run` with the venv entry point, and pointed the provider defaults at the generator
  this repo can actually start (`:8012` / `mlx-community/Qwen3.5-4B-OptiQ-4bit`). The old defaults
  (`:8016` / `gemma-4-26B-A4B-it-qat-UD-Q4_K_XL`) exist in no config, script or source file.
- Prompt (`.pi/prompts/code-diver-rag.md`) now tells the agent to answer *through* the pipeline and
  verify its citations, instead of composing answers from raw search hits.

## Defect 1 — sibling virtualenvs were indexed (found by dogfooding, fixed)

The first `answer` run cited `orchestration/` modules instead of the `answering/` modules created
hours earlier: the index was stale. Reindexing revealed why that had gone unnoticed —
`DEFAULT_EXCLUDES` excluded `.venv/**` but not `.venv-vllm-metal-official/**` (21,413 indexable
files) or `.venv-vllm-metal/**` (13,318). The run was heading for ~33,792 files against a real
source tree of 811. A broken exclusion never fails; it just buries the codebase in its own
dependencies.

- `.venv/** -> .venv*/**`, `venv/** -> venv*/**`.
- That exposed a second, more general flaw: `dir/**` also matched a **file** whose own name fit the
  pattern (`venv*/**` matched `src/venv_helper.py`), because the segment-run matcher compared the
  final segment too. `_is_excluded` now takes `is_dir`; for a file path the run must end above the
  file. The walk branch passes `is_dir=True` when pruning.
- No measurement is affected: protogen's venv is plain `.venv` (already excluded), IntelliJ and the
  CSN corpora have none. Test: `test_sibling_virtualenvs_are_excluded_not_only_dot_venv`.
- After the fix: 1622 items = 811 files x {file_summary, file_manifest} — the lean file-level index
  the architecture calls for. Re-asked the same question: it now cites
  `answering/answer_pipeline_factory.py` and `strategies/retrieval_strategy_builder.py`.

## Defect 2 — the default config is too slow to work through interactively (open)

Measured on this repo, machine NOT idle (OrbStack, Chrome, three agent processes), so treat as
shares not seconds (Finding 37):

| run | retrieval | generation |
|---|---|---|
| `answer` (stale 541-file index) | 15.2 s | 17.0 s |
| `answer` (fresh 811-file index) | 40.9 s | 13.9 s |
| `ask --json` | 209.8 s | 22.9 s |
| bare `search` | 225 s (whole command) | — |

The generator log explains it: `mlx_lm server` serves requests **serially**, and the prompts are
large — 8,375 tokens for the LLM rerank, 12,094 for the answer. One 12k-token request spent 3 m 36 s
in decode. So interactive latency is dominated by queued LLM calls on the shared `:8012` generator,
and `graph_file_rerank` puts an LLM call in front of *every* search, including a bare `search`.

## Plan §4 verification — refactor confirmed, and it exposed a reproducibility leak

6 protogen cases (`datasets/protogen_answer_cases_6.jsonl`), config
`configs/context-awareness/protogen-h29-ctrl-strict-cite.yml`, judge OFF, HEAD (11a2711) in a
throwaway worktree vs the refactored working tree, run back-to-back on the same servers.

- **5 of 6 cases byte-identical** — retrieved files, context files, context text, query plan,
  raw prediction and citations all equal. The `AnswerService` extraction changed nothing observable.
- **1 case differs (`protogen-gemini-operator`) and the cause is upstream of the refactor.** Same
  files, same ranks, same excerpts; the only textual difference is the *retrieval score* printed
  into the context: `score=0.770684` vs `0.770661`, and the same 5th-decimal wobble on the other
  three candidates. Embedding-server float noise (vllm batching on Metal), not answering code — if
  the refactor were responsible, all six cases would have moved.
- That few-character difference in the prompt is enough to change the generated answer, its
  citations, and therefore `bigram_*`, `citation_*`, `key_token_f1` for that case. Which is the
  actual finding: **`AnswerContextBuilder` prints raw scores into the prompt**
  (`answer_context_builder.py:63` and `:98`, `score={result.score:.6f}`), so nondeterministic float
  noise reaches the model. Exact replay of the answer axis is impossible while that holds, and every
  answer-axis arm carries this variance for free.
- Removing or rounding the score changes the prompt and therefore every published number, so it is a
  hypothesis to be measured (H47, task #47), not a quiet fix.

Next step (do NOT change the measured default — task #37 is still open): add a separate interactive
profile that drops the LLM rerank, and compare its quality on the answer axis before proposing it as
anyone's default. The latency numbers above are unusable as evidence — they were taken on a loaded
machine, which is exactly what task #40 exists to fix.
