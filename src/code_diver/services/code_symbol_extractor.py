from __future__ import annotations

import ast
import re
import warnings
from pathlib import Path

from ..domain import CodeSymbol


class CodeSymbolExtractor:
    _GENERIC_SYMBOL_RE = re.compile(
        r"^\s*(?:export\s+)?(?:async\s+)?(?:class|interface|type|function|def|fn|struct|enum)\s+([A-Za-z_][\w$]*)"
        r"|^\s*(?:export\s+)?const\s+([A-Za-z_][\w$]*)\s*=",
        re.MULTILINE,
    )
    _JVM_TYPE_RE = re.compile(
        r"^\s*(?:(?:public|private|protected|internal|open|final|abstract|sealed|data|value|inner|static)\s+)*"
        r"(?P<kind>class|interface|enum\s+class|enum|object|record|annotation\s+class)\s+"
        r"(?P<name>[A-Za-z_][\w$]*)"
    )
    _KOTLIN_FUNCTION_RE = re.compile(
        r"^\s*(?:(?:public|private|protected|internal|open|final|abstract|override|suspend|inline|tailrec|operator|"
        r"infix|external)\s+)*fun(?:\s*<[^>]+>)?\s+(?:(?:[A-Za-z_][\w$]*\.)+)?(?P<name>[A-Za-z_][\w$]*)\s*\("
    )
    _JAVA_METHOD_RE = re.compile(
        r"^\s*(?:(?:public|private|protected|static|final|abstract|synchronized|native|strictfp|default)\s+)*"
        r"(?:<[^>]+>\s*)?(?:[A-Za-z_][\w$<>\[\].?,]*\s+)+(?P<name>[A-Za-z_][\w$]*)\s*\("
    )
    _CONTROL_WORDS = {"if", "for", "while", "switch", "catch", "when", "return", "throw", "new"}

    def extract(self, rel_path: str, text: str) -> list[CodeSymbol]:
        suffix = Path(rel_path).suffix.lower()
        if suffix == ".py":
            python_symbols = self._python_symbols(text)
            if python_symbols:
                return python_symbols
        if suffix in {".java", ".kt", ".kts"}:
            jvm_symbols = self._jvm_symbols(text)
            if jvm_symbols:
                return jvm_symbols
        return self._generic_symbols(text)

    def _python_symbols(self, text: str) -> list[CodeSymbol]:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(text)
        except SyntaxError:
            return []
        parent_by_id = {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        symbols: list[CodeSymbol] = []
        lines = text.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            start_line = int(getattr(node, "lineno", 0) or 0)
            end_line = int(getattr(node, "end_lineno", start_line) or start_line)
            if start_line <= 0:
                continue
            parent = parent_by_id.get(id(node))
            in_class = isinstance(parent, ast.ClassDef)
            name = f"{parent.name}.{node.name}" if in_class else node.name
            kind = "class" if isinstance(node, ast.ClassDef) else "method" if in_class else "function"
            signature = lines[start_line - 1].strip() if start_line <= len(lines) else name
            symbols.append(CodeSymbol(name=name, kind=kind, start_line=start_line, end_line=end_line, signature=signature))
        symbols.sort(key=lambda symbol: (symbol.start_line, symbol.name))
        return symbols

    def _generic_symbols(self, text: str) -> list[CodeSymbol]:
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
            signature = text[match.start() : text.find("\n", match.start()) if "\n" in text[match.start() :] else len(text)]
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

    def _jvm_symbols(self, text: str) -> list[CodeSymbol]:
        lines = text.splitlines()
        matches: list[tuple[int, str, str, str]] = []
        for line_number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith(("*", "//", "/*")):
                continue
            type_match = self._JVM_TYPE_RE.match(line)
            if type_match:
                matches.append(
                    (
                        line_number,
                        self._jvm_kind(type_match.group("kind")),
                        type_match.group("name"),
                        stripped[:240],
                    )
                )
                continue
            function_match = self._KOTLIN_FUNCTION_RE.match(line)
            if function_match:
                name = function_match.group("name")
                if name not in self._CONTROL_WORDS:
                    matches.append((line_number, "function", name, stripped[:240]))
                continue
            method_match = self._JAVA_METHOD_RE.match(line)
            if method_match:
                name = method_match.group("name")
                if name not in self._CONTROL_WORDS:
                    matches.append((line_number, "method", name, stripped[:240]))
        symbols: list[CodeSymbol] = []
        for index, (line_number, kind, name, signature) in enumerate(matches):
            next_line = matches[index + 1][0] if index + 1 < len(matches) else len(lines)
            symbols.append(
                CodeSymbol(
                    name=name,
                    kind=kind,
                    start_line=line_number,
                    end_line=max(line_number, min(next_line - 1, line_number + 220)),
                    signature=signature,
                )
            )
        return symbols

    def _jvm_kind(self, raw_kind: str) -> str:
        normalized = " ".join(raw_kind.split())
        if normalized in {"enum", "enum class"}:
            return "enum"
        if normalized == "annotation class":
            return "annotation"
        return normalized

    def _line_starts(self, text: str) -> list[int]:
        starts = [0]
        starts.extend(index + 1 for index, char in enumerate(text) if char == "\n")
        return starts

    def _line_for_offset(self, starts: list[int], offset: int) -> int:
        line = 1
        for index, start in enumerate(starts, start=1):
            if start > offset:
                break
            line = index
        return line
