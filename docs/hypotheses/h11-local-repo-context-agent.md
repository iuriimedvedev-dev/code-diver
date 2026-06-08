# H11 - Local Repo-Context Agent

| Field | Value |
| --- | --- |
| ID | `H11` |
| Status | active / measured on small H7 slice / graph smoke-tested |
| Motivation | Test whether a code-explanation agent gets better search probes and better final answers when it starts every session with compact repository orientation: layout, README facts, and markdown documentation map. |
| Assumptions | Repository context helps the LLM choose better search terms and avoid wrong architecture assumptions, while tool-verified file reads remain the source of truth for implementation claims. A stable prefix should also benefit from llama.cpp prompt cache/context checkpoints across repeated chat/search turns. |
| Index composition | No index-size change. Persistent retrieval still uses compact file-level items (`file_summary`, `file_manifest`) and the configured file graph. H11 changes only the agent system prompt prefix. |
| Search/ranking flow | User question -> Search agent sees repository context prefix -> agent calls `code_diver_search` / GraphRAG / grep / symbols / bounded reads -> optional local LLM rerank -> answer with file/line evidence. |
| Model/provider matrix | Active local chat model: Gemma 4 26B-A4B QAT GGUF through llama.cpp OpenAI-compatible chat completions on `127.0.0.1:8016`. Embedding model remains the active index model, currently Qwen3-Embedding-0.6B in `code-diver.yml` and EmbeddingGemma-300M in quality benchmark configs. API models are optional controls only. |
| Dataset | Not measured yet. Compare on repo-local generated QA, CodeSearchNet/SWE retrieval slices for search-only effects, and an end-to-end explanation/judge dataset for answer effects. |
| Metrics | Required: Hit@1/3/5/10, Recall@3/5/10, Precision@k for retrieval; answer judge score, citation correctness, unsupported-claim count for explanation; first-turn latency, follow-up latency, prompt-eval tokens/sec, generation tokens/sec, tool calls/query, degraded count. |
| Cost/latency/index-size | Index size unchanged. Local model cost is hardware time only. Initial naive `-np 2` smoke with the repo context prefix reprocessed the long prompt on later turns. Cache benchmark showed the tuned Gemma/SWA config (`-np 1 --swa-full -no-kvu --cache-reuse 1024`) reduced the second stable-prefix prompt eval to `65 ms / 17 tokens` with `forced_reprocess_count=0`. |
| Result summary | Implemented. The CLI now builds `.code-diver/context/repository-context.md` before `chat` and non-JSON `search`, and `evaluate-answers` can inject the same repository orientation into LLM query planning and final answer generation. Local Gemma 4 26B-A4B smoke on `../protogen` correctly answered where team builder is managed (`src/team_builder/`, `src/api/routes/team_builder.py`, `frontend/src/app/features/team-builder/`). H7 six-case A/B showed better rank-1/MRR with README-summary context, but unchanged recall/precision. H8/H10 context variants were one-case smoke-tested only. |
| Decision | Keep active. Do not promote as a quality default yet. Promote the implementation hook, but require a larger answer dataset before claiming context improves answer quality. |
| Failure modes | The agent may trust README/docs over code; README can be stale; a too-large prefix can hurt first-turn latency; context may bias search away from exact evidence; prompt cache benefits depend on runtime slot reuse and stable prompt ordering. |
| Follow-ups | Run three-way eval: `repo_context.enabled=false`, `mode=readme_summary`, `mode=full_readme`. Record cache/prompt-eval metrics from llama.cpp logs. Add a compact technology manifest extracted from package files and build configs. Test parallelism with multiple single-slot llama-server workers instead of `-np > 1` inside one Gemma/SWA server. |
| Links | `.pi/prompts/code-diver-rag.md`, `src/code_diver/pi/repository_context_builder.py`, `src/code_diver/pi/pi_command_builder.py`, `code-diver.yml` |

## Variants

| Variant | Context source | Expected tradeoff |
| --- | --- | --- |
| `H11.0 no-context` | Existing system prompt only. | Fastest first turn, weakest repository orientation. |
| `H11.1 readme_summary` | Top-level layout, README fact summary, limited markdown documentation map. | Best default candidate: small enough for repeated sessions, preserves exact headings/commands/facts. |
| `H11.2 full_readme` | Top-level layout, full README, limited markdown documentation map. | More facts, but higher first-turn prompt cost and more stale/noisy prose. |

## KV-Cache Protocol

The stable prefix should be ordered as:

```text
base Search agent prompt
-> generated repository context
-> user question
-> tool calls and answers
```

This keeps the high-token prefix stable across sessions. For llama.cpp, the useful
runtime signals are prompt eval time, context checkpoints, slot reuse, and token
reuse/cached-prefix logs. The metric target is not just lower latency; the agent
must also preserve citation quality by verifying claims with read-only tools.

## Current Cache Finding

The original server flags used `-np 2 --cache-prompt --cache-reuse 256`. On the
tested llama.cpp build this produced repeated `forcing full prompt re-processing`
warnings with Gemma 4 26B-A4B. The working local policy is:

```bash
llama-server \
  -m .code-diver/models/gemma-4-26b-a4b-it-qat-GGUF/gemma-4-26B-A4B-it-qat-UD-Q4_K_XL.gguf \
  --host 127.0.0.1 \
  --port 8016 \
  --api-key local \
  -c 32768 \
  -np 1 \
  --cache-prompt \
  --cache-reuse 1024 \
  --swa-full \
  -no-kvu \
  --ctx-checkpoints 512 \
  --checkpoint-min-step 64 \
  --cache-ram -1 \
  --jinja \
  --slots
```

Measured cache benchmark:

| Config | First prompt eval | Second prompt eval | Forced reprocess |
| --- | ---: | ---: | ---: |
| `-np 1 --swa-full -no-kvu` | `3519 ms / 3145 tokens` | `65 ms / 17 tokens` | `0` |
| `-np 1 --swa-full` | `2779 ms / 3145 tokens` | `64 ms / 17 tokens` | `0` |

The practical default keeps `-no-kvu` because it avoids the Gemma/SWA unified-KV
failure mode seen in the earlier long prompt logs. The tradeoff is lower
in-process parallelism; concurrency should come from several single-slot workers
or a separate serving backend, not `-np 2+` for this model.

## Current Evidence

What is tested:

- repository-context construction before `chat`/non-JSON `search`;
- repository-context injection into `evaluate-answers` query planning and answer
  prompts;
- local Gemma 4 26B-A4B llama.cpp runtime with prompt cache enabled;
- one live `../protogen` smoke query through the user-facing CLI;
- stable-prefix cache reuse on synthetic repeated prompts.
- H7 no-context vs README-summary on six Protogen answer cases, same local
  Gemma 4 26B model, same Qwen3 0.6B embedding index, same final LLM rerank.
- H8/H10 graph variants as one-case smoke, same local Gemma 4 26B model.

What is not tested yet:

- full-README A-B answer quality;
- AI-judge explanation scores;
- unsupported-claim rate;
- H8/H10 full six-case or larger A-B quality;
- whether repo context helps enough to justify the added first-turn prompt cost.

Decision: H11 is usable as the local chat default, but it is not yet promoted as
a measured quality improvement. The next eval must compare the three context
variants on the same question set and judge answers with file/line evidence.

## Protogen H7 A/B - 2026-06-08

Dataset:

- `datasets/protogen_answer_cases_6.jsonl`;
- six repository-local code-exploration questions;
- local Gemma 4 26B-A4B for query planning, final candidate rerank, and answer
  generation;
- Qwen3-Embedding-0.6B local file-metadata index;
- correct product flow: LLM planned queries -> deterministic hybrid probe
  search -> one shared Gemma rerank -> bounded file reads -> Gemma answer.

Important runtime fix:

- For llama.cpp Gemma structured JSON tasks, `extra_body.enable_thinking=false`
  is not sufficient.
- The working setting is:

```yaml
generation:
  response_format: json_schema
  extra_body:
    chat_template_kwargs:
      enable_thinking: false
```

Without `chat_template_kwargs`, Gemma produced visible reasoning instead of
planner JSON and the eval either failed JSON parsing or spent the full output
budget.

| Setup | Cases | Context | File Hit | Hit@1 | File Recall | Context Recall | File MRR | Mean ms |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| H7 + Gemma 26B | 6 | none | 0.667 | 0.333 | 0.625 | 0.625 | 0.500 | 117403 |
| H7 + Gemma 26B | 6 | README summary, 10820 chars | 0.667 | 0.500 | 0.625 | 0.625 | 0.583 | 111234 |

Interpretation:

- README-summary context helped ranking quality on this small slice: Hit@1
  improved from `0.333` to `0.500`, and MRR improved from `0.500` to `0.583`.
- Recall and precision did not move, so context did not expand the answerable
  file set. It mostly helped order candidates.
- The sample is too small for a quality claim. Treat this as a positive signal
  and an integration check.
- Cold retrieval/profile construction dominated the first case. Larger runs
  should either prewarm the hybrid cache or report cold-start and warm latency
  separately.

## Graph Variant Smoke - 2026-06-08

All rows below are one-case smoke checks using the same team-builder question and
local Gemma 4 26B model. They prove H11 composes with graph search, not that graph
context is better.

| Setup | Context | File Hit | File Recall | Context Recall | File MRR | Mean ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| H8 hybrid graph-signal | none | 1.000 | 0.750 | 0.750 | 1.000 | 119847 |
| H8 hybrid graph-signal | README summary | 1.000 | 0.750 | 0.750 | 1.000 | 162594 |
| H10 graph-file | none | 1.000 | 0.750 | 0.750 | 1.000 | 94257 |
| H10 graph-file | README summary | 1.000 | 0.750 | 0.750 | 1.000 | 175010 |

Decision from this smoke: graph strategies are compatible with H11, but the
single-case graph/context rows are not decision-grade. The next graph eval should
run after cache prewarming and should compare H7/H8/H10 on the same multi-case
answer set.
