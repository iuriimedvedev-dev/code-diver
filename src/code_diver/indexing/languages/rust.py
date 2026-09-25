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


class RustStrategy:
    name: str = "rust"
    supported_extensions: frozenset[str] = frozenset({".rs"})

    _VIS_PREFIX = r"(?:pub(?:\((?:crate|super|self|in\s+[^)]+)\))?\s+)?"
    _STRUCT_RE = re.compile(
        rf"^\s*(?P<vis>{_VIS_PREFIX})struct\s+(?P<name>[A-Za-z_]\w*)"
    )
    _ENUM_RE = re.compile(
        rf"^\s*(?P<vis>{_VIS_PREFIX})enum\s+(?P<name>[A-Za-z_]\w*)"
    )
    _TRAIT_RE = re.compile(
        rf"^\s*(?P<vis>{_VIS_PREFIX})(?:unsafe\s+)?trait\s+(?P<name>[A-Za-z_]\w*)"
    )
    _IMPL_RE = re.compile(
        r"^\s*impl(?:<[^>]+>)?\s+(?:(?P<trait>[A-Za-z_][\w:]*(?:<[^>]+>)?)\s+for\s+)?(?P<type>[A-Za-z_][\w:]*(?:<[^>]+>)?)"
    )
    _FN_RE = re.compile(
        rf"^\s*(?P<vis>{_VIS_PREFIX})(?:default\s+)?(?:const\s+)?(?:async\s+)?(?:unsafe\s+)?(?:extern(?:\s+\"[^\"]+\")?\s+)?fn\s+(?P<name>[A-Za-z_]\w*)"
    )
    _MACRO_RULES_RE = re.compile(
        r"^\s*macro_rules!\s+(?P<name>[A-Za-z_]\w*)"
    )
    _PUB_MACRO_RE = re.compile(
        rf"^\s*(?P<vis>{_VIS_PREFIX})macro\s+(?P<name>[A-Za-z_]\w*)"
    )
    _USE_RE = re.compile(r"^\s*(?:pub\s+)?use\s+(?P<import>[^;]+);")
    _MOD_RE = re.compile(r"^\s*(?:pub\s+)?mod\s+(?P<mod>[A-Za-z_]\w*);")

    def extract_symbols(self, rel_path: str, text: str) -> list[CodeSymbol]:
        lines = text.splitlines()
        symbols: list[CodeSymbol] = []

        for line_idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith(("//", "/*", "*")):
                continue

            # Struct
            match = self._STRUCT_RE.match(line)
            if match:
                name = match.group("name")
                end_line = self._calculate_end_line(lines, line_idx)
                symbols.append(
                    CodeSymbol(
                        name=name,
                        kind="struct",
                        start_line=line_idx,
                        end_line=end_line,
                        signature=stripped[:240],
                    )
                )
                continue

            # Enum
            match = self._ENUM_RE.match(line)
            if match:
                name = match.group("name")
                end_line = self._calculate_end_line(lines, line_idx)
                symbols.append(
                    CodeSymbol(
                        name=name,
                        kind="enum",
                        start_line=line_idx,
                        end_line=end_line,
                        signature=stripped[:240],
                    )
                )
                continue

            # Trait
            match = self._TRAIT_RE.match(line)
            if match:
                name = match.group("name")
                end_line = self._calculate_end_line(lines, line_idx)
                symbols.append(
                    CodeSymbol(
                        name=name,
                        kind="trait",
                        start_line=line_idx,
                        end_line=end_line,
                        signature=stripped[:240],
                    )
                )
                continue

            # Impl
            match = self._IMPL_RE.match(line)
            if match:
                trait_name = match.group("trait")
                type_name = match.group("type")
                name = f"{trait_name} for {type_name}" if trait_name else type_name
                end_line = self._calculate_end_line(lines, line_idx)
                symbols.append(
                    CodeSymbol(
                        name=name,
                        kind="impl",
                        start_line=line_idx,
                        end_line=end_line,
                        signature=stripped[:240],
                    )
                )
                continue

            # Function
            match = self._FN_RE.match(line)
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

            # Macro rules
            match = self._MACRO_RULES_RE.match(line)
            if match:
                name = match.group("name")
                end_line = self._calculate_end_line(lines, line_idx)
                symbols.append(
                    CodeSymbol(
                        name=name,
                        kind="macro",
                        start_line=line_idx,
                        end_line=end_line,
                        signature=stripped[:240],
                    )
                )
                continue

            # Pub macro
            match = self._PUB_MACRO_RE.match(line)
            if match:
                name = match.group("name")
                end_line = self._calculate_end_line(lines, line_idx)
                symbols.append(
                    CodeSymbol(
                        name=name,
                        kind="macro",
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

        # Find module / use imports
        for line in lines:
            stripped = line.strip()
            if not package:
                mod_match = self._MOD_RE.match(stripped)
                if mod_match:
                    package = mod_match.group("mod")

            use_match = self._USE_RE.match(stripped)
            if use_match:
                imports.append(use_match.group("import").strip())

            # Doc comments (//! or ///)
            if stripped.startswith(("//!", "///")):
                doc_text = stripped.lstrip("/! ").strip()
                if doc_text and len(doc_hints) < 10:
                    doc_hints.append(doc_text)

        symbols = self.extract_symbols(rel_path, text)
        for sym in symbols:
            declarations.append(f"{sym.kind} {sym.name}")
            # Public if signature starts with pub
            if re.match(r"^\s*pub\b", sym.signature):
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
            if ";" in lines[idx]:
                return idx + 1
        return min(len(lines), start_line + 50)

    def _resolve_companion(self, rel_path: str) -> str | None:
        p = Path(rel_path)
        name = p.name
        if name == "lib.rs":
            main_cand = p.with_name("main.rs")
            if main_cand.exists():
                return str(main_cand)
            return str(main_cand)
        if name == "main.rs":
            lib_cand = p.with_name("lib.rs")
            if lib_cand.exists():
                return str(lib_cand)
            return str(lib_cand)
        if name == "mod.rs":
            parent_name = p.parent.name
            cand = p.parent.parent / f"{parent_name}.rs"
            if cand.exists():
                return str(cand)
            return str(cand)

        test_cand = Path("tests") / f"test_{name}"
        if test_cand.exists():
            return str(test_cand)
        test_cand_direct = Path("tests") / name
        if test_cand_direct.exists():
            return str(test_cand_direct)
        return str(test_cand)
