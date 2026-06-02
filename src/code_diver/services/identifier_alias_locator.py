from __future__ import annotations

import math
import re
from collections import Counter
from collections import defaultdict
from pathlib import Path

from ..domain import CodeItem, CodeItemIndexKind, CodeItemIndexKindResolver
from ..graph import CodeGraph
from .identifier_alias_candidate import IdentifierAliasCandidate
from .identifier_alias_document import IdentifierAliasDocument
from .tokenizer import tokenize

PATH_SPLIT_RE = re.compile(r"[^A-Za-z0-9]+")


class IdentifierAliasLocator:
    def __init__(self, graph: CodeGraph):
        self.documents = self._documents(graph)
        self.document_frequency = self._document_frequency(self.documents)
        self.average_length = self._average_length(self.documents)
        self.document_indexes_by_token = self._document_indexes_by_token(self.documents)

    def search(self, query: str, limit: int) -> list[IdentifierAliasCandidate]:
        query_tokens = tuple(token for token in tokenize(query) if len(token) >= 2)
        if not query_tokens or limit <= 0:
            return []
        candidate_indexes = self._candidate_indexes(query_tokens)
        if not candidate_indexes:
            return []
        scored = [
            self._score_document(document, query_tokens)
            for document in (self.documents[index] for index in candidate_indexes)
        ]
        scored = [candidate for candidate in scored if candidate.score > 0]
        scored.sort(key=lambda candidate: (candidate.score, candidate.path), reverse=True)
        return scored[:limit]

    def _score_document(
        self,
        document: IdentifierAliasDocument,
        query_tokens: tuple[str, ...],
    ) -> IdentifierAliasCandidate:
        score = 0.0
        matched: list[str] = []
        query_counter = Counter(query_tokens)
        for token, query_count in query_counter.items():
            tf = document.tokens.get(token, 0)
            if tf <= 0:
                continue
            df = self.document_frequency.get(token, 0)
            idf = math.log(1 + (len(self.documents) - df + 0.5) / (df + 0.5))
            denominator = tf + 1.2 * (1 - 0.35 + 0.35 * sum(document.tokens.values()) / max(self.average_length, 1.0))
            score += query_count * idf * ((tf * 2.2) / denominator)
            matched.append(token)
        score += self._path_exactness_score(document, query_tokens)
        score += self._alias_phrase_score(document, query_tokens, matched)
        return IdentifierAliasCandidate(
            path=document.path,
            title=document.title,
            score=score,
            matched_aliases=tuple(matched[:12]),
            preview=document.preview,
        )

    def _path_exactness_score(self, document: IdentifierAliasDocument, query_tokens: tuple[str, ...]) -> float:
        path = document.path.lower()
        basename = Path(path).stem
        score = 0.0
        for token in set(query_tokens):
            if token == basename:
                score += 6.0
            elif token in basename:
                score += 2.0
            elif f"/{token}" in path or f"{token}/" in path:
                score += 1.4
        return score

    def _alias_phrase_score(
        self,
        document: IdentifierAliasDocument,
        query_tokens: tuple[str, ...],
        matched: list[str],
    ) -> float:
        query_phrase = " ".join(query_tokens)
        score = 0.0
        for alias in document.aliases:
            alias_tokens = tuple(tokenize(alias))
            if not alias_tokens:
                continue
            alias_phrase = " ".join(alias_tokens)
            if alias_phrase and alias_phrase in query_phrase:
                score += 4.0
                matched.append(alias)
            elif query_phrase and query_phrase in alias_phrase:
                score += 3.0
                matched.append(alias)
        return score

    def _documents(self, graph: CodeGraph) -> list[IdentifierAliasDocument]:
        by_path: dict[str, list[CodeItem]] = {}
        for item in graph.items.values():
            by_path.setdefault(item.path, []).append(item)
        resolver = CodeItemIndexKindResolver()
        documents: list[IdentifierAliasDocument] = []
        for path, items in by_path.items():
            aliases = self._aliases(path, items)
            texts = [path, " ".join(aliases)]
            preview_parts: list[str] = []
            for item in sorted(items, key=lambda candidate: self._item_priority(candidate, resolver)):
                kind = resolver.resolve(item)
                if kind in {CodeItemIndexKind.FILE_MANIFEST, CodeItemIndexKind.FILE_SUMMARY, CodeItemIndexKind.SYMBOL}:
                    texts.append(item.title)
                    texts.append(item.content)
                    if len(preview_parts) < 4:
                        preview_parts.append(self._compact(item.content, 220))
            text = "\n".join(texts)
            documents.append(
                IdentifierAliasDocument(
                    path=path,
                    title=f"{path}::identifier_alias",
                    text=text,
                    tokens=Counter(token for token in tokenize(text) if len(token) >= 2),
                    aliases=tuple(aliases),
                    preview=self._compact(" ".join(preview_parts), 520),
                )
            )
        return documents

    def _aliases(self, path: str, items: list[CodeItem]) -> list[str]:
        aliases: list[str] = [path, Path(path).name, Path(path).stem]
        aliases.extend(part for part in PATH_SPLIT_RE.split(path) if len(part) >= 2)
        for item in items:
            symbol = item.metadata.get("symbol") if isinstance(item.metadata, dict) else None
            if symbol:
                aliases.append(str(symbol))
            if "::" in item.title:
                aliases.append(item.title.rsplit("::", 1)[-1])
        return self._unique(aliases)

    def _item_priority(self, item: CodeItem, resolver: CodeItemIndexKindResolver) -> int:
        kind = resolver.resolve(item)
        if kind == CodeItemIndexKind.FILE_MANIFEST:
            return 0
        if kind == CodeItemIndexKind.FILE_SUMMARY:
            return 1
        if kind == CodeItemIndexKind.SYMBOL:
            return 2
        return 3

    def _document_frequency(self, documents: list[IdentifierAliasDocument]) -> Counter[str]:
        frequency: Counter[str] = Counter()
        for document in documents:
            frequency.update(document.tokens.keys())
        return frequency

    def _document_indexes_by_token(self, documents: list[IdentifierAliasDocument]) -> dict[str, tuple[int, ...]]:
        indexes: dict[str, list[int]] = defaultdict(list)
        for index, document in enumerate(documents):
            for token in document.tokens:
                indexes[token].append(index)
        return {token: tuple(values) for token, values in indexes.items()}

    def _candidate_indexes(self, query_tokens: tuple[str, ...]) -> list[int]:
        indexes: set[int] = set()
        for token in query_tokens:
            indexes.update(self.document_indexes_by_token.get(token, ()))
        return list(indexes)

    def _average_length(self, documents: list[IdentifierAliasDocument]) -> float:
        if not documents:
            return 0.0
        return sum(sum(document.tokens.values()) for document in documents) / len(documents)

    def _unique(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        rows: list[str] = []
        for value in values:
            row = " ".join(str(value).split())
            key = row.lower()
            if not row or key in seen:
                continue
            seen.add(key)
            rows.append(row)
        return rows

    def _compact(self, text: str, limit: int) -> str:
        compact = " ".join(text.split())
        if len(compact) <= limit:
            return compact
        return compact[:limit].rstrip() + "..."
