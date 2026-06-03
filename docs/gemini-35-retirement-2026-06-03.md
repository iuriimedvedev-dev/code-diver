# Gemini 3.5 Flash Retirement Decision - 2026-06-03

## Decision

Stop using Gemini 3.5 Flash as a regular evaluation reranker/orchestrator.

Keep it only as an occasional oracle for small smoke checks, manual adjudication, or hard-tail analysis. Default full-dataset runs should use local rerankers or cheaper models.

Important: this is a cost and iteration-speed retirement, not a quality rejection. In the saved IntelliJ 1000-case data, H3 + Gemini 3.5 Flash is the strongest measured reranker by Hit@1, Hit@10, MRR, and nDCG. Treat it as the current quality ceiling and oracle baseline until another setup beats it on the same dataset.

## Why

Gemini 3.5 Flash is the best measured quality point so far, but the cost profile is not acceptable for iterative research. The strongest Gemini 3.5 run costs about 35 USD per 1000 IntelliJ cases. Several repeated runs already account for most of the measured API spend.

The current local Qwen3-Reranker 0.6B cross-encoder run is not final yet, but the 400/1000 partial already holds the target top-k quality with zero API cost:

| Setup | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | nDCG@10 | MRR@10 | Mean ms | API cost |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| H3 manifest + Gemini 3.5 Flash | 1000 | 0.871 | 0.903 | 0.943 | 0.976 | 0.964 | 0.908 | 0.898 | 6542 | $34.94 |
| H2 A grep/read + Gemini 3.5 Flash | 1000 | 0.785 | 0.868 | 0.875 | 0.882 | 0.861 | 0.820 | 0.826 | 3190 | $12.78 |
| H2 B ephemeral index + Gemini 3.5 Flash | 1000 | 0.778 | 0.858 | 0.859 | 0.869 | 0.849 | 0.810 | 0.817 | 6389 | $14.22 |
| H2 A grep/read + Gemini Flash-Lite | 1000 | 0.719 | 0.859 | 0.875 | 0.883 | 0.864 | 0.796 | 0.790 | 2851 | $2.03 |
| H2 B ephemeral index + Gemini Flash-Lite | 1000 | 0.738 | 0.845 | 0.857 | 0.866 | 0.846 | 0.792 | 0.792 | 6390 | $2.26 |
| H3 + Qwen3-Reranker 0.6B local, fast/no-cache partial | 400/1000 | 0.750 | 0.938 | 0.950 | 0.960 | 0.935 | 0.845 | 0.842 | 3831 | $0 |
| H2 A + Qwen3.5 4B local partial | 500/1000 | 0.618 | 0.794 | 0.860 | 0.890 | 0.859 | 0.736 | 0.719 | 11800 | $0 |

## Interpretation

Gemini 3.5 Flash is still the quality ceiling in the saved data, especially for Hit@1 and MRR. It remains useful as a reference point.

For iteration, it is too expensive. One H3 1000-case Gemini 3.5 run costs about the same as many local reranker sweeps. Running multiple Gemini 3.5 variants produced a large bill without changing the architectural conclusion.

The local Qwen3-Reranker 0.6B path is the current pragmatic default: it is already above the Hit@10 0.95 target on the 400-case partial, near Gemini's Hit@5, much cheaper, and faster than the expensive H3 Gemini 3.5 run.

The remaining gap is ranking sharpness, not recall:

- Gemini H3 Hit@1: 0.871
- Local H3 CE partial Hit@1: 0.750
- Gemini H3 Hit@10: 0.976
- Local H3 CE partial Hit@10: 0.960

So the next quality work should target first-position ordering and confidence calibration, not broad candidate recall.

## Cost Findings

Saved final reports sum to about 181.09 USD of estimated model cost. Naively summing partial reports gives about 236.37 USD, but that double-counts partials that correspond to final reports.

Largest final report costs:

| Run | Cost |
|---|---:|
| H3 manifest + Gemini 3.5 Flash, answer sets v2, 1000 cases | $34.94 |
| H3 union + Gemini 3.5 Flash, 1000 cases | $32.72 |
| H3 union multi + Gemini 3.5 Flash, 1000 cases | $32.71 |
| H2 B + Gemini 3.5 Flash, 1000 cases | $14.22 |
| H2 A + Gemini 3.5 Flash, 1000 cases | $12.78 |

## Go-Forward Policy

1. No Gemini 3.5 Flash full 1000-case sweeps by default.
2. Any API run over 100 cases must have an explicit budget note in the report before it starts.
3. Prefer local Qwen3-Reranker cross-encoder for full sweeps.
4. Use Gemini Flash-Lite only for cheap API comparison runs when needed.
5. Use Gemini 3.5 Flash only for small oracle checks, for example 50-100 hard cases or adjudication of disputed labels.
6. Report estimated cost, model calls, and tokens in every eval table.
7. Keep H3 Gemini 3.5 1000-case as the baseline ceiling until a local setup beats it on full 1000.

## Next Experiments

1. Finish the active H3 + Qwen3-Reranker 0.6B 1000-case run.
2. Run H3 + Qwen3-Reranker 4B using the same llama.cpp no-cache server settings.
3. Compare 0.6B vs 4B by Hit@1, Hit@5, Hit@10, MRR, nDCG, latency, and memory.
4. Add a cheap hard-tail cascade: local 0.6B first, then a stronger reranker only when confidence is low.
5. Fix the full H3 alias path by prebuilding/caching the alias index instead of constructing it from a 425MB graph artifact at eval startup.
