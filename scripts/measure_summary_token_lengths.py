#!/usr/bin/env python3
"""H-70: measure the real TOKEN length of indexed file summaries at a given char budget.

Builds the same `file_summary` items the scanner builds for the champion config
(compact budget on), applies the same char cap the embedder would apply, prefixes the
same `document_prefix`, and tokenizes with the embedder's own tokenizer. Reports the
distribution and how many samples would be truncated by the 512-token window.

    python scripts/measure_summary_token_lengths.py --budget 500 --budget 1900 --sample 200
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from code_diver.services.code_symbol_extractor import CodeSymbolExtractor  # noqa: E402
from code_diver.services.file_summary_item_builder import FileSummaryItemBuilder  # noqa: E402

MODEL = "mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ"
DOCUMENT_PREFIX = "title: none | text: "
MODEL_MAX_TOKENS = 512

INCLUDE_SUFFIXES = {
    ".java", ".kt", ".kts", ".xml", ".properties", ".gradle", ".md", ".json", ".yaml", ".yml"
}
EXCLUDE_PARTS = {
    ".idea", ".gradle", ".ijwb", "build", "out", "test", "tests", "testData",
    "testdata", "generated", "gen", ".cache", "node_modules",
}


def sample_files(root: Path, count: int, seed: int) -> list[Path]:
    candidates: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in INCLUDE_SUFFIXES:
            continue
        if EXCLUDE_PARTS & set(path.relative_to(root).parts):
            continue
        candidates.append(path)
    random.Random(seed).shuffle(candidates)
    return candidates[:count]


def percentile(values: list[int], fraction: float) -> int:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="../intellij-community")
    parser.add_argument("--sample", type=int, default=200)
    parser.add_argument("--seed", type=int, default=70)
    parser.add_argument("--budget", type=int, action="append", default=None)
    parser.add_argument("--max-symbols", type=int, default=96)
    args = parser.parse_args()
    budgets = args.budget or [500, 1900]

    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)

    root = Path(args.root).resolve()
    files = sample_files(root, args.sample, args.seed)
    print(f"root={root} sampled={len(files)} files (seed={args.seed})")

    builder = FileSummaryItemBuilder(max_symbols=args.max_symbols, compact_budget=True)
    extractor = CodeSymbolExtractor()

    summaries: list[str] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(path.relative_to(root))
        symbols = extractor.extract(rel, text)
        summaries.append(builder.build(rel, text, symbols).to_embedding_text())

    full_tokens = [
        len(tokenizer.encode(DOCUMENT_PREFIX + summary, add_special_tokens=False))
        for summary in summaries
    ]
    print(
        "\nUNCAPPED summary token length (what the builder produces before any char cap):"
        f"\n  n={len(full_tokens)} min={min(full_tokens)} median={int(statistics.median(full_tokens))}"
        f" mean={statistics.mean(full_tokens):.1f} p90={percentile(full_tokens, 0.90)}"
        f" p95={percentile(full_tokens, 0.95)} p99={percentile(full_tokens, 0.99)}"
        f" max={max(full_tokens)}"
    )
    over = sum(1 for value in full_tokens if value > MODEL_MAX_TOKENS)
    print(f"  over {MODEL_MAX_TOKENS} tokens: {over}/{len(full_tokens)} ({100 * over / len(full_tokens):.1f}%)")

    for budget in budgets:
        chars = [min(len(DOCUMENT_PREFIX + summary), budget) for summary in summaries]
        tokens = [
            len(tokenizer.encode((DOCUMENT_PREFIX + summary)[:budget], add_special_tokens=False))
            for summary in summaries
        ]
        char_truncated = sum(
            1 for summary in summaries if len(DOCUMENT_PREFIX + summary) > budget
        )
        token_truncated = sum(1 for value in tokens if value > MODEL_MAX_TOKENS)
        print(
            f"\nBUDGET max_input_chars={budget}"
            f"\n  chars   : median={int(statistics.median(chars))} p95={percentile(chars, 0.95)} max={max(chars)}"
            f"\n  tokens  : min={min(tokens)} median={int(statistics.median(tokens))}"
            f" mean={statistics.mean(tokens):.1f} p50={percentile(tokens, 0.50)}"
            f" p90={percentile(tokens, 0.90)} p95={percentile(tokens, 0.95)}"
            f" p99={percentile(tokens, 0.99)} max={max(tokens)}"
            f"\n  char-capped (content lost to the char budget): {char_truncated}/{len(summaries)}"
            f" ({100 * char_truncated / len(summaries):.1f}%)"
            f"\n  token-overflow (> {MODEL_MAX_TOKENS}, would be token-truncated): {token_truncated}/{len(tokens)}"
            f" ({100 * token_truncated / len(tokens):.1f}%)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
