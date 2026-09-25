from __future__ import annotations

import re
from pathlib import Path

from ...domain import CodeSymbol
from .base import (
    LanguageEvidence,
    StructuralSpan,
    find_block_end,
    with_preamble_span,
)


class GoStrategy:
    name: str = "go"
    supported_extensions: frozenset[str] = frozenset({".go"})

    _PACKAGE_RE = re.compile(r"^\s*package\s+(?P<pkg>[A-Za-z_]\w*)")
    _SINGLE_IMPORT_RE = re.compile(r'^\s*import\s+"(?P<imp>[^"]+)"')
    _TYPE_RE = re.compile(
        r"^\s*type\s+(?P<name>[A-Za-z_]\w*)(?:\[[^\]]+\])?\s+(?P<kind>struct|interface)\b"
    )
    _TYPE_ALIAS_RE = re.compile(
        r"^\s*type\s+(?P<name>[A-Za-z_]\w*)(?:\[[^\]]+\])?\s+(?P<alias>[^\s{]+)"
    )
    _METHOD_RE = re.compile(
        r"^\s*func\s*\(\s*(?:(?P<recv_var>\w+)\s+)?(?:\*)?(?P<recv_type>[A-Za-z_]\w*)\s*\)\s*(?P<name>[A-Za-z_]\w*)\s*(?:\[[^\]]+\])?\s*\("
    )
    _FN_RE = re.compile(
        r"^\s*func\s+(?P<name>[A-Za-z_]\w*)\s*(?:\[[^\]]+\])?\s*\("
    )

    def extract_symbols(self, rel_path: str, text: str) -> list[CodeSymbol]:
        lines = text.splitlines()
        symbols: list[CodeSymbol] = []

        in_type_block = False

        for line_idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith(("//", "/*", "*")):
                continue

            if stripped == "type (" or stripped.startswith("type ("):
                in_type_block = True
                continue
            if in_type_block:
                if stripped == ")":
                    in_type_block = False
                    continue
                # Match inside type block
                block_match = re.match(
                    r"^\s*(?P<name>[A-Za-z_]\w*)(?:\[[^\]]+\])?\s+(?P<kind>struct|interface)\b",
                    line,
                )
                if block_match:
                    name = block_match.group("name")
                    kind = block_match.group("kind")
                    end_line = self._calculate_end_line(lines, line_idx)
                    symbols.append(
                        CodeSymbol(
                            name=name,
                            kind=kind,
                            start_line=line_idx,
                            end_line=end_line,
                            signature=stripped[:240],
                        )
                    )
                    continue

            # Method: func (r *Receiver) Method()
            method_match = self._METHOD_RE.match(line)
            if method_match:
                recv_type = method_match.group("recv_type")
                method_name = method_match.group("name")
                name = f"{recv_type}.{method_name}"
                end_line = self._calculate_end_line(lines, line_idx)
                symbols.append(
                    CodeSymbol(
                        name=name,
                        kind="method",
                        start_line=line_idx,
                        end_line=end_line,
                        signature=stripped[:240],
                    )
                )
                continue

            # Free function: func Name()
            fn_match = self._FN_RE.match(line)
            if fn_match:
                name = fn_match.group("name")
                end_line = self._calculate_end_line(lines, line_idx)
                symbols.append(
                    CodeSymbol(
                        name=name,
                        kind="function",
                        start_line=line_idx,
                        end_line=end_line,
                        signature=stripped[:240],
                    )
                )
                continue

            # Struct / Interface: type Name struct / interface
            type_match = self._TYPE_RE.match(line)
            if type_match:
                name = type_match.group("name")
                kind = type_match.group("kind")
                end_line = self._calculate_end_line(lines, line_idx)
                symbols.append(
                    CodeSymbol(
                        name=name,
                        kind=kind,
                        start_line=line_idx,
                        end_line=end_line,
                        signature=stripped[:240],
                    )
                )
                continue

            # Type alias: type Name int
            alias_match = self._TYPE_ALIAS_RE.match(line)
            if alias_match:
                name = alias_match.group("name")
                symbols.append(
                    CodeSymbol(
                        name=name,
                        kind="type",
                        start_line=line_idx,
                        end_line=line_idx,
                        signature=stripped[:240],
                    )
                )

        symbols.sort(key=lambda s: (s.start_line, s.name))
        return symbols

    def extract_spans(self, rel_path: str, text: str, line_count: int) -> list[StructuralSpan]:
        symbols = self.extract_symbols(rel_path, text)
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

    def extract_evidence(self, rel_path: str, text: str) -> LanguageEvidence:
        lines = text.splitlines()
        package: str | None = None
        imports: list[str] = []
        exports: list[str] = []
        declarations: list[str] = []
        doc_hints: list[str] = []

        in_import_block = False
        for line in lines:
            stripped = line.strip()
            if not package:
                pkg_match = self._PACKAGE_RE.match(stripped)
                if pkg_match:
                    package = pkg_match.group("pkg")
                    continue

            if stripped == "import (" or stripped.startswith("import ("):
                in_import_block = True
                continue
            if in_import_block:
                if stripped == ")":
                    in_import_block = False
                    continue
                match = re.search(r'"(?P<imp>[^"]+)"', stripped)
                if match:
                    imports.append(match.group("imp"))
                continue

            single_match = self._SINGLE_IMPORT_RE.match(stripped)
            if single_match:
                imports.append(single_match.group("imp"))

            if stripped.startswith("//") and not stripped.startswith("//go:"):
                comment = stripped.lstrip("/ ").strip()
                if (comment.startswith("Package ") or " " in comment) and len(doc_hints) < 10:
                    doc_hints.append(comment)

        symbols = self.extract_symbols(rel_path, text)
        for sym in symbols:
            declarations.append(f"{sym.kind} {sym.name}")
            # In Go, capitalized identifiers are exported
            check_name = sym.name.split(".")[-1]
            if check_name and check_name[0].isupper():
                exports.append(sym.name)

        companion = self._resolve_companion(rel_path)

        return LanguageEvidence(
            package=package,
            imports=imports,
            exports=exports,
            declarations=declarations,
            doc_hints=doc_hints,
            companion_path=companion,
        )

    def _calculate_end_line(self, lines: list[str], start_line: int) -> int:
        start_idx = start_line - 1
        line = lines[start_idx]
        if "{" in line:
            return find_block_end(lines, start_line)
        for idx in range(start_idx, min(len(lines), start_idx + 5)):
            if "{" in lines[idx]:
                return find_block_end(lines, idx + 1)
        return min(len(lines), start_line + 50)

    def _resolve_companion(self, rel_path: str) -> str | None:
        p = Path(rel_path)
        name = p.name
        if name.endswith("_test.go"):
            target_name = name[:-8] + ".go"
            cand = p.with_name(target_name)
            if cand.exists():
                return str(cand)
            return str(cand)
        if name.endswith(".go"):
            target_name = name[:-3] + "_test.go"
            cand = p.with_name(target_name)
            if cand.exists():
                return str(cand)
            return str(cand)
        return None
