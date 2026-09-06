from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..reranking.hub_prior_scorer import HubPriorScorer
from .ce_meta_feature_row import CE_META_FEATURE_NAMES, CeMetaFeatureRow

_TEST_PATH_MARKERS = ("/test/", "/tests/", "/testdata/", "test/", "tests/")

_EXTENSION_JAVA = (".java",)
_EXTENSION_KT = (".kt", ".kts")
_EXTENSION_XML = (".xml",)
_EXTENSION_MD = (".md", ".markdown")


@dataclass(frozen=True, slots=True)
class CeMetaCandidate:
    """The raw per-file signals available at the CE rerank stage."""

    item_id: str
    path: str
    ce_score: float
    ce_rank: int
    base_fused_score: float
    base_fused_rank: int


class CeMetaFeatureExtractor:
    """Turns CE-stage candidates into fixed-width feature rows for the meta-ranker.

    Pure and deterministic: the same candidate list and query always produce the same
    numbers, which is what makes an exported training set replayable and what the
    inference path relies on to match the training distribution.
    """

    __slots__ = ("_hub_prior_scorer", "_path_cache")

    def __init__(self, hub_prior_scorer: HubPriorScorer | None = None) -> None:
        self._hub_prior_scorer = hub_prior_scorer or HubPriorScorer()
        # Per-batch cache of path-derived computations to avoid repeated string ops.
        self._path_cache: dict[str, dict[str, object]] = {}

    def extract(
        self,
        query: str,
        candidates: Sequence[CeMetaCandidate],
    ) -> list[CeMetaFeatureRow]:
        if not candidates:
            return []
        self._path_cache.clear()
        query_terms = self._query_terms(query)
        query_term_set = set(query_terms)
        query_term_count = float(len(query_terms))
        max_fan_in = max(
            (self._hub_prior_scorer.fan_in_degree(c.path) or 0 for c in candidates),
            default=0,
        )
        rows = [
            CeMetaFeatureRow(
                item_id=candidate.item_id,
                path=candidate.path,
                features=self._features(
                    candidate, query_terms, query_term_set, query_term_count, max_fan_in
                ),
            )
            for candidate in candidates
        ]
        return rows

    def _cached_path_data(self, path: str) -> dict[str, object]:
        cached = self._path_cache.get(path)
        if cached is not None:
            return cached
        path_lower = path.lower()
        path_terms = path_lower.replace("/", " ").replace("-", " ").replace("_", " ").split()
        dir_parts = [p for p in path_lower.split("/") if p and "." not in p]
        dir_tokens: set[str] = set()
        for part in dir_parts:
            dir_tokens.update(part.replace("-", " ").replace("_", " ").split())
        ext = self._file_extension(path)
        cached = {
            "path_lower": path_lower,
            "path_terms": path_terms,
            "dir_tokens": dir_tokens,
            "ext": ext,
            "is_test": self._is_test_path(path),
            "path_depth": path.count("/"),
            "filename_len": len(path.rsplit("/", 1)[-1]),
            "role_prior": self._hub_prior_scorer.role_prior(path),
            "fan_in": self._hub_prior_scorer.fan_in_degree(path) or 0,
        }
        self._path_cache[path] = cached
        return cached

    def _features(
        self,
        candidate: CeMetaCandidate,
        query_terms: list[str],
        query_term_set: set[str],
        query_term_count: float,
        max_fan_in: int,
    ) -> tuple[float, ...]:
        pd = self._cached_path_data(candidate.path)
        fan_in: int = pd["fan_in"]  # type: ignore[assignment]
        fan_in_prior = (
            (fan_in / max_fan_in) if max_fan_in > 0 else 0.0
        )
        role_prior: float = pd["role_prior"]  # type: ignore[assignment]
        path_lower: str = pd["path_lower"]  # type: ignore[assignment]
        lexical_overlap = (
            sum(1 for t in query_terms if t in path_lower) / query_term_count
            if query_term_count > 0
            else 0.0
        )
        dir_tokens: set[str] = pd["dir_tokens"]  # type: ignore[assignment]
        overlap = dir_tokens & query_term_set
        dir_proximity = len(overlap) / max(len(dir_tokens), 1)
        ext: str = pd["ext"]  # type: ignore[assignment]
        return (
            candidate.ce_score,
            float(candidate.ce_rank),
            fan_in_prior,
            role_prior,
            candidate.base_fused_score,
            float(candidate.base_fused_rank),
            lexical_overlap,
            float(pd["path_depth"]),
            float(pd["filename_len"]),
            1.0 if pd["is_test"] else 0.0,
            1.0 if ext == "java" else 0.0,
            1.0 if ext == "kt" else 0.0,
            1.0 if ext == "xml" else 0.0,
            1.0 if ext == "md" else 0.0,
            query_term_count,
            dir_proximity,
        )

    @staticmethod
    def _query_terms(query: str) -> list[str]:
        return [t.lower() for t in query.replace("-", " ").replace("_", " ").replace("/", " ").split() if t]

    @staticmethod
    def _file_extension(path: str) -> str:
        _, _, ext = path.rpartition(".")
        ext = ext.lower()
        if ext in ("java",):
            return "java"
        if ext in ("kt", "kts"):
            return "kt"
        if ext in ("xml",):
            return "xml"
        if ext in ("md", "markdown"):
            return "md"
        return "other"

    @staticmethod
    def _is_test_path(path: str) -> bool:
        lowered = path.lower()
        return any(marker in lowered for marker in _TEST_PATH_MARKERS)