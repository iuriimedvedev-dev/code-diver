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


class CppStrategy:
    name: str = "cpp"
    supported_extensions: frozenset[str] = frozenset({
        ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".c++", ".h++"
    })

    _SOURCE_EXTS: ClassVar[set[str]] = {".c", ".cc", ".cpp", ".cxx", ".c++"}
    _HEADER_EXTS: ClassVar[set[str]] = {".h", ".hh", ".hpp", ".hxx", ".h++"}

    _CONTROL_WORDS: ClassVar[set[str]] = {
        "if", "for", "while", "switch", "catch", "return", "sizeof", "case", "delete", "new", "throw"
    }

    _NAMESPACE_RE = re.compile(r"^\s*namespace\s+(?P<ns>[A-Za-z_][\w:]*)")
    _INCLUDE_RE = re.compile(r'^\s*#\s*include\s+[<"](?P<inc>[^>"]+)[>"]')

    # Class, struct, enum definitions
    _TYPE_RE = re.compile(
        r"^\s*(?:template\s*<[^>]*>\s*)?(?P<kind>class|struct|enum\s+class|enum\s+struct|enum)\s+"
        r"(?:[A-Za-z0-9_]+_API\s+)?(?P<name>[A-Za-z_]\w*)"
    )

    # Constructors and destructors: ClassName(...) or Class::ClassName(...) or Class::~ClassName(...) or ~ClassName(...)
    _CTOR_DTOR_RE = re.compile(
        r"^\s*(?:template\s*<[^>]*>\s*)?(?:(?:explicit|inline|constexpr)\s+)*"
        r"(?:(?P<cls>[A-Za-z_]\w*)::)?(?P<tilde>~)?(?P<name>[A-Za-z_]\w*)\s*\([^;)]*\)\s*"
        r"(?::\s*[^{]+)?(?=\{|$)"
    )

    # Member methods: ReturnType Class::Method(args)
    _MEMBER_METHOD_RE = re.compile(
        r"^\s*(?:template\s*<[^>]*>\s*)?(?:(?:static|inline|virtual|constexpr|consteval|explicit|friend)\s+)*"
        r"(?P<ret>[A-Za-z_][\w:<>,*&\[\]\s]*?\s+)(?P<cls>[A-Za-z_]\w*)::(?P<name>[A-Za-z_]\w*)\s*\([^;)]*\)"
        r"(?:\s*const)?(?:\s*noexcept(?:\([^)]*\))?)?(?:\s*override)?(?:\s*final)?\s*(?:->\s*[^;{]+)?(?=\{|$)"
    )

    # Free functions & Template functions: ReturnType name(args)
    _FREE_FN_RE = re.compile(
        r"^\s*(?:template\s*<[^>]*>\s*)?(?:(?:static|inline|virtual|constexpr|consteval|extern(?:\s+\"[^\"]+\")?)\s+)*"
        r"(?P<ret>[A-Za-z_][\w:<>,*&\[\]\s]*?\s+)(?P<name>[A-Za-z_]\w*)\s*\([^;)]*\)"
        r"(?:\s*const)?(?:\s*noexcept(?:\([^)]*\))?)?(?:\s*override)?(?:\s*final)?\s*(?:->\s*[^;{]+)?(?=\{|$)"
    )

    def extract_symbols(self, rel_path: str, text: str) -> list[CodeSymbol]:
        lines = text.splitlines()
        symbols: list[CodeSymbol] = []

        for line_idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith(("//", "/*", "*", "#")):
                continue

            # Class / Struct / Enum
            type_match = self._TYPE_RE.match(line)
            if type_match:
                name = type_match.group("name")
                raw_kind = type_match.group("kind")
                # Exclude forward declarations like "class Foo;" or "struct Bar;"
                if not self._is_forward_decl(lines, line_idx):
                    kind = "enum" if "enum" in raw_kind else "struct" if raw_kind == "struct" else "class"
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

            # Constructor or Destructor
            ctor_match = self._CTOR_DTOR_RE.match(line)
            if ctor_match:
                cls = ctor_match.group("cls")
                tilde = ctor_match.group("tilde")
                name = ctor_match.group("name")
                is_dtor = bool(tilde)
                is_ctor = (cls is not None and cls == name) or (cls is None and not is_dtor and name not in self._CONTROL_WORDS and not self._has_return_type_prefix(stripped, name))
                if (is_dtor or is_ctor) and name not in self._CONTROL_WORDS:
                    full_name = f"{cls}::{'~' if is_dtor else ''}{name}" if cls else f"{'~' if is_dtor else ''}{name}"
                    kind = "destructor" if is_dtor else "constructor"
                    end_line = self._calculate_end_line(lines, line_idx)
                    symbols.append(
                        CodeSymbol(
                            name=full_name,
                            kind=kind,
                            start_line=line_idx,
                            end_line=end_line,
                            signature=stripped[:240],
                        )
                    )
                    continue

            # Member method Class::Method
            method_match = self._MEMBER_METHOD_RE.match(line)
            if method_match:
                cls = method_match.group("cls")
                name = method_match.group("name")
                if name not in self._CONTROL_WORDS and cls not in self._CONTROL_WORDS:
                    end_line = self._calculate_end_line(lines, line_idx)
                    symbols.append(
                        CodeSymbol(
                            name=f"{cls}::{name}",
                            kind="method",
                            start_line=line_idx,
                            end_line=end_line,
                            signature=stripped[:240],
                        )
                    )
                    continue

            # Free function / template function
            fn_match = self._FREE_FN_RE.match(line)
            if fn_match:
                name = fn_match.group("name")
                if name not in self._CONTROL_WORDS and not name.startswith("~"):
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
        namespace: str | None = None
        imports: list[str] = []
        exports: list[str] = []
        declarations: list[str] = []
        doc_hints: list[str] = []

        in_doc = False
        current_doc: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not namespace:
                ns_match = self._NAMESPACE_RE.match(stripped)
                if ns_match:
                    namespace = ns_match.group("ns")

            inc_match = self._INCLUDE_RE.match(stripped)
            if inc_match:
                imports.append(inc_match.group("inc"))

            if stripped.startswith("///"):
                hint = stripped.lstrip("/ ").strip()
                if hint and len(doc_hints) < 10:
                    doc_hints.append(hint)
            elif stripped.startswith("/**"):
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
        is_header = Path(rel_path).suffix in self._HEADER_EXTS
        for sym in symbols:
            declarations.append(f"{sym.kind} {sym.name}")
            # Header declarations or symbols with export markings are considered exported
            if is_header or "export" in sym.signature.lower() or 'extern "C"' in sym.signature:
                exports.append(sym.name)

        companion = self._resolve_companion(rel_path)

        return LanguageEvidence(
            namespace=namespace,
            imports=imports,
            exports=exports,
            declarations=declarations,
            doc_hints=doc_hints,
            companion_path=companion,
        )

    def _is_forward_decl(self, lines: list[str], start_line: int) -> bool:
        start_idx = start_line - 1
        line = lines[start_idx]
        if ";" in line and "{" not in line:
            return True
        for idx in range(start_idx, min(len(lines), start_idx + 3)):
            if ";" in lines[idx] and "{" not in lines[idx]:
                return True
            if "{" in lines[idx]:
                return False
        return False

    def _has_return_type_prefix(self, stripped: str, name: str) -> bool:
        idx = stripped.find(name)
        if idx <= 0:
            return False
        prefix = stripped[:idx].strip()
        tokens = [t for t in prefix.split() if t not in {"explicit", "inline", "constexpr", "virtual"}]
        return len(tokens) > 0

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
        ext = p.suffix.lower()

        if ext in self._SOURCE_EXTS:
            # Source -> find Header
            header_exts = [".hpp", ".h", ".hh", ".hxx"]
            # 1. Same directory
            for h_ext in header_exts:
                cand = p.with_suffix(h_ext)
                if cand.exists():
                    return str(cand)
            # 2. Check include/ directory counterpart if in src/
            path_str = str(p)
            if "src/" in path_str:
                for h_ext in header_exts:
                    cand = Path(path_str.replace("src/", "include/")).with_suffix(h_ext)
                    if cand.exists():
                        return str(cand)
            # Default to .h or .hpp
            default_ext = ".hpp" if ext in {".cpp", ".cc", ".cxx"} else ".h"
            return str(p.with_suffix(default_ext))

        elif ext in self._HEADER_EXTS:
            # Header -> find Source
            source_exts = [".cpp", ".cc", ".cxx", ".c"]
            # 1. Same directory
            for s_ext in source_exts:
                cand = p.with_suffix(s_ext)
                if cand.exists():
                    return str(cand)
            # 2. Check src/ counterpart if in include/
            path_str = str(p)
            if "include/" in path_str:
                for s_ext in source_exts:
                    cand = Path(path_str.replace("include/", "src/")).with_suffix(s_ext)
                    if cand.exists():
                        return str(cand)
            # Default to .cpp or .c
            default_ext = ".c" if ext == ".h" and not p.name.endswith(".hpp") else ".cpp"
            return str(p.with_suffix(default_ext))

        return None
