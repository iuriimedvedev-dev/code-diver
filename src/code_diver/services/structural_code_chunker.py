from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass
from pathlib import Path

from ..domain import CodeItem, CodeItemIndexKind, CodeItemMetadata
from .code_symbol_extractor import CodeSymbolExtractor


@dataclass(frozen=True, slots=True)
class StructuralSpan:
    title: str
    kind: str
    start_line: int
    end_line: int


class StructuralCodeChunker:
    def __init__(self, max_lines: int, symbol_extractor: CodeSymbolExtractor | None = None):
        self.max_lines = max_lines
        self.symbol_extractor = symbol_extractor or CodeSymbolExtractor()

    def chunk(self, rel_path: str, text: str) -> list[CodeItem]:
        lines = text.splitlines()
        if not lines:
            return []
        spans = self._spans(rel_path, text, len(lines))
        if not spans:
            return []
        items: list[CodeItem] = []
        for span in spans:
            items.extend(self._items_for_span(rel_path, lines, span))
        return items

    def _spans(self, rel_path: str, text: str, line_count: int) -> list[StructuralSpan]:
        if Path(rel_path).suffix.lower() == ".py":
            spans = self._python_spans(text, line_count)
            if spans:
                return spans
        return self._generic_spans(rel_path, text, line_count)

    def _python_spans(self, text: str, line_count: int) -> list[StructuralSpan]:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return []
        spans: list[StructuralSpan] = []
        top_level_nodes = [
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
            and getattr(node, "lineno", 0)
            and getattr(node, "end_lineno", 0)
        ]
        if top_level_nodes and int(getattr(top_level_nodes[0], "lineno")) > 1:
            spans.append(StructuralSpan("module preamble", "preamble", 1, int(getattr(top_level_nodes[0], "lineno")) - 1))
        for node in top_level_nodes:
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            spans.append(
                StructuralSpan(
                    title=str(getattr(node, "name")),
                    kind=kind,
                    start_line=int(getattr(node, "lineno")),
                    end_line=min(int(getattr(node, "end_lineno")), line_count),
                )
            )
        return self._normalized_spans(spans, line_count)

    def _generic_spans(self, rel_path: str, text: str, line_count: int) -> list[StructuralSpan]:
        symbols = self.symbol_extractor.extract(rel_path, text)
        if not symbols:
            return []
        spans: list[StructuralSpan] = []
        first_start = symbols[0].start_line
        if first_start > 1:
            spans.append(StructuralSpan("file preamble", "preamble", 1, first_start - 1))
        for symbol in symbols:
            spans.append(
                StructuralSpan(
                    title=symbol.name,
                    kind=symbol.kind,
                    start_line=max(symbol.start_line, 1),
                    end_line=min(max(symbol.end_line, symbol.start_line), line_count),
                )
            )
        return self._normalized_spans(spans, line_count)

    def _normalized_spans(self, spans: list[StructuralSpan], line_count: int) -> list[StructuralSpan]:
        normalized = [
            span
            for span in spans
            if 1 <= span.start_line <= line_count and span.end_line >= span.start_line
        ]
        normalized.sort(key=lambda span: (span.start_line, span.end_line, span.title))
        return normalized

    def _items_for_span(self, rel_path: str, lines: list[str], span: StructuralSpan) -> list[CodeItem]:
        items: list[CodeItem] = []
        for start_line in range(span.start_line, span.end_line + 1, self.max_lines):
            end_line = min(start_line + self.max_lines - 1, span.end_line)
            body = "\n".join(lines[start_line - 1 : end_line])
            if not body.strip():
                continue
            title = f"{rel_path}::{span.title}" if span.title else f"{rel_path}:{start_line}-{end_line}"
            if span.start_line != start_line or span.end_line != end_line:
                title = f"{title}:{start_line}-{end_line}"
            digest = hashlib.sha1(f"{rel_path}:{span.title}:{start_line}:{end_line}".encode("utf-8")).hexdigest()[:12]
            items.append(
                CodeItem(
                    id=f"{rel_path}::structural#{digest}",
                    path=rel_path,
                    title=title,
                    content=body,
                    start_line=start_line,
                    end_line=end_line,
                    metadata={
                        CodeItemMetadata.SOURCE: "scanner",
                        CodeItemMetadata.INDEX_KIND: CodeItemIndexKind.STRUCTURAL_CHUNK,
                        CodeItemMetadata.KIND: span.kind,
                    },
                )
            )
        return items
