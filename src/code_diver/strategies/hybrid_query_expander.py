from __future__ import annotations

from collections.abc import Mapping


class HybridQueryExpander:
    def __init__(self, aliases: Mapping[str, list[str]]):
        self.aliases = {key.lower(): tuple(value.lower() for value in values) for key, values in aliases.items()}

    def expand(self, terms: list[str]) -> list[str]:
        expanded: list[str] = []
        seen: set[str] = set()
        for term in terms:
            self._append(expanded, seen, term)
            for alias in self.aliases.get(term, ()):
                self._append(expanded, seen, alias)
        return expanded

    def _append(self, terms: list[str], seen: set[str], value: str) -> None:
        normalized = value.lower().strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        terms.append(normalized)
