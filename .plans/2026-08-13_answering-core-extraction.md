# Answering core extraction — one pipeline for product and evals

Decision of record (user, 2026-08-12): **the internal Python answering pipeline is the product.**
`ask` / `chat` / pi are front-ends that call it. Nothing else answers.

This plan is the enabling change. Until it lands, every quality number we have describes code that
no user path executes.

---

## 1. What exists today (measured, not assumed)

Four distinct paths can answer a question. They share the retrieval strategies and nothing else.

| # | Path | Entry | Who assembles the pipeline | Measured? |
|---|---|---|---|---|
| 1 | product | `cmd_ask` / `cmd_chat` (cli.py:2030, 2052) → `make_search_agent_runner` (cli.py:1802) → `PiRunner` → `npm exec -- pi` | the pi agent, at runtime, by calling `code_diver_search` | **never** — 2 sessions on disk |
| 2 | answer eval | `cmd_evaluate_answers` (cli.py:2799) | **inline in the CLI**, cli.py:2860-2914 | yes — every 0.8xx number lives here |
| 3 | search-tool eval | `evaluate-search-tools` → `agent/direct_*` | a third agent implementation | partly |
| 4 | pi extension | `.pi/extensions/code-diver-rag.ts` | shells out per-tool, composes the answer itself | never |

Root cause of the divergence, precisely: **path 2 assembles its collaborators inline in a CLI
function, driven off `args.*`.** There is no object anyone else can construct. So paths 1 and 4
had no choice but to grow their own logic.

### 1.1 The inline block that must move (cli.py:2860-2914)

```
make_embedding_provider(config, vector_store.metadata())
make_retrieval_strategy(config, provider, vector_store)
AnswerQueryPlanner(answer_provider, max_queries=args.query_count, repository_context=...)   # if --agentic-queries
HYBRID_RERANK -> HYBRID probe-strategy substitution                                          # if --agentic-query-rerank
query_retrieval_strategy = make_retrieval_strategy(replace(config, search=replace(...)), ...)
AnswerCandidateRerankerFactory().create(config, answer_provider)                             # if --agentic-query-rerank
AnswerJudge(create_generation_provider(judge_config), prompt_path=args.judge_prompt)         # if --judge
```

Plus, earlier in the same function (cli.py:2842-2860), state that is equally part of the pipeline
and equally unreachable from outside:

- `limit = args.limit or config.evaluation.limit`
- `context_files = args.context_files or default_answer_context_files(config)`
- `answer_provider = create_generation_provider(config)`
- `build_repository_context(config, answer_provider)` → read to string → **mutates `config`** by
  back-filling `llm_rerank.repository_context_path`
- `AnswerContextBuilder(config.root, max_files=context_files, lines_per_file=args.context_lines, exclude=inspection_exclude_patterns(config), max_file_bytes=config.scanner.max_file_bytes)`

`AnswerEvaluator` itself (`answering/answer_evaluator.py`) is already a clean `@dataclass(slots=True)`
that takes all of the above as fields. **It is not the problem.** The problem is that only
`cmd_evaluate_answers` knows how to fill those fields.

### 1.2 Three defects in the product path, found while reading it

1. **The pi extension points at a model server that does not exist here.**
   `.pi/extensions/code-diver-rag.ts:490-493` defaults to `http://127.0.0.1:8016/v1` with model
   `gemma-4-26B-A4B-it-qat-UD-Q4_K_XL`. Grep across `configs/`, `code-diver.yml`, `scripts/` and
   `src/`: **`8016` appears nowhere, `26B-A4B` appears nowhere.** Our generator is
   `mlx-community/Qwen3.5-4B-OptiQ-4bit` on `:8012` (`code-diver.yml:24-27`), served by
   `scripts/serve_generator.sh`. So out of the box the pi front-end cannot reach a model unless the
   caller sets three env vars. This alone would explain "2 sessions ever".
2. **The extension shells out `uv run code-diver`** (`.pi/extensions/code-diver-rag.ts:709`).
   `uv run` re-resolves dependencies and reaches GitHub for the `vllm-metal` wheel — the failure
   mode that has already killed eval arms. Every eval script uses `.venv/bin/code-diver` for
   exactly this reason. The product path must too.
3. **There is no answer tool.** The extension registers 14 tools (`code_diver_search`,
   `code_diver_inspect`, `code_diver_read`, `code_diver_grep`, `code_diver_symbols`,
   `code_diver_tree`, …) and not one of them answers a question. pi retrieves, then composes the
   answer in its own agent loop with its own prompt. The measured answer prompt, the citation
   allowlist, the context builder, the query planner and the candidate reranker are all bypassed.

Consequence worth stating plainly: **fixing 1 and 2 alone would not make the product match the
numbers.** Only 3 — routing the answer itself through the core — does that.

---

## 2. Target architecture

```
                       ┌─────────────────────────────────────────┐
                       │ AnswerPipelineFactory                   │
                       │  AppConfig + AnswerPipelineOptions      │
                       │  -> AnswerPipeline (frozen collaborators)│
                       └───────────────┬─────────────────────────┘
                                       │
                    ┌──────────────────┴───────────────────┐
                    │                                      │
          ┌─────────▼──────────┐              ┌────────────▼───────────┐
          │ AnswerService      │              │ AnswerEvaluator        │
          │ answer(query)      │              │ evaluate(cases)        │
          │ -> AnswerOutcome   │              │ -> report (metrics,    │
          │ no metrics, no     │              │    judge, usage)       │
          │ judge, no dataset  │              │ delegates per case     │
          └─────────┬──────────┘              └────────────────────────┘
                    │
     ┌──────────────┼──────────────┬────────────────────┐
     │              │              │                    │
`code-diver     `cmd_ask`      `cmd_chat`      `code_diver_answer`
  answer`                                      (pi extension tool)
```

Two new units, one refactor, zero new behaviour:

- **`answering/answer_pipeline_options.py`** — frozen dataclass of the knobs that today live on
  `args`: `limit`, `context_files`, `context_lines`, `agentic_queries`, `agentic_query_rerank`,
  `agentic_query_search_strategy`, `query_count`, `query_workers`, `omit_context`. Defaults come
  from `AppConfig`, so a caller that passes nothing gets the config-declared pipeline. This is the
  point where "config-first" stops being a slogan: the eval's CLI flags become *overrides* of a
  config default rather than the only way to express the pipeline.
- **`answering/answer_pipeline_factory.py`** — the block from §1.1, moved verbatim, returning an
  `AnswerPipeline` value object (provider, strategy, answer_provider, context_builder,
  repository_context, query_planner, query_retrieval_strategy, query_result_reranker, limit,
  and the possibly-rewritten `config`). Judge construction stays **out** — a judge is an eval
  concern, never a product one.
- **`answering/answer_service.py`** — `answer(query: str) -> AnswerOutcome`. Reuses
  `AnswerEvaluator`'s retrieve → context → prompt → parse path, minus metrics and minus the
  `AnswerCase` dataset shape.

### 2.1 The one real design risk

`AnswerEvaluator._evaluate_case` (answer_evaluator.py:114-210) interleaves the pipeline with metric
computation: `_retrieve` → `_file_bundle_metrics(candidate)` → context → `_file_bundle_metrics(context)`
→ `_answer_prompt` → generate → parse → `_citation_metrics`. The metrics need `case.expected_paths`,
which a product query does not have.

Two ways to split it, and the choice matters:

- **(a) `AnswerService` owns the pipeline; `AnswerEvaluator` calls it and computes metrics from the
  returned `AnswerOutcome`.** Single implementation, guaranteed no drift. Requires `AnswerOutcome`
  to carry everything the metrics need: `search_results`, `retrieved_files`, `context`
  (files + `file_ranges`), `citations`, `plan_payload`, all four usage/model pairs, timings.
- (b) Extract a shared private helper both call. Less invasive, but leaves two orchestrators — the
  exact shape of the current problem.

**Take (a).** The whole point is that there is one pipeline. If `AnswerOutcome` is awkward to
define, that is information about coupling we should pay down now, not route around.

Non-negotiable: `AnswerEvaluator.evaluate()`'s report payload must be **byte-identical** before and
after, on a fixed dataset. That is the refactor's own test (§4).

---

## 3. Phases

Each phase ends in a committable, verifiable state. No phase requires a model server except where
stated, so most of this can be done while the machine is doing measurement work — but see §6.

### Phase 1 — extract the factory (no behaviour change)
1. Add `AnswerPipelineOptions` + `AnswerPipelineFactory` + `AnswerPipeline`.
2. `cmd_evaluate_answers` builds `AnswerPipelineOptions` from `args` and calls the factory. The
   ~55 inline lines become ~6. Judge construction stays in the CLI.
3. Keep the `config` mutation (repository-context back-fill) inside the factory and **return the
   rewritten config** — silently mutating a caller's config is how `llm_rerank.repository_context_path`
   became invisible in the first place.

Verify: `evaluate-answers` on a 5-case slice, report identical to a pre-change run.

### Phase 2 — `AnswerService`, and `AnswerEvaluator` on top of it
1. Define `AnswerOutcome` (§2.1a).
2. `AnswerService.answer(query)` = the pipeline half of `_evaluate_case`.
3. `_evaluate_case` becomes: call the service, then compute metrics/judge from the outcome.
4. Preserve the unjudgeable-row policy and `REASON_GENERATION_ERROR` handling exactly — those are
   the guards that keep a failed generation from silently scoring as a bad answer.

Verify: full-report byte-equality on a fixed dataset slice (§4).

### Phase 3 — `code-diver answer`
A new non-agentic command: query in, grounded answer + citations out, via `AnswerService`.
`--json` for machine consumption.

**Shipped differently from what this section originally said, deliberately.** The plan called for
an **advanced** registration and no `--help` widening. `answer` shipped as a **primary** command and
the restricted metavar was widened to `{init,index,search,answer,evaluate,provider}`, because the
instruction that arrived mid-implementation — make the CLI the interface we ourselves work through —
makes `answer` the product's main verb. Hiding the one command that every published quality number
describes is progressive disclosure applied backwards: the gate exists to hide research plumbing
(`experiment`, the `evaluate-*` family), not the product. `search` returns places, `answer` explains;
both belong in the default help. The non-goal in §5 is superseded for this one command only.

This is the seam every front-end uses. It is also the first time the product and the eval will
provably run the same code.

### Phase 4 — rewire the front-ends
1. `cmd_ask` / `cmd_chat`: default to the core (`AnswerService`) for one-shot answering. Keep the
   pi runner reachable behind an explicit opt-in — pi is the *interactive* surface, not the answer
   engine. `make_search_agent_runner` stays for `chat`.
2. `.pi/extensions/code-diver-rag.ts`:
   - add `code_diver_answer` → `code-diver answer --json`;
   - fix the provider defaults to `:8012` / `mlx-community/Qwen3.5-4B-OptiQ-4bit` (defect 1);
   - replace `uv run` with the venv entry point (defect 2);
   - update `.pi/prompts/code-diver-rag.md` to tell the agent to answer *through* the tool rather
     than composing from raw search hits.

### Phase 5 — wire the evals to the core
1. `evaluate-answers` already runs the core after phase 2 — no further work, but re-baseline
   protogen 247 to confirm 0.817 survives the refactor.
2. **External answer-axis validation on IntelliJ**, which has never been done:
   `datasets/intellij_eval_1000.answer_sets.jsonl` (285,512 bytes) already exists — no labelling
   needed. Requires the generator (`:8012`) and, for scoring, the judge (`:8030`).
3. Decide the fate of `agent/direct_*` (path 3). It is a third agent implementation; if
   `evaluate-search-tools` is still worth keeping, it should at least share the factory. Do not
   delete it in this plan — that is a separate decision with its own evidence.

---

## 4. How the refactor proves itself

`AnswerEvaluator` produces a large nested report. Equality is the test:

1. Before touching anything, run `evaluate-answers` on a small fixed dataset slice with the judge
   **off** (a judge adds LLM nondeterminism; we are testing the refactor, not the model) and keep
   the report.
2. After each phase, re-run and diff. Search-axis replay is deterministic (Finding 69, 999/1000
   byte-identical), so retrieval contributes no noise. Generation at `temperature: 0` should be
   stable; if it is not, that is a finding in its own right and must be recorded before proceeding.
3. Any diff is a regression until explained. "Looks equivalent" is not a result.

Fields expected to differ legitimately: wall-clock timings only.

---

## 5. What this plan deliberately does not do

- **No new retrieval behaviour.** The default retrieval config for large repositories is still
  undecided (task #37, recall-first vs precision-first) and H46 (#38) is unmeasured. The refactor
  must not smuggle in a default change — it would contaminate both questions at once.
- **No judge in the product path.** A judge is a measurement instrument.
- **No `--help` surface widening** — *superseded for `answer` only* (see Phase 3). Progressive
  disclosure at cli.py:235-241 stays intentional for everything else: no research or plumbing
  command gets promoted, and the advanced set is otherwise untouched.
- **No TUI.** There is no TUI framework in this repo — only `ui/trace_monitor.py` and the `monitor`
  command. "TUI exists" in the original request refers to pi's interface, which is pi's, not ours.

---

## 6. Sequencing against the measurement debt

Two measurement debts are queued, unblocked, and both were killed rather than completed:

- **#38 H46** — config written and validated, arm killed at ~46 min, must re-run from scratch.
- **#40 latency** — never ran. Needs an idle machine (standing rule: latency and quality never
  share an arm).

Constraint: **do not run tests, builds, or evals while a measurement arm is in flight** — latency
is a measured quantity (Finding 37), and "not GPU" is not the same as "not heavy". Phases 1-2 are
pure refactor and can be *written* at any time, but their verification runs (§4) touch the
generator and must be scheduled against the arms.

Recommended order: phases 1-2 written now → #38 and #40 arms on an idle machine → §4 verification →
phases 3-5. Restarting the arms means bringing servers back up via the four `scripts/serve_*.sh`.

---

## 7. Open questions

1. Should `ask` default to the core or stay agentic? Leaning core: it is the only measured path, and
   an agent that calls `code_diver_answer` still gets agentic behaviour where it helps.
2. `AnswerContextBuilder`'s `max_docs=3` / `doc_lines_per_file=120` are still on the deferred list.
   Do not tune them here.
3. Does `evaluate-search-tools` earn its keep? It is the only consumer of `agent/direct_*`.
