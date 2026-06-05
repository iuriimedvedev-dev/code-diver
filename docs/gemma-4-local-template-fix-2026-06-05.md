# Gemma 4 Local Template Fix - 2026-06-05

## Question

Local Gemma 4 E2B/E4B looked much weaker than expected in agentic answer/search
experiments. The suspected cause was not raw model quality, but incorrect chat
template / structured-output usage.

## Finding

The local MLX `mlx_vlm.server` already applies the Gemma 4 chat template from
the model checkpoint. We should not hand-build `<|turn>...` prompts.

What we did wrong:

- used `response_format: false` as a workaround after `json_object` failures;
- therefore disabled the server's structured JSON path for local Gemma;
- then counted answer JSON parse failures as full case errors, which erased
  retrieval/context metrics and made search look worse than it was;
- gave small local rerankers candidates without an explicit path role, so tests
  and examples often outranked implementation owner files.

Correct local Gemma mode for structured tasks:

```yaml
generation:
  provider: openai_compatible
  response_format: json_schema
  extra_body:
    enable_thinking: false
```

This matches the local server behavior:

- `response_format.type=json_schema` is supported by `mlx_vlm.server`;
- `json_object` is not the right compatibility target for this runtime;
- `enable_thinking=false` keeps JSON tasks concise and avoids reasoning-channel
  leakage in structured outputs.

## Code Changes

- `OpenAICompatibleGenerationProvider` now accepts named/dict response formats:
  `json_object`, `json_schema`, `false`, or a provider-specific schema dict.
- `ConfigLoader` preserves `response_format: json_schema` instead of converting
  non-empty strings to `True`.
- local Gemma/Qwen structured benchmark configs now use `response_format:
  json_schema`.
- `AnswerEvaluator` preserves retrieval/context metrics when final answer JSON
  parsing fails.
- LLM rerank candidates now include `path_role`:
  `implementation`, `test`, `example`, `doc`, or `generated`.
- LLM rerank prompts now explicitly prefer implementation owner files over
  tests/examples/docs unless the user asks for supporting files.

## Live Smoke

Both local MLX Gemma servers returned valid JSON with the corrected request
shape:

| Server | Model | Result |
| --- | --- | --- |
| `127.0.0.1:8012` | `mlx-community/gemma-4-e2b-it-4bit` | valid JSON |
| `127.0.0.1:8013` | `mlx-community/gemma-4-e4b-it-4bit` | valid JSON |

## Qibo E2E Smoke

This is a 3-case smoke, not a final benchmark. It isolates the effect of
structured output + path-role prompting.

| Setup | File recall | File MRR | Candidate Hit@1 | Candidate Hit@5 | Context recall | Token F1 | Mean ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Gemini Lite H7 baseline | 0.722 | 1.000 | 1.000 | 1.000 | 0.722 | 0.434 | 4,694 |
| Gemma E2B before path-role fix | 0.611 | 0.161 | 0.000 | 0.667 | 0.000 | 0.171 | 9,130 |
| Gemma E2B json_schema + path_role | 0.611 | 0.694 | 0.667 | 0.667 | 0.444 | 0.208 | 21,659 |
| Gemma E4B before path-role fix | 0.611 | 0.426 | 0.333 | 0.333 | 0.333 | 0.308 | 26,868 |
| Gemma E4B json_schema + path_role | 0.611 | 0.704 | 0.667 | 0.667 | 0.444 | 0.314 | 26,621 |

## Interpretation

The old local Gemma failures were partly self-inflicted. Correct JSON Schema
serving and explicit path roles materially improve head ranking on the smoke
set.

The corrected local Gemma path is still slower and weaker than Gemini Lite on
this tiny E2E slice. The next fair test is a same-index 100-case answer/search
run with:

- H6.1 EmbeddingGemma file locator;
- Agentic query planning;
- shared final LLM rerank;
- `response_format: json_schema`;
- `path_role` candidate metadata.

Old local Gemma runs with `response_format: false` should be treated as
directional only.
