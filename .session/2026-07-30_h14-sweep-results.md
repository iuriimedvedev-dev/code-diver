# H14 text-graph sweep results

## Models tested (all MLX 4-bit, 100 cases each)

| Model          | Err | Grounded | Nonempty | FabRate | Bundle | File@1 | TokF1 | JSum  | JOverall | Time   |
|----------------|-----|----------|----------|---------|--------|--------|-------|-------|----------|--------|
| gemma4-e2b     | 1   | 0.530    | 0.990    | 0.122   | 0.370  | 0.460  | 0.151 | 17.39 | 3.59     | 74s    |
| gemma4-e4b     | 0   | 0.500    | 1.000    | 0.073   | 0.350  | 0.480  | 0.141 | 18.72 | 3.84     | 90s    |
| **qwen35-4b**  | 0   | **0.720**| 1.000    | 0.054   | 0.460  | 0.560  | 0.122 | 20.30 | 4.21     | 104s   |
| qwen35-9b      | 0   | 0.700    | 1.000    | 0.042   | 0.460  | 0.570  | 0.141 | 20.52 | 4.28     | 125s   |

## Key fixes validated

1. **Schema guard** — eliminated empty responses: answer_nonempty=1.0 for all Qwen models (vs ~11% errors before)
2. **Deterministic grounding metrics** — catch fabrication patterns that citation validation missed
3. **Served-model identity** — verified on first response; caught gemma4-12b unloadable in ~30s
4. **extra_body chat_template validation** — 54 flat occurrences in configs corrected via static test

## Recommendation

**Promote qwen35-4b** — best deterministic grounding (0.720), low fabrication (0.054), fastest time (104s/case). The 9B variant adds 20% latency for negligible gain.

## Default model updated

The following operational files were updated to promote **qwen35-4b** as the default:

| File | Change |
|---|---|
| `src/code_diver/settings/defaults.py` | `GENERATION_MODEL`, `PI_MODEL`, `LOCAL_OPENAI_BASE_URL` → qwen35-4b on port 8012 |
| `code-diver.yml` | Generation + PI model → `mlx-community/Qwen3.5-4B-OptiQ-4bit`, port 8012, `response_format: json_schema`, `enable_thinking: false` |
| `scripts/run_h14_sweep.sh` | Default label order → qwen35-4b first |
| `scripts/run_h14_model.sh` | `VALID_LABELS` reordered, gemma4-12b removed |

## Follow-up

- `compare_judges.py` tool written but needs same-answers-judged-by-two-judges data (not yet collected)
- Bundle completeness (~0.35-0.46) is the primary bottleneck — retrieval, not generation
