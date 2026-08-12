"""Shared refuse-to-clobber guard for report-writing scripts.

A 100-case judged baseline report (and its `.partial.json` recovery sibling) was silently
destroyed by a re-judge of an unrelated 10-case smoke run, because nothing checked whether
a script's output path already pointed at a file with real data in it. Two independent fix
rounds landed the same three symbols (`RefuseToClobberError`, `allow_overwrite_from_env()`,
`guard_against_clobber()`) directly into `scripts/rejudge_answer_report.py`,
`scripts/run_postrank_h2_benchmark.py`, and `scripts/run_postrank_h2_deterministic.py`
because the two rounds were scoped apart. This module folds all three copies into one, so
the guard idiom lives in exactly one place, alongside the sibling naming helper in
`scripts/judge_report_naming.py`.

Import mechanism: this module is dependency-light on purpose (stdlib only -- no
`code_diver` imports), so the postrank scripts, which otherwise need heavy
`code_diver.*` generation/judge dependencies, don't gain any new ones by pulling this in,
and so a bare `python -c "import ..."` in a clean interpreter can load it standing alone.
Callers load it the same way `scripts/rerun_meta_judge_failed.py` loads its sibling
`scripts/meta_judge_explainer_candidates.py`: via `importlib.util.spec_from_file_location`
keyed off `Path(__file__).resolve().parent`, rather than a flat `import clobber_guard`.
A flat import would rely on `scripts/` being on `sys.path`, which is only true when a
script is executed directly (`python scripts/foo.py` puts its own directory at
`sys.path[0]`) and is NOT true when a script is loaded the way this repo's tests load
scripts under test -- via `importlib.util.spec_from_file_location`, which does not mutate
`sys.path`. The path-based `spec_from_file_location` mechanism works unconditionally in
both cases.
"""

from __future__ import annotations

import os
from pathlib import Path


class RefuseToClobberError(RuntimeError):
    """Raised when a report write target already exists and overwriting was not requested.

    Guards every destination a run is about to write, including `.partial.json`
    (or `.partial.<ext>`) recovery siblings: the incident this class exists to prevent
    destroyed a 100-case judged baseline AND its `.partial.json` sibling with a 10-case
    re-run that happened to compute the exact same output path. Guarding only the final
    file would not have prevented it, since the partial was the only recovery path and it
    was destroyed too.
    """

    def __init__(self, path: Path) -> None:
        super().__init__(
            f"refusing to overwrite existing report: {path} "
            "(pass --allow-overwrite or set ALLOW_OVERWRITE=1 to overwrite it deliberately)"
        )
        self.path = path


def allow_overwrite_from_env() -> bool:
    """Default for `--allow-overwrite`, mirroring the `ALLOW_OVERWRITE` idiom used across
    this repo's `run_h1*.sh` scripts and the callers of this module."""
    return os.environ.get("ALLOW_OVERWRITE", "").strip().lower() not in ("", "0", "false")


def guard_against_clobber(*paths: Path | None, allow_overwrite: bool) -> None:
    """Refuse to proceed if any of `paths` already exists, unless `allow_overwrite`.

    Must be called before any write starts (including before the first partial write, and
    before any long-running work such as starting model servers or the eval subprocess),
    so a refusal never truncates or otherwise touches a pre-existing file.
    """
    if allow_overwrite:
        return
    for path in paths:
        if path is not None and path.exists():
            raise RefuseToClobberError(path)
