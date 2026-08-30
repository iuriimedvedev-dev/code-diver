from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..domain import CodeItem, CodeItemIndexKind, CodeItemMetadata, CodeSymbol
from .file_summary_item_builder import (
    IDENTIFIER_SPLIT_RE,
    TERM_KEYWORD_STOPWORDS,
    TERM_PATH_STOPWORDS,
    TRUNCATION_MARKER,
)

_SOURCE_SUFFIXES = frozenset({
    ".java",
    ".kt",
    ".kts",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".swift",
    ".scala",
    ".go",
    ".rs",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
})

TYPE_KINDS = frozenset({"class", "interface", "object", "enum", "record", "annotation"})
CALLABLE_KINDS = frozenset({"function", "method", "symbol"})

PRIVATE_MODIFIER_RE = re.compile(r"^\s*(?:@\w+\s+)*(?:private|protected)\b")
ACCESSOR_NAME_RE = re.compile(r"^(?:get|set|is|has)[A-Z_]")
DOC_END_RE = re.compile(r"\*/\s*$")
DOC_START_RE = re.compile(r"^\s*/\*\*?")
IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

MIN_FILE_LINES = 200
MIN_CALLABLE_LINES = 4
MAX_CHUNKS_PER_FILE = 20
MAX_CHUNK_CHARS = 500
MAX_SIGNATURE_CHARS = 160
MAX_PURPOSE_CHARS = 180
MAX_TERM_COUNT = 14
MAX_BODY_LINES_SCANNED = 60


class SymbolChunkItemBuilder:
    """Emit one dense point per meaningful top-level type and public callable of a large file.

    H-64: a file summary is a single vector for the whole file, so a query that names one
    method of a 3000-line class competes against every other topic in that file and the gold
    file drowns. Chunk-level points give each symbol its own vector while keeping `path` set
    to the full file path, so retrieval, dedup and path scoring stay file-level.

    The text follows the `file_summary_compact_budget` style: the discriminative content
    (symbol identity, then purpose) comes first, because the embedder truncates at ~500 chars.
    """

    def __init__(
        self,
        min_file_lines: int = MIN_FILE_LINES,
        max_chunks_per_file: int = MAX_CHUNKS_PER_FILE,
        max_chars: int = MAX_CHUNK_CHARS,
        min_callable_lines: int = MIN_CALLABLE_LINES,
    ):
        self.min_file_lines = min_file_lines
        self.max_chunks_per_file = max_chunks_per_file
        self.max_chars = max_chars
        self.min_callable_lines = min_callable_lines

    def build(self, rel_path: str, text: str, symbols: list[CodeSymbol]) -> list[CodeItem]:
        if not symbols or not _is_source_file(rel_path):
            return []
        lines = text.splitlines()
        if len(lines) < self.min_file_lines:
            return []
        selected = self._select(symbols, lines)
        return [self._item(rel_path, lines, symbol, enclosing) for symbol, enclosing in selected]

    def _select(
        self,
        symbols: list[CodeSymbol],
        lines: list[str],
    ) -> list[tuple[CodeSymbol, str | None]]:
        selected: list[tuple[CodeSymbol, str | None]] = []
        enclosing: str | None = None
        for symbol in symbols:
            if symbol.kind in TYPE_KINDS:
                if self._is_top_level(symbol, lines) and self._keeps_type(symbol, lines):
                    selected.append((symbol, None))
                    if len(selected) >= self.max_chunks_per_file:
                        break
                enclosing = symbol.name
                continue
            if symbol.kind not in CALLABLE_KINDS:
                continue
            if not self._keeps_callable(symbol, lines):
                continue
            selected.append((symbol, enclosing))
            if len(selected) >= self.max_chunks_per_file:
                break
        return selected

    def _is_top_level(self, symbol: CodeSymbol, lines: list[str]) -> bool:
        line = self._line(lines, symbol.start_line)
        return len(line) - len(line.lstrip()) == 0

    def _keeps_type(self, symbol: CodeSymbol, lines: list[str]) -> bool:
        return not self._is_private(self._line(lines, symbol.start_line))

    def _keeps_callable(self, symbol: CodeSymbol, lines: list[str]) -> bool:
        line = self._line(lines, symbol.start_line)
        if self._is_private(line):
            return False
        name = symbol.name.rsplit(".", 1)[-1]
        if name.startswith("_"):
            return False
        body_lines = self._body_line_count(symbol, lines)
        if ACCESSOR_NAME_RE.match(name) and body_lines <= 3:
            return False
        return body_lines >= self.min_callable_lines

    def _body_line_count(self, symbol: CodeSymbol, lines: list[str]) -> int:
        """Return the symbol's real length in lines.

        `CodeSymbolExtractor` ends a JVM symbol at "next declaration start - 1", so the last
        symbol of a file swallows every trailing line and a three-line getter can look large.
        Balancing braces from the declaration recovers the true body; languages without braces
        (Python, where the AST already reports an exact `end_lineno`) fall back to the span.
        """
        span = max(symbol.end_line - symbol.start_line + 1, 1)
        depth = 0
        opened = False
        for offset in range(span):
            line = self._line(lines, symbol.start_line + offset)
            depth += line.count("{") - line.count("}")
            opened = opened or "{" in line
            if opened and depth <= 0:
                return offset + 1
        return span

    @staticmethod
    def _is_private(line: str) -> bool:
        return bool(PRIVATE_MODIFIER_RE.match(line))

    @staticmethod
    def _line(lines: list[str], line_number: int) -> str:
        index = line_number - 1
        return lines[index] if 0 <= index < len(lines) else ""

    def _item(
        self,
        rel_path: str,
        lines: list[str],
        symbol: CodeSymbol,
        enclosing: str | None,
    ) -> CodeItem:
        start_line = max(symbol.start_line, 1)
        # The extractor's end_line runs to the next declaration, so the body terms of the last
        # symbol in a file would be read from unrelated trailing lines. Use the real body.
        end_line = min(start_line + self._body_line_count(symbol, lines) - 1, len(lines))
        content = self._content(rel_path, lines, symbol, enclosing, start_line, end_line)
        digest = hashlib.sha1(
            f"{rel_path}:symbol-chunk:{symbol.name}:{start_line}:{end_line}".encode()
        ).hexdigest()[:12]
        return CodeItem(
            id=f"{rel_path}::symbol_chunk::{symbol.name}#{digest}",
            path=rel_path,
            title=f"{rel_path}::{symbol.name}",
            content=content,
            start_line=start_line,
            end_line=end_line,
            metadata={
                CodeItemMetadata.SOURCE: "scanner",
                CodeItemMetadata.INDEX_KIND: CodeItemIndexKind.SYMBOL_CHUNK,
                CodeItemMetadata.KIND: symbol.kind,
                CodeItemMetadata.SYMBOL: symbol.name,
            },
        )

    def _content(
        self,
        rel_path: str,
        lines: list[str],
        symbol: CodeSymbol,
        enclosing: str | None,
        start_line: int,
        end_line: int,
    ) -> str:
        sections = [
            self._symbol_section(symbol, enclosing),
            self._purpose_section(lines, start_line),
            f"signature: {self._cap(symbol.signature.strip(), MAX_SIGNATURE_CHARS)}",
            self._terms_section(lines, start_line, end_line, symbol, enclosing),
            f"file: {self._file_line_value(rel_path)}",
        ]
        content = "\n".join(section for section in sections if section)
        if len(content) <= self.max_chars:
            return content
        return content[: max(self.max_chars - len(TRUNCATION_MARKER), 0)] + TRUNCATION_MARKER

    def _symbol_section(self, symbol: CodeSymbol, enclosing: str | None) -> str:
        name = symbol.name.rsplit(".", 1)[-1]
        qualified = f"{enclosing}.{name}" if enclosing else name
        words = self._words([enclosing or "", name])
        tail = f" {' '.join(words)}" if words else ""
        return f"symbol: {symbol.kind} {qualified}{tail}"

    def _purpose_section(self, lines: list[str], start_line: int) -> str:
        doc = self._preceding_doc_sentence(lines, start_line)
        if not doc:
            return ""
        return f"purpose: {self._cap(doc, MAX_PURPOSE_CHARS)}"

    def _preceding_doc_sentence(self, lines: list[str], line_number: int) -> str | None:
        end = line_number - 2
        while end >= 0 and (not lines[end].strip() or lines[end].strip().startswith("@")):
            end -= 1
        if end < 0 or not DOC_END_RE.search(lines[end]):
            return None
        start = end
        while start >= 0 and not DOC_START_RE.match(lines[start]):
            start -= 1
        if start < 0:
            return None
        doc_lines = []
        for line in lines[start : end + 1]:
            cleaned = re.sub(r"^\s*/\*\*?\s?", "", line)
            cleaned = re.sub(r"^\s*\*\s?", "", cleaned)
            cleaned = re.sub(r"\s*\*/\s*$", "", cleaned)
            if cleaned.strip():
                doc_lines.append(cleaned.strip())
        doc = " ".join(doc_lines)
        sentence = re.split(r"(?<=[.!?])\s+", doc, maxsplit=1)[0]
        return sentence or None

    def _terms_section(
        self,
        lines: list[str],
        start_line: int,
        end_line: int,
        symbol: CodeSymbol,
        enclosing: str | None,
    ) -> str:
        body = lines[start_line : min(end_line, start_line + MAX_BODY_LINES_SCANNED)]
        seen = {word for word in self._words([enclosing or "", symbol.name.rsplit(".", 1)[-1]])}
        terms: list[str] = []
        for line in body:
            for identifier in IDENTIFIER_RE.findall(line):
                for token in IDENTIFIER_SPLIT_RE.split(identifier):
                    normalized = token.lower()
                    if len(normalized) < 3 or normalized in seen or self._is_noise(normalized):
                        continue
                    seen.add(normalized)
                    terms.append(normalized)
                    if len(terms) >= MAX_TERM_COUNT:
                        return f"terms: {' '.join(terms)}"
        return f"terms: {' '.join(terms)}" if terms else ""

    def _words(self, values: list[str]) -> list[str]:
        words: list[str] = []
        seen: set[str] = set()
        for value in values:
            for token in IDENTIFIER_SPLIT_RE.split(value):
                normalized = token.lower()
                if len(normalized) < 2 or normalized in seen:
                    continue
                seen.add(normalized)
                words.append(normalized)
        return words

    @staticmethod
    def _is_noise(normalized: str) -> bool:
        if normalized.isdigit():
            return True
        if normalized in TERM_KEYWORD_STOPWORDS:
            return True
        return normalized in TERM_PATH_STOPWORDS

    @staticmethod
    def _file_line_value(rel_path: str) -> str:
        parts = Path(rel_path).parts
        return "/".join(parts[-3:])

    @staticmethod
    def _cap(line: str, limit: int) -> str:
        if len(line) <= limit:
            return line
        return line[: max(limit - len(TRUNCATION_MARKER), 0)] + TRUNCATION_MARKER


def _is_source_file(rel_path: str) -> bool:
    return Path(rel_path).suffix.lower() in _SOURCE_SUFFIXES
