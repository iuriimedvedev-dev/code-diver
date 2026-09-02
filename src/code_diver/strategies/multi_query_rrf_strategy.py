from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol

from ..config.multi_query_config import MultiQueryConfig
from ..domain import SearchResult
from .retrieval_strategy import RetrievalStrategy

logger = logging.getLogger(__name__)

QUERY_ALIASES = {
    "go to declaration": "navigate to declaration",
    "find usages": "usage search",
    "find in path": "search in files",
    "search everywhere": "SearchEverywhere",
    "quick documentation": "quick doc",
    "live template": "template expansion",
    "intention actions": "intention quick fix",
    "tool window": "toolwindow",
    "version control": "vcs",
    "code folding": "collapse regions",
    "refactoring": "refactor",
    "implemented": "implementation",
    "managed": "management",
    "handled": "handling",
    "registered": "registration",
    "executed": "execution",
    "coordinated": "coordination",
    "created": "creation",
    "detected": "detection",
    "collected": "collection",
    "rename": "rename refactor",
    "settings": "options",
    "keymap": "keyboard shortcut",
    "completion": "code completion lookup",
    "inspections": "inspection highlighting",
    "debugger": "debug",
    "breakpoints": "breakpoint",
    "vcs": "version control",
    "terminal": "console terminal",
    "notification": "notification balloon",
    "indexing": "index dumb mode",
    "diff": "compare diff",
}

# Interrogative scaffolding stripped by statement normalization: question word,
# optional auxiliary, optional "i find", optional article.
_QUESTION_PREFIX = re.compile(
    r"^(?:where|how|what|which|who|why|when)\s+"
    r"(?:is|are|was|were|does|do|did|can|could|should|would|will)?\s*"
    r"(?:i\s+find\s+)?(?:the\s+|a\s+|an\s+)?",
    re.IGNORECASE,
)
_TRAILING_SCOPE = re.compile(r"\s+in the (?:codebase|code|project|ide)\s*$", re.IGNORECASE)
# Filler and generic verbs dropped before guessing a camelCase symbol from content words.
_SYMBOL_STOP_WORDS = {
    "a", "an", "and", "are", "can", "code", "does", "do", "find", "for", "how",
    "in", "is", "me", "of", "on", "project", "show", "the", "to", "what", "where",
    "which", "why", "with", "you",
    "collected", "coordinated", "created", "detected", "displayed", "done", "executed",
    "handled", "happen", "happens", "implemented", "managed", "registered", "shown",
    "supported", "used",
}


class MultiQueryVariantGenerator:
    def variants(self, query: str, max_variants: int) -> list[str]:
        if not query.strip():
            return []
        statement = self._statement(query)
        candidates = [query.strip(), statement, self._aliased(statement), self._symbol_guess(statement)]
        result: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            candidate = candidate.strip()
            key = candidate.casefold()
            if candidate and key not in seen:
                seen.add(key)
                result.append(candidate)
            if len(result) >= max(1, max_variants):
                break
        return result

    def _statement(self, query: str) -> str:
        statement = query.strip().rstrip("?").strip()
        statement = _QUESTION_PREFIX.sub("", statement)
        return _TRAILING_SCOPE.sub("", statement).strip()

    def _aliased(self, statement: str) -> str:
        result = statement
        for source, target in sorted(QUERY_ALIASES.items(), key=lambda pair: len(pair[0]), reverse=True):
            result = re.sub(rf"\b{re.escape(source)}\b", target, result, flags=re.IGNORECASE)
        return result

    def _symbol_guess(self, statement: str) -> str:
        """camelCase symbol guess: "extract method refactoring" -> "ExtractMethodRefactoring"."""
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_]*", statement)
        tokens = [token for token in tokens if token.casefold() not in _SYMBOL_STOP_WORDS]
        if len(tokens) < 2:
            return ""
        return "".join(token[:1].upper() + token[1:] for token in tokens[:4])


class QueryRewriter(Protocol):
    def rewrite(self, query: str, max_variants: int) -> list[str]:
        ...


class LlmQueryRewriter:
    def __init__(self, generation_provider: Any):
        self.generation_provider = generation_provider

    def rewrite(self, query: str, max_variants: int) -> list[str]:
        schema = {
            "type": "object",
            "properties": {"variants": {"type": "array", "items": {"type": "string"}}},
            "required": ["variants"],
            "additionalProperties": False,
        }
        prompt = f"Rewrite this code search query into up to {max_variants} distinct queries: {query}"
        try:
            response = self.generation_provider.generate_json(prompt, schema=schema)
            values = json.loads(response).get("variants", [])
            return [str(value) for value in values if isinstance(value, str)] if isinstance(values, list) else []
        except Exception:
            logger.warning("LLM multi-query rewrite failed", exc_info=True)
            return []


class MultiQueryRrfStrategy(RetrievalStrategy):
    def __init__(
        self,
        underlying: RetrievalStrategy,
        config: MultiQueryConfig,
        generator: MultiQueryVariantGenerator | None = None,
        llm_rewriter: QueryRewriter | None = None,
        fusion_pool_size: int | None = None,
    ):
        self.underlying = underlying
        self.config = config
        self.generator = generator or MultiQueryVariantGenerator()
        self.llm_rewriter = llm_rewriter
        self.fusion_pool_size = fusion_pool_size

    def search(self, query: str, limit: int) -> list[SearchResult]:
        effective_limit = (
            max(limit, self.fusion_pool_size)
            if self.fusion_pool_size is not None
            else limit
        )
        variants = self._variants(query)
        if len(variants) <= 1:
            results = self.underlying.search(query, effective_limit)
            return results[:effective_limit] if self.fusion_pool_size is not None else results
        return self._fuse(self._run(variants, effective_limit), limit)

    def _variants(self, query: str) -> list[str]:
        variants = self.generator.variants(query, self.config.max_variants)
        if (
            self.config.llm_rewrites_enabled
            and self.llm_rewriter is not None
            and len(variants) < max(1, self.config.max_variants)
        ):
            variants.extend(self.llm_rewriter.rewrite(query, self.config.max_variants))
        result: list[str] = []
        seen: set[str] = set()
        for variant in variants:
            key = variant.strip().casefold()
            if key and key not in seen:
                seen.add(key)
                result.append(variant.strip())
            if len(result) >= max(1, self.config.max_variants):
                break
        return result

    def _run(self, variants: list[str], limit: int) -> list[list[SearchResult]]:
        if self.config.parallel_variants:
            with ThreadPoolExecutor(max_workers=max(1, self.config.max_variant_workers)) as executor:
                return list(executor.map(lambda variant: self.underlying.search(variant, limit), variants))
        return [self.underlying.search(variant, limit) for variant in variants]

    def _fuse(self, ranked_lists: list[list[SearchResult]], limit: int) -> list[SearchResult]:
        """Path-level RRF: score(f) = sum(w_i / (rrf_k + rank_i(f))), variant 0 is the original query."""
        scores: dict[str, float] = {}
        representatives: dict[str, SearchResult] = {}
        for index, results in enumerate(ranked_lists):
            weight = self.config.original_query_weight if index == 0 else 1.0
            seen_paths: set[str] = set()
            rank = 0
            for result in results:
                path = result.item.path
                if path in seen_paths:
                    continue
                seen_paths.add(path)
                rank += 1
                representatives.setdefault(path, result)
                scores[path] = scores.get(path, 0.0) + weight / (self.config.rrf_k + rank)
        ordered = sorted(scores, key=lambda path: (scores[path], representatives[path].score, path), reverse=True)
        pool_size = self.fusion_pool_size if self.fusion_pool_size is not None else limit
        return [SearchResult(representatives[path].item, scores[path] + representatives[path].score * 1e-9) for path in ordered[:pool_size]]
