# H11 - Local Repo-Context Agent

| Field | Value |
| --- | --- |
| ID | `H11` |
| Status | active / pending eval |
| Motivation | Test whether a code-explanation agent gets better search probes and better final answers when it starts every session with compact repository orientation: layout, README facts, and markdown documentation map. |
| Assumptions | Repository context helps the LLM choose better search terms and avoid wrong architecture assumptions, while tool-verified file reads remain the source of truth for implementation claims. A stable prefix should also benefit from llama.cpp prompt cache/context checkpoints across repeated chat/search turns. |
| Index composition | No index-size change. Persistent retrieval still uses compact file-level items (`file_summary`, `file_manifest`) and the configured file graph. H11 changes only the agent system prompt prefix. |
| Search/ranking flow | User question -> Search agent sees repository context prefix -> agent calls `code_diver_search` / GraphRAG / grep / symbols / bounded reads -> optional local LLM rerank -> answer with file/line evidence. |
| Model/provider matrix | Active local chat model: Gemma 4 26B-A4B QAT GGUF through llama.cpp OpenAI-compatible chat completions on `127.0.0.1:8016`. Embedding model remains the active index model, currently Qwen3-Embedding-0.6B in `code-diver.yml` and EmbeddingGemma-300M in quality benchmark configs. API models are optional controls only. |
| Dataset | Not measured yet. Compare on repo-local generated QA, CodeSearchNet/SWE retrieval slices for search-only effects, and an end-to-end explanation/judge dataset for answer effects. |
| Metrics | Required: Hit@1/3/5/10, Recall@3/5/10, Precision@k for retrieval; answer judge score, citation correctness, unsupported-claim count for explanation; first-turn latency, follow-up latency, prompt-eval tokens/sec, generation tokens/sec, tool calls/query, degraded count. |
| Cost/latency/index-size | Index size unchanged. Local model cost is hardware time only. Initial smoke with the repo context prefix produced a roughly 5.2k-token prompt eval in about 4.8s on M3 Max and generated at about 82 tok/s. |
| Result summary | Implemented. The CLI now builds `.code-diver/context/repository-context.md` before `chat` and non-JSON `search`, and Pi receives it through `--append-system-prompt`. |
| Decision | Keep active. Do not promote until full README vs summarized README are compared against no-context on the same cases. |
| Failure modes | The agent may trust README/docs over code; README can be stale; a too-large prefix can hurt first-turn latency; context may bias search away from exact evidence; prompt cache benefits depend on runtime slot reuse and stable prompt ordering. |
| Follow-ups | Run three-way eval: `repo_context.enabled=false`, `mode=readme_summary`, `mode=full_readme`. Record cache/prompt-eval metrics from llama.cpp logs. Add a compact technology manifest extracted from package files and build configs. |
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
