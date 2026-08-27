from __future__ import annotations

import logging
import math
from collections import Counter, defaultdict
from collections.abc import Iterable

from ..domain import CodeItem
from ..services.tokenizer import tokenize
from .hybrid_item_profile import HybridItemProfile
from .hybrid_item_profiler import HybridItemProfiler

logger = logging.getLogger(__name__)


class HybridLexicalIndex:
    def __init__(self, items: Iterable[CodeItem], profiler: HybridItemProfiler):
        self.items_by_id: dict[str, CodeItem] = {}
        self.profiles: dict[str, HybridItemProfile] = {}
        self.item_ids_by_term: dict[str, set[str]] = defaultdict(set)
        self.term_frequencies_by_id: dict[str, Counter[str]] = {}
        self.document_lengths_by_id: dict[str, int] = {}
        for item in items:
            profile = profiler.profile(item)
            self.items_by_id[item.id] = item
            self.profiles[item.id] = profile
            frequencies = Counter(self._weighted_tokens(item))
            self.term_frequencies_by_id[item.id] = frequencies
            self.document_lengths_by_id[item.id] = sum(frequencies.values())
            for term in self._terms(profile):
                self.item_ids_by_term[term].add(item.id)
        total_length = sum(self.document_lengths_by_id.values())
        self.average_document_length = total_length / max(len(self.document_lengths_by_id), 1)

    def candidates(self, terms: tuple[str, ...]) -> list[CodeItem]:
        item_ids: set[str] = set()
        for term in terms:
            item_ids.update(self.item_ids_by_term.get(term, set()))
        return [self.items_by_id[item_id] for item_id in item_ids if item_id in self.items_by_id]

    def _postings_as_dict(self) -> dict[str, set[str]]:
        """Convert item_ids_by_term to plain dict for native bridge."""
        return dict(self.item_ids_by_term)

    def _tf_as_dict(self) -> dict[str, dict[str, int]]:
        """Convert term_frequencies_by_id to plain dict for native bridge."""
        return {k: dict(v) for k, v in self.term_frequencies_by_id.items()}

    def _dl_as_dict(self) -> dict[str, int]:
        """Convert document_lengths_by_id to plain dict for native bridge."""
        return dict(self.document_lengths_by_id)

    def bm25_scores(self, terms: tuple[str, ...], *, k1: float, b: float) -> dict[str, float]:
        # Try native BM25 (dual-path, off by default)
        from ..native_search import try_bm25_scores

        native = try_bm25_scores(
            self._tf_as_dict(),
            self._dl_as_dict(),
            self._postings_as_dict(),
            self.average_document_length,
            list(terms),
            k1=k1,
            b=b,
        )
        if native is not None:
            return native

        # Python fallback
        item_ids = {item.id for item in self.candidates(terms)}
        scores: dict[str, float] = {}
        total_documents = max(len(self.items_by_id), 1)
        for item_id in item_ids:
            frequencies = self.term_frequencies_by_id.get(item_id, Counter())
            document_length = self.document_lengths_by_id.get(item_id, 0)
            score = 0.0
            for term in terms:
                tf = frequencies.get(term, 0)
                if tf <= 0:
                    continue
                document_frequency = len(self.item_ids_by_term.get(term, set()))
                idf = math.log(1 + (total_documents - document_frequency + 0.5) / (document_frequency + 0.5))
                denominator = tf + k1 * (1 - b + b * document_length / max(self.average_document_length, 1.0))
                score += idf * ((tf * (k1 + 1)) / denominator)
            if score > 0:
                scores[item_id] = score
        return scores

    def _terms(self, profile: HybridItemProfile) -> frozenset[str]:
        return profile.title_terms | profile.path_terms | profile.content_terms | profile.metadata_terms

    def _weighted_tokens(self, item: CodeItem) -> list[str]:
        metadata_text = " ".join(str(value) for value in item.metadata.values() if value)
        return [
            *tokenize(item.content),
            *tokenize(item.title),
            *tokenize(item.title),
            *tokenize(item.path),
            *tokenize(item.path),
            *tokenize(metadata_text),
            *tokenize(metadata_text),
        ]
