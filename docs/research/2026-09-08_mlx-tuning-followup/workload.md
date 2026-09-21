# MLX follow-up exact workload

This is the finite inline workload shape used for the fresh timing artifact.
It intentionally creates no source script, adapter, monkeypatch, package edit,
or service process. Run from the repository root with the already cached pinned
runtime. Choose a unique output path before running so an earlier raw artifact
is never overwritten.

```sh
OUT="docs/research/2026-09-08_mlx-tuning-followup/rerun_$(date +%Y%m%d_%H%M%S).json"
HF_HUB_CACHE="$PWD/.tmp/mlx-model-cache/huggingface" \
.tmp/mlx-runtime/bin/python - "$OUT" <<'PY'
import json, math, random, sys, time
from collections import defaultdict
from pathlib import Path
import mlx.core as mx
from mlx_lm import load

out = Path(sys.argv[1])
payload = json.loads(Path("artifacts/research/2026-09-08_metal-runtime/payloads_v2.json").read_text())
model, tokenizer, _ = load(
    "mlx-community/Qwen3-Reranker-0.6B-4bit",
    revision="5f324548f1d20c2b5a450f126fc6ef2fb1126524",
    lazy=False,
    return_config=True,
)
tok = getattr(tokenizer, "_tokenizer", tokenizer)
instruct = "Given a web search query, retrieve relevant passages that answer the query"
prefix = ("<|im_start|>system\nJudge whether the Document meets the requirements "
          "based on the Query and the Instruct provided. Note that the answer "
          "can only be \"yes\" or \"no\".<|im_end|>\n<|im_start|>user\n")
suffix = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
yes_id, no_id = (int(tok.convert_tokens_to_ids(x)) for x in ("yes", "no"))

def encode(query, document):
    middle = f"<Instruct>: {instruct}\n<Query>: {query}\n<Document>: {document}"
    return (tok.encode(prefix, add_special_tokens=False)
            + tok.encode(middle, add_special_tokens=False)
            + tok.encode(suffix, add_special_tokens=False))

def score_hidden(hidden):
    logits = model.model.embed_tokens.as_linear(hidden[:, -1:, :])
    pair = mx.stack([logits[:, 0, no_id], logits[:, 0, yes_id]], axis=-1)
    probability = mx.softmax(pair.astype(mx.float32), axis=-1)[:, 1]
    mx.eval(logits, probability); mx.synchronize()
    return [float(x) for x in probability.tolist()]

def run(sequences, mode):
    if mode == "serial":
        scores = []
        for ids in sequences:
            scores.extend(score_hidden(model.model(mx.array([ids], dtype=mx.int32))))
        return scores
    groups = defaultdict(list)
    for index, ids in enumerate(sequences):
        groups[len(ids)].append((index, ids))
    scores = [None] * len(sequences)
    for _, group in sorted(groups.items()):
        values = score_hidden(model.model(mx.array([ids for _, ids in group], dtype=mx.int32)))
        for (index, _), value in zip(group, values):
            scores[index] = value
    return scores

raw = {"seed": 43, "warmups": 2, "timed_repetitions": 7, "caps": {}}
rng = random.Random(43)
for cap, cache_bytes in (("850", 2 * 1024**3), ("2400", 1 * 1024**3)):
    query, documents = payload[cap]["query"], payload[cap]["documents"]
    sequences = [encode(query, document) for document in documents]
    mx.set_cache_limit(cache_bytes); mx.clear_cache()
    reference = run(sequences, "serial")
    conditions = ["serial", "exact_length_groups"]
    rows = []
    for phase, repeats in (("warmup", 2), ("timed", 7)):
        for repeat in range(1, repeats + 1):
            order = conditions[:]; rng.shuffle(order)
            for mode in order:
                mx.set_cache_limit(cache_bytes); mx.clear_cache()
                full0 = time.perf_counter(); tok0 = time.perf_counter()
                current = [encode(query, document) for document in documents]
                tokenization = time.perf_counter() - tok0
                gpu0 = time.perf_counter(); scores = run(current, mode)
                gpu = time.perf_counter() - gpu0
                full = time.perf_counter() - full0
                if phase == "timed":
                    delta = [b - a for a, b in zip(reference, scores)]
                    rows.append({"repeat": repeat, "mode": mode,
                                 "full_wall_seconds": full,
                                 "tokenization_seconds": tokenization,
                                 "synchronized_gpu_seconds": gpu,
                                 "finite_count": sum(math.isfinite(x) for x in scores),
                                 "max_abs_delta": max(abs(x) for x in delta)})
    raw["caps"][cap] = {"reference_scores": reference, "timed_runs": rows}
out.write_text(json.dumps(raw, indent=2) + "\n")
print(out)
PY
```

The measured run used the same token boundary for both conditions and recorded
the complete schedule, score arrays, top-10 checks, threshold checks, model and
payload hashes, and all timing fields in
`head_and_timing_raw.json`. The command above is a rerun recipe, not a claim
that exact grouping is universally faster; correctness must remain a gate.