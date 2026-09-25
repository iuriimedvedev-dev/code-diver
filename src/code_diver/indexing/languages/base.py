from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ...domain import CodeSymbol


@dataclass(frozen=True, slots=True)
class StructuralSpan:
    title: str
    kind: str
    start_line: int
    end_line: int


@dataclass(slots=True)
class LanguageEvidence:
    package: str | None = None
    namespace: str | None = None
    imports: list[str] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    declarations: list[str] = field(default_factory=list)
    doc_hints: list[str] = field(default_factory=list)
    companion_path: str | None = None

    def __post_init__(self) -> None:
        if self.package and not self.namespace:
            self.namespace = self.package
        elif self.namespace and not self.package:
            self.package = self.namespace


@runtime_checkable
class LanguageStrategy(Protocol):
    name: str
    supported_extensions: frozenset[str]

    def extract_symbols(self, rel_path: str, text: str) -> list[CodeSymbol]:
        ...

    def extract_spans(self, rel_path: str, text: str, line_count: int) -> list[StructuralSpan]:
        ...

    def extract_evidence(self, rel_path: str, text: str) -> LanguageEvidence:
        ...


def normalize_spans(spans: list[StructuralSpan], line_count: int) -> list[StructuralSpan]:
    normalized = [
        StructuralSpan(
            title=span.title,
            kind=span.kind,
            start_line=max(1, span.start_line),
            end_line=min(max(span.start_line, span.end_line), line_count),
        )
        for span in spans
        if 1 <= span.start_line <= line_count
    ]
    normalized.sort(key=lambda s: (s.start_line, s.end_line, s.title))
    return normalized


def with_preamble_span(
    spans: list[StructuralSpan],
    line_count: int,
    title: str = "file preamble",
) -> list[StructuralSpan]:
    if not spans:
        if line_count > 0:
            return [StructuralSpan(title, "preamble", 1, line_count)]
        return []
    first_start = spans[0].start_line
    result: list[StructuralSpan] = []
    if first_start > 1:
        result.append(StructuralSpan(title, "preamble", 1, min(first_start - 1, line_count)))
    result.extend(spans)
    return normalize_spans(result, line_count)


def find_block_end(
    lines: list[str],
    start_line: int,
    open_char: str = "{",
    close_char: str = "}",
    max_scan_lines: int = 500,
) -> int:
    """Find the closing delimiter line starting from start_line (1-indexed)."""
    depth = 0
    found_open = False
    in_single_quote = False
    in_double_quote = False
    in_block_comment = False

    limit = min(len(lines), start_line + max_scan_lines - 1)
    for idx in range(start_line - 1, limit):
        line = lines[idx]
        col = 0
        line_len = len(line)
        while col < line_len:
            char = line[col]
            # Check comment entry/exit
            if in_block_comment:
                if char == "*" and col + 1 < line_len and line[col + 1] == "/":
                    in_block_comment = False
                    col += 2
                    continue
                col += 1
                continue

            if (
                not in_single_quote
                and not in_double_quote
                and char == "/"
                and col + 1 < line_len
            ):
                next_char = line[col + 1]
                if next_char == "/":
                    # Line comment, rest of line is ignored
                    break
                if next_char == "*":
                    in_block_comment = True
                    col += 2
                    continue

            # Check quotes
            if char == '"' and not in_single_quote:
                # check escape
                escaped = col > 0 and line[col - 1] == "\\" and not (col > 1 and line[col - 2] == "\\")
                if not escaped:
                    in_double_quote = not in_double_quote
            elif char == "'" and not in_double_quote:
                escaped = col > 0 and line[col - 1] == "\\" and not (col > 1 and line[col - 2] == "\\")
                if not escaped:
                    in_single_quote = not in_single_quote

            if not in_single_quote and not in_double_quote:
                if char == open_char:
                    depth += 1
                    found_open = True
                elif char == close_char and found_open:
                    depth -= 1
                    if depth <= 0:
                        return idx + 1

            col += 1

    return min(len(lines), start_line)
