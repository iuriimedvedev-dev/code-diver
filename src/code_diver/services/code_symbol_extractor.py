from __future__ import annotations

import ast
import re
from pathlib import Path

from ..domain import CodeSymbol


class CodeSymbolExtractor:
    _GENERIC_SYMBOL_RE = re.compile(
        r"^\s*(?:export\s+)?(?:async\s+)?(?:class|interface|type|function|def|fn|struct|enum)\s+([A-Za-z_][\w$]*)"
        r"|^\s*(?:export\s+)?const\s+([A-Za-z_][\w$]*)\s*=",
        re.MULTILINE,
    )

    def extract(self, rel_path: str, text: str) -> list[CodeSymbol]:
        suffix = Path(rel_path).suffix.lower()
        if suffix == ".py":
            python_symbols = self._python_symbols(text)
            if python_symbols:
                return python_symbols
        return self._generic_symbols(text)

    def _python_symbols(self, text: str) -> list[CodeSymbol]:
        try:
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
