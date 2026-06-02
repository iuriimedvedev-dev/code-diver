from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IdentifierAliasDocument:
    path: str
    title: str
    text: str
    tokens: Counter[str]
    aliases: tuple[str, ...]
    preview: str
