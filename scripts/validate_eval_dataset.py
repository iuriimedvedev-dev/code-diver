from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


STOP_WORDS = {
    "and",
    "are",
    "behavior",
    "codebase",
    "configuration",
    "does",
    "for",
    "handled",
    "implemented",
    "the",
    "where",
}


@dataclass(slots=True)
class ValidationIssue:
    severity: str
    case_id: str
    message: str
    details: dict[str, Any]


class EvalDatasetValidator:
    def __init__(
        self,
        root: Path,
        max_glob_matches: int,
        path_overlap_threshold: float,
    ):
        self.root = root.resolve()
        self.max_glob_matches = max_glob_matches
        self.path_overlap_threshold = path_overlap_threshold
        self._repo_files: list[str] | None = None

    def validate(self, dataset: Path) -> dict[str, Any]:
        rows = self._load_rows(dataset)
        issues: list[ValidationIssue] = []
        issues.extend(self._dataset_shape_issues(rows))
        for row in rows:
            issues.extend(self._row_issues(row))
        return self._summary(rows, issues)

    def _load_rows(self, dataset: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for index, line in enumerate(dataset.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"Dataset row {index} must be an object.")
            rows.append(row)
        return rows

    def _dataset_shape_issues(self, rows: list[dict[str, Any]]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        seen_ids: dict[str, int] = {}
        seen_queries: dict[str, int] = {}
        for index, row in enumerate(rows, start=1):
            case_id = str(row.get("id") or f"row-{index}")
            query = self._normalize_query(str(row.get("query") or ""))
            if case_id in seen_ids:
                issues.append(
                    ValidationIssue(
                        "error",
                        case_id,
                        "duplicate case id",
                        {"first_row": seen_ids[case_id], "duplicate_row": index},
                    )
                )
            seen_ids.setdefault(case_id, index)
            if query:
                seen_queries[query] = seen_queries.get(query, 0) + 1
        duplicate_query_count = sum(count - 1 for count in seen_queries.values() if count > 1)
        if duplicate_query_count:
            issues.append(
                ValidationIssue(
                    "warning",
                    "*",
                    "duplicate normalized queries",
                    {"duplicate_query_rows": duplicate_query_count},
                )
            )
        return issues

    def _row_issues(self, row: dict[str, Any]) -> list[ValidationIssue]:
        case_id = str(row.get("id") or "")
        query = str(row.get("query") or "")
        expected = self._expected(row)
        issues: list[ValidationIssue] = []
        if not query.strip():
            issues.append(ValidationIssue("error", case_id, "empty query", {}))
        if not expected:
            issues.append(ValidationIssue("error", case_id, "empty expected list", {}))
        exact = [value for value in expected if not value.startswith("glob:")]
        globs = [value for value in expected if value.startswith("glob:")]
        if exact and globs:
            issues.append(
                ValidationIssue(
                    "warning",
                    case_id,
                    "mixed exact paths and glob alternatives",
                    {"exact_count": len(exact), "glob_count": len(globs)},
                )
            )
        for value in exact:
            if not (self.root / value).exists():
                issues.append(ValidationIssue("error", case_id, "expected path does not exist", {"path": value}))
        for value in globs:
            issues.extend(self._glob_issues(case_id, value, exact))
        overlap = self._query_path_overlap(query, expected)
        if overlap >= self.path_overlap_threshold:
            issues.append(
                ValidationIssue(
                    "warning",
                    case_id,
                    "high query/path token overlap",
                    {"overlap": round(overlap, 4), "threshold": self.path_overlap_threshold},
                )
            )
        return issues

    def _glob_issues(self, case_id: str, value: str, exact: list[str]) -> list[ValidationIssue]:
        pattern = value.removeprefix("glob:")
        matches = [path for path in self._repo_file_list() if fnmatch.fnmatchcase(path, pattern)]
        issues: list[ValidationIssue] = []
        if not matches:
            issues.append(ValidationIssue("error", case_id, "glob matches no files", {"glob": value}))
        if len(matches) > self.max_glob_matches:
            issues.append(
                ValidationIssue(
                    "warning",
                    case_id,
                    "glob matches too many files",
                    {"glob": value, "matches": len(matches), "max_glob_matches": self.max_glob_matches},
                )
            )
        overlapping_exact = [path for path in exact if fnmatch.fnmatchcase(path, pattern)]
        if overlapping_exact:
            issues.append(
                ValidationIssue(
                    "warning",
                    case_id,
                    "glob overlaps exact expected paths",
                    {"glob": value, "overlapping_exact": overlapping_exact[:10]},
                )
            )
        return issues

    def _repo_file_list(self) -> list[str]:
        if self._repo_files is None:
            self._repo_files = self._git_file_list() or [
                path.relative_to(self.root).as_posix()
                for path in self.root.rglob("*")
                if path.is_file() and ".git" not in path.relative_to(self.root).parts
            ]
        return self._repo_files

    def _git_file_list(self) -> list[str]:
        if not (self.root / ".git").exists():
            return []
        completed = subprocess.run(
            ["git", "-C", str(self.root), "ls-files"],
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            return []
        return [line for line in completed.stdout.splitlines() if line]

    def _query_path_overlap(self, query: str, expected: list[str]) -> float:
        query_tokens = set(self._tokens(query))
        if not query_tokens:
            return 0.0
        path_tokens = set(self._tokens(" ".join(expected)))
        return len(query_tokens & path_tokens) / len(query_tokens)

    def _tokens(self, text: str) -> list[str]:
        spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
        return [
            token.lower()
            for token in re.split(r"[^A-Za-z0-9]+", spaced)
            if len(token) > 1 and token.lower() not in STOP_WORDS
        ]

    def _expected(self, row: dict[str, Any]) -> list[str]:
        value = row.get("expected") or row.get("relevant") or []
        if isinstance(value, str):
            return [value]
        return [str(item) for item in value]

    def _normalize_query(self, query: str) -> str:
        return " ".join(query.lower().split())

    def _summary(self, rows: list[dict[str, Any]], issues: list[ValidationIssue]) -> dict[str, Any]:
        expected_sizes = [len(self._expected(row)) for row in rows]
        exact_paths = [
            value
            for row in rows
            for value in self._expected(row)
            if not value.startswith("glob:")
        ]
        globs = [
            value
            for row in rows
            for value in self._expected(row)
            if value.startswith("glob:")
        ]
        return {
            "rows": len(rows),
            "expected_size_mean": sum(expected_sizes) / max(len(expected_sizes), 1),
            "expected_size_max": max(expected_sizes, default=0),
            "multi_expected_rate": sum(1 for size in expected_sizes if size > 1) / max(len(expected_sizes), 1),
            "unique_exact_expected_paths": len(set(exact_paths)),
            "glob_labels": len(globs),
            "issue_counts": {
                "error": sum(1 for issue in issues if issue.severity == "error"),
                "warning": sum(1 for issue in issues if issue.severity == "warning"),
            },
            "issues": [
                {
                    "severity": issue.severity,
                    "case_id": issue.case_id,
                    "message": issue.message,
                    "details": issue.details,
                }
                for issue in issues
            ],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate code-diver JSONL evaluation datasets.")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--root", type=Path, default=Path("../intellij-community"))
    parser.add_argument("--max-glob-matches", type=int, default=100)
    parser.add_argument("--path-overlap-threshold", type=float, default=0.5)
    parser.add_argument("--fail-on-warnings", action="store_true")
    args = parser.parse_args()

    validator = EvalDatasetValidator(
        root=args.root,
        max_glob_matches=args.max_glob_matches,
        path_overlap_threshold=args.path_overlap_threshold,
    )
    summary = validator.validate(args.dataset)
    print(json.dumps(summary, indent=2, sort_keys=True))
    issue_counts = summary["issue_counts"]
    if issue_counts["error"] or (args.fail_on_warnings and issue_counts["warning"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
