from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from ..domain import CodeItem
from .hybrid_item_profile import HybridItemProfile
from .hybrid_item_profiler import HybridItemProfiler


class HybridLexicalIndex:
    def __init__(self, items: Iterable[CodeItem], profiler: HybridItemProfiler):
        self.items_by_id: dict[str, CodeItem] = {}
        self.profiles: dict[str, HybridItemProfile] = {}
        self.item_ids_by_term: dict[str, set[str]] = defaultdict(set)
        for item in items:
            profile = profiler.profile(item)
            self.items_by_id[item.id] = item
            self.profiles[item.id] = profile
            for term in self._terms(profile):
                self.item_ids_by_term[term].add(item.id)

    def candidates(self, terms: tuple[str, ...]) -> list[CodeItem]:
        item_ids: set[str] = set()
        for term in terms:
            item_ids.update(self.item_ids_by_term.get(term, set()))
        return [self.items_by_id[item_id] for item_id in item_ids if item_id in self.items_by_id]

    def _terms(self, profile: HybridItemProfile) -> frozenset[str]:
        return profile.title_terms | profile.path_terms | profile.content_terms | profile.metadata_terms
