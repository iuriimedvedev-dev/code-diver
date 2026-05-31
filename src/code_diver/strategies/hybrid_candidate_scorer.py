from __future__ import annotations

from ..domain import CodeItem
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

        return HybridCandidateScore(
            item=item,
            lexical_score=min(1.0, content_coverage * 0.75 + title_coverage * 0.25),
            path_score=path_coverage,
            symbol_score=symbol_coverage,
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
