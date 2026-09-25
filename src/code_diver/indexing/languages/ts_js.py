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


class TsJsStrategy:
    name: str = "ts_js"
    supported_extensions: frozenset[str] = frozenset({
        ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"
    })

    _CLASS_RE = re.compile(
        r"^\s*(?:export\s+(?:default\s+)?)?(?:abstract\s+)?class\s+(?P<name>[A-Za-z_$][\w$]*)"
    )
    _INTERFACE_RE = re.compile(
        r"^\s*(?:export\s+)?interface\s+(?P<name>[A-Za-z_$][\w$]*)"
    )
    _TYPE_ALIAS_RE = re.compile(
        r"^\s*(?:export\s+)?type\s+(?P<name>[A-Za-z_$][\w$]*)\s*(?:<[^>]+>)?\s*="
    )
    _FUNCTION_RE = re.compile(
        r"^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?function(?:\s*\*\s*|\s+)(?P<name>[A-Za-z_$][\w$]*)\s*(?:<[^>]+>)?\s*\("
    )
    _CONST_FN_RE = re.compile(
        r"^\s*(?:export\s+)?const\s+(?P<name>[A-Za-z_$][\w$]*)\s*(?::\s*[^=]+)?=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
    )
    _CONST_FN_EXPR_RE = re.compile(
        r"^\s*(?:export\s+)?const\s+(?P<name>[A-Za-z_$][\w$]*)\s*(?::\s*[^=]+)?=\s*(?:async\s*)?function\b"
    )
    _EXPORT_CONST_RE = re.compile(
        r"^\s*export\s+(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)"
    )
    _IMPORT_FROM_RE = re.compile(
        r"^\s*import\s+(?:.+?\s+from\s+)?['\"](?P<source>[^'\"]+)['\"]"
    )
    _REQUIRE_RE = re.compile(
        r"(?:const|let|var)\s+(?:\{[^}]+\}|[A-Za-z_$][\w$]*)\s*=\s*require\(['\"](?P<source>[^'\"]+)['\"]\)"
    )
    _EXPORT_NAMES_RE = re.compile(
        r"^\s*export\s*\{\s*(?P<names>[^}]+)\s*\}"
    )

    def extract_symbols(self, rel_path: str, text: str) -> list[CodeSymbol]:
        lines = text.splitlines()
        symbols: list[CodeSymbol] = []

        for line_idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith(("//", "/*", "*")):
                continue

            # Class
            match = self._CLASS_RE.match(line)
            if match:
                name = match.group("name")
                end_line = self._calculate_end_line(lines, line_idx)
                symbols.append(
                    CodeSymbol(
                        name=name,
                        kind="class",
                        start_line=line_idx,
                        end_line=end_line,
                        signature=stripped[:240],
                    )
                )
                continue

            # Interface
            match = self._INTERFACE_RE.match(line)
            if match:
                name = match.group("name")
                end_line = self._calculate_end_line(lines, line_idx)
                symbols.append(
                    CodeSymbol(
                        name=name,
                        kind="interface",
                        start_line=line_idx,
                        end_line=end_line,
                        signature=stripped[:240],
                    )
                )
                continue

            # Type alias
            match = self._TYPE_ALIAS_RE.match(line)
            if match:
                name = match.group("name")
                end_line = self._calculate_end_line(lines, line_idx)
                symbols.append(
                    CodeSymbol(
                        name=name,
                        kind="type",
                        start_line=line_idx,
                        end_line=end_line,
                        signature=stripped[:240],
                    )
                )
                continue

            # Const function (arrow or expression)
            match = self._CONST_FN_RE.match(line) or self._CONST_FN_EXPR_RE.match(line)
            if match:
                name = match.group("name")
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

            # Standard function
            match = self._FUNCTION_RE.match(line)
            if match:
                name = match.group("name")
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

            # Export const/var (non-function)
            match = self._EXPORT_CONST_RE.match(line)
            if match:
                name = match.group("name")
                symbols.append(
                    CodeSymbol(
                        name=name,
                        kind="symbol",
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
        imports: list[str] = []
        exports: list[str] = []
        declarations: list[str] = []
        doc_hints: list[str] = []

        # Find imports, doc comments, and explicit export blocks
        in_doc = False
        current_doc: list[str] = []
        for line in lines:
            stripped = line.strip()
            imp_match = self._IMPORT_FROM_RE.match(stripped)
            if imp_match:
                imports.append(imp_match.group("source"))

            req_match = self._REQUIRE_RE.search(stripped)
            if req_match:
                imports.append(req_match.group("source"))

            export_block = self._EXPORT_NAMES_RE.match(stripped)
            if export_block:
                for n in export_block.group("names").split(","):
                    clean = n.strip().split(" as ")[-1].strip()
                    if clean:
                        exports.append(clean)

            if stripped.startswith("/**"):
                in_doc = True
                current_doc = [stripped.removeprefix("/**").removesuffix("*/").strip()]
                if stripped.endswith("*/") and len(stripped) > 4:
                    in_doc = False
                    first = current_doc[0]
                    if first and len(doc_hints) < 10:
                        doc_hints.append(first)
                continue
            if in_doc:
                if stripped.endswith("*/"):
                    in_doc = False
                    cleaned = stripped.removesuffix("*/").lstrip("* ").strip()
                    if cleaned:
                        current_doc.append(cleaned)
                    first = next((d for d in current_doc if d), "")
                    if first and len(doc_hints) < 10:
                        doc_hints.append(first)
                else:
                    cleaned = stripped.lstrip("* ").strip()
                    if cleaned:
                        current_doc.append(cleaned)

        symbols = self.extract_symbols(rel_path, text)
        for sym in symbols:
            declarations.append(f"{sym.kind} {sym.name}")
            if re.match(r"^\s*export\b", sym.signature):
                exports.append(sym.name)

        companion = self._resolve_companion(rel_path)

        return LanguageEvidence(
            package=None,
            imports=imports,
            exports=sorted(list(set(exports))),
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
            if ";" in lines[idx]:
                return idx + 1
        return min(len(lines), start_line + 50)

    def _resolve_companion(self, rel_path: str) -> str | None:
        p = Path(rel_path)
        name = p.name
        stem = p.stem
        suffix = p.suffix

        # Definition file
        if name.endswith(".d.ts"):
            base = name[:-5]
            cand = p.with_name(f"{base}.ts")
            if cand.exists():
                return str(cand)
            return str(cand)

        # Test files -> source
        for pattern in [".test", ".spec", "_test", "_spec"]:
            if pattern in stem:
                base_stem = stem.replace(pattern, "")
                cand = p.with_name(f"{base_stem}{suffix}")
                if cand.exists():
                    return str(cand)
                return str(cand)

        # Source -> test
        test_cand = p.with_name(f"{stem}.test{suffix}")
        if test_cand.exists():
            return str(test_cand)
        spec_cand = p.with_name(f"{stem}.spec{suffix}")
        if spec_cand.exists():
            return str(spec_cand)
        dts_cand = p.with_name(f"{stem}.d.ts")
        if dts_cand.exists():
            return str(dts_cand)

        return str(test_cand)
