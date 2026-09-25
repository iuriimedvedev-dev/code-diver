from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar

from ...domain import CodeSymbol
from .base import (
    LanguageEvidence,
    StructuralSpan,
    find_block_end,
    with_preamble_span,
)


class JvmStrategy:
    name: str = "jvm"
    supported_extensions: frozenset[str] = frozenset({".java", ".kt", ".kts"})

    _JVM_TYPE_RE = re.compile(
        r"^\s*(?:(?:public|private|protected|internal|open|final|abstract|sealed|data|value|inner|static|non-sealed)\s+)*"
        r"(?P<kind>class|interface|enum\s+class|enum|object|record|annotation\s+class|@interface)\s+"
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
    _JAVA_CONSTRUCTOR_RE = re.compile(
        r"^\s*(?:(?:public|private|protected)\s+)+(?P<name>[A-Za-z_][\w$]*)\s*\([^;)]*\)\s*(?:throws\s+[^{]+)?\{"
    )
    _PACKAGE_RE = re.compile(r"^\s*package\s+(?P<pkg>[a-zA-Z0-9_.]+);?")
    _IMPORT_RE = re.compile(r"^\s*import\s+(?:static\s+)?(?P<imp>[a-zA-Z0-9_.*]+);?")
    _CONTROL_WORDS: ClassVar[set[str]] = {
        "if", "for", "while", "switch", "catch", "when", "return", "throw", "new", "synchronized"
    }

    def extract_symbols(self, rel_path: str, text: str) -> list[CodeSymbol]:
        lines = text.splitlines()
        symbols: list[CodeSymbol] = []

        for line_idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith(("//", "*", "/*")):
                continue

            type_match = self._JVM_TYPE_RE.match(line)
            if type_match:
                raw_kind = type_match.group("kind")
                name = type_match.group("name")
                kind = self._normalize_kind(raw_kind)
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

            fn_match = self._KOTLIN_FUNCTION_RE.match(line)
            if fn_match:
                name = fn_match.group("name")
                if name not in self._CONTROL_WORDS:
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

            ctor_match = self._JAVA_CONSTRUCTOR_RE.match(line)
            if ctor_match:
                name = ctor_match.group("name")
                if name not in self._CONTROL_WORDS:
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

            method_match = self._JAVA_METHOD_RE.match(line)
            if method_match:
                name = method_match.group("name")
                if name not in self._CONTROL_WORDS:
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

        # Find package and imports
        for line in lines:
            if not package:
                pkg_match = self._PACKAGE_RE.match(line)
                if pkg_match:
                    package = pkg_match.group("pkg")
                    continue
            imp_match = self._IMPORT_RE.match(line)
            if imp_match:
                imports.append(imp_match.group("imp"))

        # Find doc comments /** ... */
        in_doc = False
        current_doc: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("/**"):
                in_doc = True
                current_doc = [stripped.removeprefix("/**").removesuffix("*/").strip()]
                if stripped.endswith("*/") and len(stripped) > 4:
                    in_doc = False
                    first = current_doc[0]
                    if first:
                        doc_hints.append(first)
                continue
            if in_doc:
                if stripped.endswith("*/"):
                    in_doc = False
                    cleaned = stripped.removesuffix("*/").lstrip("* ").strip()
                    if cleaned:
                        current_doc.append(cleaned)
                    first = next((d for d in current_doc if d), "")
                    if first:
                        doc_hints.append(first)
                else:
                    cleaned = stripped.lstrip("* ").strip()
                    if cleaned:
                        current_doc.append(cleaned)

        # Declarations and exports
        symbols = self.extract_symbols(rel_path, text)
        is_kotlin = Path(rel_path).suffix in {".kt", ".kts"}
        for sym in symbols:
            declarations.append(f"{sym.kind} {sym.name}")
            sig = sym.signature
            if is_kotlin:
                # In Kotlin, symbols without private/internal are public
                if not re.search(r"\b(private|internal)\b", sig):
                    exports.append(sym.name)
            else:
                # In Java, public or protected are exported
                if re.search(r"\b(public|protected)\b", sig):
                    exports.append(sym.name)

        companion = self._resolve_companion(rel_path)

        return LanguageEvidence(
            package=package,
            imports=imports,
            exports=exports,
            declarations=declarations,
            doc_hints=doc_hints[:10],
            companion_path=companion,
        )

    def _calculate_end_line(self, lines: list[str], start_line: int) -> int:
        start_idx = start_line - 1
        line = lines[start_idx]
        if "{" in line:
            return find_block_end(lines, start_line)
        # Check next few lines for '{' or ';'
        for idx in range(start_idx, min(len(lines), start_idx + 5)):
            if "{" in lines[idx]:
                return find_block_end(lines, idx + 1)
            if ";" in lines[idx]:
                return idx + 1
        return min(len(lines), start_line + 50)

    def _normalize_kind(self, raw_kind: str) -> str:
        k = " ".join(raw_kind.split())
        if k in {"enum", "enum class"}:
            return "enum"
        if k in {"annotation class", "@interface"}:
            return "annotation"
        if k == "record":
            return "record"
        return k

    def _resolve_companion(self, rel_path: str) -> str | None:
        p = Path(rel_path)
        stem = p.stem
        suffix = p.suffix
        if stem.endswith(("Test", "Tests")):
            base = stem.removesuffix("Tests").removesuffix("Test")
            cand = p.with_name(f"{base}{suffix}")
            if cand.exists():
                return str(cand)
            # Try src/main/java / src/test/java swap
            path_str = str(p)
            if "src/test/" in path_str:
                src_cand = Path(path_str.replace("src/test/", "src/main/")).with_name(f"{base}{suffix}")
                if src_cand.exists():
                    return str(src_cand)
            return str(cand)
        else:
            cand = p.with_name(f"{stem}Test{suffix}")
            if cand.exists():
                return str(cand)
            path_str = str(p)
            if "src/main/" in path_str:
                test_cand = Path(path_str.replace("src/main/", "src/test/")).with_name(f"{stem}Test{suffix}")
                if test_cand.exists():
                    return str(test_cand)
            return str(cand)
