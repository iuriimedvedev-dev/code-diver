# Gemma E4B Ranker Research - 2026-06-02

## Summary

We did get good quality from Gemma E4B, but only after fixing the runtime and output-contract setup.

Best current local ranker:

- Model: `mlx-community/gemma-4-e4b-it-OptiQ-4bit`
- Runtime: `mlx_lm.server`
- Chat template args: `{"enable_thinking": false}`
- Prompt mode: `hybrid_rerank_flash_lite_top20_compact`
- Max tokens: `512`
- Parser: strict JSON first, loose index-list salvage second

On the 30-case quick set it reached Hit@1 `0.667`, MRR@10 `0.747`, nDCG@10 `0.764`.
On the 100-case set it reached Hit@1 `0.620`, MRR@10 `0.701`, nDCG@10 `0.687`.

## Consolidated Results

Full generated table:

- `.code-diver/reports/local-ranker-consolidated-table.md`

Key rows:

| Dataset | Model | Strategy | Hit@1 | MRR@10 | nDCG@10 | MAP@10 | Mean ms/query | Calls | Errors |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|
| 30 | baseline hybrid | `hybrid_candidates_symbol_first` | 0.500 | 0.622 | 0.626 | 0.557 | 725 | 0 | 0 |
| 30 | `gemma4_e4b_it_4bit` old 256 | compact | 0.567 | 0.663 | 0.674 | 0.612 | 4431 | 30 | 0 |
| 30 | `gemma4_e4b_it_4bit_512` | compact | 0.600 | 0.694 | 0.688 | 0.629 | 4341 | 30 | 0 |
| 30 | `gemma4_e4b_it_4bit_thinking_compact` | compact | 0.500 | 0.605 | 0.632 | 0.564 | 11994 | 30 | 0 |
| 30 | `gemma4_e4b_it_optiq_4bit` old | compact | 0.500 | 0.605 | 0.632 | 0.564 | 7530 | 0 | 30 |
| 30 | `gemma4_e4b_it_optiq_4bit_512` | compact | 0.667 | 0.747 | 0.764 | 0.704 | 5673 | 30 | 0 |
| 30 | `gemma4_e4b_it_optiq_4bit_512` | file-first | 0.633 | 0.718 | 0.726 | 0.658 | 14696 | 30 | 0 |
| 30 | `gemma4_e4b_it_optiq_4bit_512` | precision | 0.600 | 0.705 | 0.702 | 0.630 | 12780 | 30 | 0 |
| 100 | baseline hybrid | `hybrid_candidates_symbol_first` | 0.520 | 0.633 | 0.610 | 0.537 | 348 | 0 | 0 |
| 100 | `gemma4_e4b_it_optiq_4bit_best` | compact | 0.620 | 0.701 | 0.687 | 0.622 | 5347 | 100 | 0 |

## Where We Failed

1. We treated "Gemma E4B" as one thing. It is not. Uniform 4-bit and OptiQ 4-bit behave very differently. Uniform E4B improved over baseline, but OptiQ E4B is the actual quality candidate.
2. The first Gemma OptiQ run was invalid. It had `0` successful LLM calls and `30` parse errors. That was not model quality; it was an output-contract failure.
3. We used a strict JSON-object parser only. Gemma often returns valid rank intent but not wrapped exactly as `{"results": [...]}`. The loose parser fixed this without accepting arbitrary line numbers from long prose.
4. We assumed heavier prompts would help the smarter model. They did not. File-first and precision prompts were 2-3x slower and worse than compact top20 for OptiQ.
5. Thinking mode is bad for this task right now. Uniform E4B thinking compact dropped to baseline-like quality and nearly tripled latency.
6. The 30-case quick set overstated the win. Full-100 still shows a real lift, but nDCG drops from `0.764` to `0.687`. We should optimize against 100+ cases, not celebrate 30-case spikes.

## What Worked

- OptiQ quantization: strongest quality recovery for E4B.
- `enable_thinking=false`: best for deterministic structured reranking.
- Compact top20 prompt: best quality/latency tradeoff.
- `max_tokens=512`: enough room for stable JSON/list output; better than the old 256-token run.
- Loose index-list salvage: converted Gemma's non-object outputs into usable ranked indices while keeping guardrails.

## Recommended Config

Use `configs/protogen-gemma-e4b-optiq-best-100.yml` as the current best local Gemma config.

The minimal important pieces:

```yaml
hypotheses:
  - hybrid_candidates_symbol_first
  - hybrid_rerank_flash_lite_top20_compact

generation_models:
  - name: gemma4_e4b_it_optiq_4bit_best
    runtime: mlx_lm
    model: mlx-community/gemma-4-e4b-it-OptiQ-4bit
    precision: 4bit
    quantization: optiq-4bit
    max_tokens: 512
    chat_template_args: '{"enable_thinking": false}'
```

## Next Research

1. Try `optiq serve` instead of `mlx_lm.server`; mlx-optiq docs indicate Gemma 4 OptiQ has runtime patches and KV handling that plain MLX may not fully expose.
2. Add constrained JSON/grammar decoding for local rankers. Parser salvage is useful, but constrained output is cleaner.
3. Add progressive report writing after each strategy, not only after each model. Long sweeps currently hide partial metrics until the end.
4. Test smaller compact variants: top15/top25, preview 350/600, and no file summaries. The winning mode is compact, so optimize that path.
5. Run the best Gemma profile on the larger IntelliJ dataset after the 1k dataset is ready.
