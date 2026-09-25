from __future__ import annotations

import re
from pathlib import Path

from ...domain import CodeSymbol
from .base import (
    LanguageEvidence,
    StructuralSpan,
    with_preamble_span,
)


class GenericStrategy:
    name: str = "generic"
    supported_extensions: frozenset[str] = frozenset()

    _MD_EXTS = frozenset({".md", ".markdown", ".mdown", ".rst", ".txt"})
    _MARKDOWN_HEADER_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+)$")

    _GENERIC_SYMBOL_RE = re.compile(
        r"^\s*(?:export\s+)?(?:pub(?:\([^)]+\))?\s+)?(?:async\s+)?"
        r"(?:class|interface|trait|type|function|def|fn|struct|enum)\s+(?P<n1>[A-Za-z_][\w$]*)"
        r"|^\s*func\s+(?:\([^)]+\)\s+)?(?P<n2>[A-Za-z_]\w*)"
        r"|^\s*impl(?:\s*<[^>]+>)?\s+(?:[A-Za-z_]\w+\s+for\s+)?(?P<n3>[A-Za-z_]\w*)"
        r"|^\s*(?:export\s+)?const\s+(?P<n4>[A-Za-z_][\w$]*)\s*=",
        re.MULTILINE,
    )

    def extract_symbols(self, rel_path: str, text: str) -> list[CodeSymbol]:
        suffix = Path(rel_path).suffix.lower()
        if suffix in self._MD_EXTS:
            return self._extract_markdown_symbols(text)
        return self._extract_code_symbols(text)

    def extract_spans(self, rel_path: str, text: str, line_count: int) -> list[StructuralSpan]:
        suffix = Path(rel_path).suffix.lower()
        if suffix in self._MD_EXTS:
            return self._extract_markdown_spans(text, line_count)
        return self._extract_generic_spans(rel_path, text, line_count)

    def extract_evidence(self, rel_path: str, text: str) -> LanguageEvidence:
        symbols = self.extract_symbols(rel_path, text)
        declarations = [f"{s.kind} {s.name}" for s in symbols]
        doc_hints: list[str] = []

        lines = text.splitlines()
        for line in lines[:10]:
            stripped = line.strip()
            if stripped and not stripped.startswith(("//", "/*", "#", "*")):
                doc_hints.append(stripped[:120])
                break
            elif stripped.startswith(("#", "/*", "//")):
                doc_hints.append(stripped.lstrip("#/* ").strip()[:120])
                break

        return LanguageEvidence(
            package=None,
            imports=[],
            exports=[],
            declarations=declarations,
            doc_hints=doc_hints,
            companion_path=None,
        )

    def _extract_markdown_symbols(self, text: str) -> list[CodeSymbol]:
        lines = text.splitlines()
        headers: list[tuple[int, int, str]] = []  # (line_idx, level, title)
        for idx, line in enumerate(lines, start=1):
            m = self._MARKDOWN_HEADER_RE.match(line)
            if m:
                level = len(m.group("hashes"))
                title = m.group("title").strip()
                headers.append((idx, level, title))

        symbols: list[CodeSymbol] = []
        for i, (line_idx, level, title) in enumerate(headers):
            next_line = headers[i + 1][0] - 1 if i + 1 < len(headers) else len(lines)
            kind = "title" if level == 1 else "section"
            symbols.append(
                CodeSymbol(
                    name=title,
                    kind=kind,
                    start_line=line_idx,
                    end_line=max(line_idx, next_line),
                    signature=lines[line_idx - 1].strip()[:240],
                )
            )
        return symbols

    def _extract_markdown_spans(self, text: str, line_count: int) -> list[StructuralSpan]:
        symbols = self._extract_markdown_symbols(text)
        if not symbols:
            return with_preamble_span([], line_count, title="document preamble")

        spans: list[StructuralSpan] = []
        for sym in symbols:
            spans.append(
                StructuralSpan(
                    title=sym.name,
                    kind=sym.kind,
                    start_line=sym.start_line,
                    end_line=min(sym.end_line, line_count),
                )
            )

        return with_preamble_span(spans, line_count, title="document preamble")

    def _extract_code_symbols(self, text: str) -> list[CodeSymbol]:
        matches = list(self._GENERIC_SYMBOL_RE.finditer(text))
        if not matches:
            return []
        line_starts = self._line_starts(text)
        symbols: list[CodeSymbol] = []
        for index, match in enumerate(matches):
            name = next(group for group in match.groups() if group)
            start_line = self._line_for_offset(line_starts, match.start())
            next_start = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            end_line = min(self._line_for_offset(line_starts, next_start), start_line + 160)
            sig_end = text.find("\n", match.start())
            signature = text[match.start() : sig_end if sig_end != -1 else len(text)]
            symbols.append(
                CodeSymbol(
                    name=name,
                    kind="symbol",
                    start_line=start_line,
                    end_line=max(start_line, end_line),
                    signature=signature.strip()[:240],
                )
            )
        return symbols

    def _extract_generic_spans(self, rel_path: str, text: str, line_count: int) -> list[StructuralSpan]:
        symbols = self._extract_code_symbols(text)
        if not symbols:
            return with_preamble_span([], line_count)

        spans: list[StructuralSpan] = []
        for symbol in symbols:
            spans.append(
                StructuralSpan(
                    title=symbol.name,
                    kind=symbol.kind,
                    start_line=symbol.start_line,
                    end_line=min(symbol.end_line, line_count),
                )
            )

        return with_preamble_span(spans, line_count, title="file preamble")

    def _line_starts(self, text: str) -> list[int]:
        starts = [0]
        starts.extend(idx + 1 for idx, char in enumerate(text) if char == "\n")
        return starts

    def _line_for_offset(self, starts: list[int], offset: int) -> int:
        line = 1
        for idx, start in enumerate(starts, start=1):
            if start > offset:
                break
            line = idx
        return line
