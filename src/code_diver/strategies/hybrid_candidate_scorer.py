from __future__ import annotations

from ..domain import CodeItem
from ..domain import CodeItemMetadata
from .hybrid_candidate_score import HybridCandidateScore
from .hybrid_item_profile import HybridItemProfile
from .hybrid_item_profiler import HybridItemProfiler
from .hybrid_query import HybridQuery


class HybridCandidateScorer:
    def __init__(
        self,
        query: HybridQuery,
        profiler: HybridItemProfiler | None = None,
        profiles: dict[str, HybridItemProfile] | None = None,
    ):
        self.query = query
        self.profiler = profiler or HybridItemProfiler()
        self.profiles = profiles if profiles is not None else {}

    def score(self, item: CodeItem) -> HybridCandidateScore:
        if not self.query.terms:
            return HybridCandidateScore(item=item)

        profile = self._profile(item)

        title_coverage = self._coverage(profile.title_terms)
        content_coverage = self._coverage(profile.content_terms)
        path_coverage = self._coverage(profile.path_terms)
        symbol_coverage = self._coverage(profile.metadata_terms)
        symbol_match_score = self._symbol_match_score(item, profile)

        return HybridCandidateScore(
            item=item,
            lexical_score=min(1.0, content_coverage * 0.75 + title_coverage * 0.25),
            path_score=path_coverage,
            symbol_score=symbol_coverage,
            symbol_match_score=symbol_match_score,
        )

    def _coverage(self, candidates: frozenset[str]) -> float:
        if not candidates:
            return 0.0
        matches = sum(1 for term in self.query.terms if term in candidates)
        return matches / len(self.query.terms)

    def _profile(self, item: CodeItem) -> HybridItemProfile:
        profile = self.profiles.get(item.id)
        if profile is None:
            profile = self.profiler.profile(item)
            self.profiles[item.id] = profile
        return profile

    def _symbol_match_score(self, item: CodeItem, profile: HybridItemProfile) -> float:
        symbol = str(item.metadata.get(CodeItemMetadata.SYMBOL) or "")
        if not symbol:
            return 0.0
        symbol_terms = profile.metadata_terms
        if not symbol_terms:
            return 0.0
        matches = sum(1 for term in self.query.terms if term in symbol_terms)
        if matches == 0:
            return 0.0
        return min(1.0, matches / max(min(len(symbol_terms), len(self.query.terms)), 1))
