"""Pure naming helper for judged-report output paths.

`scripts/run_h14_model.sh` and `scripts/run_h16_arm.sh` each used to hand-build the judged
output filename by concatenating a handful of shell variables (model/arm label, judge
label, and a context-budget suffix) -- but never the case-count suffix that the *answer*
report filename (`$OUT`) already carries. Two runs of the same model/arm/judge at
different `--cases` values (say, a 10-case smoke test and a 100-case baseline) therefore
built the *exact same* judged-report path and the second run silently clobbered the first.
That is the incident this module fixes: a 100-case judged baseline
(`h14-qwen35-4b-answer-strict-qwen35-9b.json`) was overwritten by a 10-case smoke re-judge
because both runs computed the identical `JUDGE_OUT`.

The fix here is deliberately not "remember to also concatenate `$CASES`" -- that is exactly
the kind of manual, per-suffix bookkeeping that caused the bug and will cause the next one
the day a new suffix is added and one call site forgets it. Instead
`derive_judge_output_path()` takes the *whole* answer-report filename (which is already,
correctly, unique per case-count/budget/label -- see `$OUT` in `run_h14_model.sh` and
`run_h16_arm.sh`) and treats it as an opaque, load-bearing string: the judged filename is
that string with `-answer-strict-<judge_label>` spliced in before `.json`. Because the
entire input stem survives byte-for-byte as a prefix of the output name, the mapping is
injective by construction -- two distinct input filenames can never produce the same output
filename for the same judge label -- with no need to track, or re-derive, which suffixes
happen to be "distinguishing" today.

New convention: `<answer-report-stem>-answer-strict-<judge_label>.json`, written into a
`strict-judge/` directory that is a sibling of the answer report's own directory.

Worked examples (`answer_report` = the `$OUT` an answer-eval run already writes):
    protogen-h14-qwen35-4b-text-graph-10.json
        -> strict-judge/protogen-h14-qwen35-4b-text-graph-10-answer-strict-qwen35-9b.json
    protogen-h14-qwen35-4b-text-graph-100.json
        -> strict-judge/protogen-h14-qwen35-4b-text-graph-100-answer-strict-qwen35-9b.json
    protogen-h14-qwen35-4b-text-graph-100-cf10-cl160.json
        -> strict-judge/protogen-h14-qwen35-4b-text-graph-100-cf10-cl160-answer-strict-qwen35-9b.json

`scripts/run_h14_model.sh` and `scripts/run_h16_arm.sh` call this module (via its CLI, see
`main()` below) instead of hand-building `JUDGE_OUT`/`JUDGE_PARTIAL`, so the naming logic
lives in exactly one place.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def derive_judge_output_path(answer_report_path: Path, judge_label: str) -> Path:
    """Derive the judged-report path from an answer-report path, losslessly.

    This is a pure function of its two inputs. Because `answer_report_path.stem` is
    preserved verbatim as a prefix of the result, no two distinct answer-report filenames
    can ever derive the same judged filename for the same `judge_label` -- the case-count
    and context-budget suffixes an answer-report filename already carries survive
    automatically, without this function needing to know they exist.
    """
    if not judge_label:
        raise ValueError("judge_label must be a non-empty string")
    judge_dir = answer_report_path.parent / "strict-judge"
    return judge_dir / f"{answer_report_path.stem}-answer-strict-{judge_label}.json"


def derive_judge_partial_path(judge_output_path: Path) -> Path:
    """Derive the `.partial.json` sibling of a judged-report path.

    Mirrors the `${JUDGE_OUT%.json}.partial.json` shell idiom used across the repo's
    `run_h1*.sh` scripts, so `$JUDGE_OUT` and `$JUDGE_PARTIAL` are always in lockstep.
    """
    return judge_output_path.with_name(f"{judge_output_path.stem}.partial.json")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Print the judged-report output path (or, with --partial, its .partial.json "
            "sibling) derived from an answer-report path. Used by run_h14_model.sh and "
            "run_h16_arm.sh so the naming logic that maps an answer report to its judged "
            "report lives in exactly one place."
        )
    )
    parser.add_argument("answer_report", type=Path)
    parser.add_argument("--judge-label", required=True)
    parser.add_argument(
        "--partial",
        action="store_true",
        help="Print the .partial.json sibling of the judged-report path instead of the main path.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output = derive_judge_output_path(args.answer_report, args.judge_label)
    print(derive_judge_partial_path(output) if args.partial else output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
