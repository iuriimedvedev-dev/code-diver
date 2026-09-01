from __future__ import annotations

import fnmatch


class ExpectedPathMatcher:
    """Does a retrieved file path satisfy one of a case's expected entries.

    Extracted so the LTR feature export labels rows with exactly the rule the evaluation
    metrics use. A training set labelled by a second, slightly different matcher would
    teach the ranker a target the reported metrics do not measure.
    """

    def matches_any(self, path: str, expected: list[str]) -> bool:
        return any(self.matches(path, value) for value in expected)

    def matches(self, path: str, expected: str) -> bool:
        normalized = expected.strip()
        if normalized.startswith("glob:"):
            return fnmatch.fnmatchcase(path, normalized.removeprefix("glob:"))
        return path == normalized or path.startswith(normalized.rstrip("/") + "/")
