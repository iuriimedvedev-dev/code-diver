from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IdentifierAliasCandidate:
    path: str
    title: str
    score: float
    matched_aliases: tuple[str, ...]
    preview: str
