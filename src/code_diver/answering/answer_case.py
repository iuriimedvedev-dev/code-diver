from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AnswerCase:
    id: str
    question: str
    reference: str
    expected_paths: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, row: dict[str, Any]) -> "AnswerCase":
        case_id = str(row.get("id") or row.get("case_id") or "").strip()
        question = str(row.get("question") or row.get("query") or "").strip()
        reference = str(row.get("reference") or row.get("answer") or "").strip()
        if not case_id:
            raise ValueError("AnswerCase requires id or case_id.")
        if not question:
            raise ValueError(f"AnswerCase {case_id} requires question or query.")
        if not reference:
            raise ValueError(f"AnswerCase {case_id} requires reference or answer.")
        metadata = dict(row.get("metadata") or {})
        for key in ("repo", "commit_id", "qa_type", "cluster"):
            if key in row and key not in metadata:
                metadata[key] = row[key]
        expected = [str(path) for path in row.get("expected_paths") or row.get("expected") or []]
        if not expected:
            expected = cls._extract_reference_paths(reference)
        return cls(
            id=case_id,
            question=question,
            reference=reference,
            expected_paths=expected,
            metadata=metadata,
        )

    @staticmethod
    def _extract_reference_paths(reference: str) -> list[str]:
        pattern = re.compile(r"([A-Za-z0-9_./-]+\.(?:py|java|kt|ts|tsx|js|jsx|go|rs|cpp|c|h|hpp|cs|rb|php)):")
        seen: set[str] = set()
        paths: list[str] = []
        for match in pattern.finditer(reference):
            path = match.group(1).strip("/")
            if path not in seen:
                seen.add(path)
                paths.append(path)
        return paths
