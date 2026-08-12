from __future__ import annotations

import ast
import hashlib
import re
import warnings
from pathlib import Path

from ..domain import CodeItem, CodeItemIndexKind, CodeItemMetadata, CodeSymbol

COMMENT_LINE_RE = re.compile(r"^\s*(?:#|//+|/\*+|\*+|--)\s?(?P<comment>.*)$")
STRING_LITERAL_RE = re.compile(r"(?P<quote>['\"])(?P<value>[^'\"]{4,180})(?P=quote)")
IDENTIFIER_SPLIT_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|[^A-Za-z0-9]+")
BEHAVIOR_LINE_RE = re.compile(
    r"\b(return|yield|raise|throw|except|catch|if|elif|else|switch|case|when|match|for|while|await)\b",
    re.IGNORECASE,
)
EFFECT_LINE_RE = re.compile(
    r"\b("
    r"auth|token|jwt|permission|login|password|credential|"
    r"request|response|http|https|api|client|url|uri|"
    r"sql|query|database|session|transaction|cache|queue|event|"
    r"file|path|read|write|stream|upload|download|"
    r"config|setting|env|option|feature|flag"
    r")\b",
    re.IGNORECASE,
)


class FileBodyEvidenceItemBuilder:
    def __init__(
        self,
        max_symbols: int = 96,
        max_terms: int = 140,
        max_comments: int = 28,
        max_strings: int = 36,
        max_behavior_lines: int = 32,
        max_effect_lines: int = 32,
        max_line_chars: int = 180,
    ):
        self.max_symbols = max_symbols
        self.max_terms = max_terms
        self.max_comments = max_comments
        self.max_strings = max_strings
        self.max_behavior_lines = max_behavior_lines
        self.max_effect_lines = max_effect_lines
        self.max_line_chars = max_line_chars

    def build(self, rel_path: str, text: str, symbols: list[CodeSymbol]) -> CodeItem:
        digest = hashlib.sha1(
            f"{rel_path}:file-body-evidence".encode()
        ).hexdigest()[:12]
        comments = self._comments(text)
        string_hints = self._string_hints(rel_path, text)
        behavior_lines = self._matching_lines(
            text, BEHAVIOR_LINE_RE, self.max_behavior_lines
        )
        effect_lines = self._matching_lines(text, EFFECT_LINE_RE, self.max_effect_lines)
        evidence_terms = self._evidence_terms(
            rel_path, symbols, comments, string_hints, behavior_lines, effect_lines
        )
        content = "\n".join(
            [
                f"file: {rel_path}",
                f"filename: {Path(rel_path).name}",
                f"extension: {Path(rel_path).suffix.lower()}",
                self._terms_section("body_terms", evidence_terms, self.max_terms),
                self._rows_section("comments", comments, self.max_comments),
                self._rows_section("strings", string_hints, self.max_strings),
                self._rows_section(
                    "behavior_lines", behavior_lines, self.max_behavior_lines
                ),
                self._rows_section("effect_lines", effect_lines, self.max_effect_lines),
            ]
        ).strip()
        return CodeItem(
            id=f"{rel_path}::file_body_evidence#{digest}",
            path=rel_path,
            title=f"{rel_path}::file_body_evidence",
            content=content,
            metadata={
                CodeItemMetadata.SOURCE: "scanner",
                CodeItemMetadata.INDEX_KIND: CodeItemIndexKind.FILE_BODY_EVIDENCE,
            },
        )

    def _comments(self, text: str) -> list[str]:
        rows: list[str] = []
        for line in text.splitlines():
            match = COMMENT_LINE_RE.match(line)
            if not match:
                continue
            comment = self._compact_line(match.group("comment").strip(" */"))
            if comment:
                rows.append(comment)
        return self._unique_rows(rows)[: self.max_comments]

    def _string_hints(self, rel_path: str, text: str) -> list[str]:
        suffix = Path(rel_path).suffix.lower()
        if suffix == ".py":
            tree = self._python_tree(text)
            if tree is not None:
                values = [
                    self._compact_line(node.value)
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Constant) and isinstance(node.value, str)
                ]
                return self._unique_rows(
                    value for value in values if self._useful_string(value)
                )[: self.max_strings]
        values = [
            self._compact_line(match.group("value"))
            for match in STRING_LITERAL_RE.finditer(text)
        ]
        return self._unique_rows(
            value for value in values if self._useful_string(value)
        )[: self.max_strings]

    def _matching_lines(
        self, text: str, pattern: re.Pattern[str], limit: int
    ) -> list[str]:
        rows: list[str] = []
        for line in text.splitlines():
            stripped = " ".join(line.strip().split())
            if not stripped or not pattern.search(stripped):
                continue
            rows.append(self._compact_line(stripped))
            if len(rows) >= limit * 3:
                break
        return self._unique_rows(rows)[:limit]

    def _evidence_terms(
        self,
        rel_path: str,
        symbols: list[CodeSymbol],
        comments: list[str],
        string_hints: list[str],
        behavior_lines: list[str],
        effect_lines: list[str],
    ) -> list[str]:
        values = [rel_path, Path(rel_path).stem, *Path(rel_path).parts]
        for symbol in symbols[: self.max_symbols]:
            values.extend([symbol.name, symbol.signature])
        values.extend(comments)
        values.extend(string_hints)
        values.extend(behavior_lines)
        values.extend(effect_lines)
        return self._unique_terms(values)[: self.max_terms]

    def _terms_section(self, label: str, terms: list[str], limit: int) -> str:
        rows = terms[:limit]
        return f"{label}: {' '.join(rows) if rows else 'none'}"

    def _rows_section(self, label: str, rows: list[str], limit: int) -> str:
        selected = rows[:limit]
        if not selected:
            return f"{label}: none"
        return f"{label}:\n" + "\n".join(f"- {row}" for row in selected)

    def _python_tree(self, text: str) -> ast.AST | None:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                return ast.parse(text)
        except SyntaxError:
            return None

    def _useful_string(self, value: str) -> bool:
        stripped = value.strip()
        if len(stripped) < 4:
            return False
        if stripped.isspace():
            return False
        return len(set(stripped)) >= 3

    def _compact_line(self, value: str) -> str:
        return " ".join(value.split())[: self.max_line_chars]

    def _unique_terms(self, values: list[str]) -> list[str]:
        terms: list[str] = []
        seen: set[str] = set()
        for value in values:
            for token in IDENTIFIER_SPLIT_RE.split(value):
                normalized = token.lower()
                if len(normalized) < 2 or normalized in seen:
                    continue
                seen.add(normalized)
                terms.append(normalized)
        return terms

    def _unique_rows(self, rows: list[str]) -> list[str]:
        seen: set[str] = set()
        unique_rows: list[str] = []
        for row in rows:
            normalized = row.strip()
            key = normalized.lower()
            if not normalized or key in seen:
                continue
            seen.add(key)
            unique_rows.append(normalized)
        return unique_rows
