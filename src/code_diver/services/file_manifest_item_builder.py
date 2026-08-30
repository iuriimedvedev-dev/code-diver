from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..domain import CodeItem, CodeItemIndexKind, CodeItemMetadata, CodeSymbol
from .file_summary_item_builder import (
    JVM_DECLARATION_RE,
    JVM_DOC_END_RE,
    JVM_DOC_START_RE,
)

PACKAGE_RE = re.compile(r"^\s*package\s+([A-Za-z_][\w.]*);?\s*$", re.MULTILINE)
IMPORT_RE = re.compile(
    r"^\s*(?:import\s+(?:static\s+)?[A-Za-z_][\w.*]*(?:\s+as\s+[A-Za-z_][\w]*)?;?"
    r"|from\s+[\w.]+\s+import\s+.+)\s*$",
    re.MULTILINE,
)
CONFIG_KEY_RE = re.compile(r"^\s*([A-Za-z_][\w.-]{1,120})\s*[:=]", re.MULTILINE)
XML_NAME_RE = re.compile(r"<\s*([A-Za-z_][\w.-]*)(?:\s|>|/)")
PATH_SPLIT_RE = re.compile(r"[^A-Za-z0-9]+")
IDENTIFIER_WORD_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|[^A-Za-z0-9]+")

JVM_SUFFIXES = frozenset({".java", ".kt", ".kts"})

# H-66c: in symbol-surface mode the manifest vector must carry the API surface that the
# 500-char summary window truncates away. Object/accessor plumbing carries no discriminative
# signal and is dropped so real domain methods reach the vector.
TRIVIAL_SYMBOL_NAMES = frozenset(
    {
        "tostring",
        "equals",
        "hashcode",
        "clone",
        "finalize",
        "copy",
        "compareto",
        "iterator",
        "invoke",
        "main",
    }
)
SURFACE_MAX_SYMBOLS = 22
SURFACE_MAX_SIGNATURE_CHARS = 120
SURFACE_MAX_DOC_CHARS = 220


class FileManifestItemBuilder:
    def __init__(
        self,
        max_imports: int = 20,
        max_symbols: int = 80,
        max_config_keys: int = 80,
        symbol_surface: bool = False,
    ):
        self.max_imports = max_imports
        self.max_symbols = max_symbols
        self.max_config_keys = max_config_keys
        self.symbol_surface = symbol_surface

    def build(self, rel_path: str, text: str, symbols: list[CodeSymbol]) -> CodeItem:
        digest = hashlib.sha1(f"{rel_path}:file-manifest".encode()).hexdigest()[:12]
        sections = (
            self._symbol_surface_sections(rel_path, text, symbols)
            if self.symbol_surface
            else [
                f"file: {rel_path}",
                f"filename: {Path(rel_path).name}",
                f"extension: {Path(rel_path).suffix.lower()}",
                self._path_section(rel_path),
                self._package_section(text),
                self._symbols_section(symbols),
                self._imports_section(text),
                self._config_section(rel_path, text),
            ]
        )
        content = "\n".join(section for section in sections if section).strip()
        return CodeItem(
            id=f"{rel_path}::file_manifest#{digest}",
            path=rel_path,
            title=f"{rel_path}::file_manifest",
            content=content,
            metadata={
                CodeItemMetadata.SOURCE: "scanner",
                CodeItemMetadata.INDEX_KIND: CodeItemIndexKind.FILE_MANIFEST,
            },
        )

    def _symbol_surface_sections(
        self, rel_path: str, text: str, symbols: list[CodeSymbol]
    ) -> list[str]:
        """Return the manifest text as the symbol surface of the file.

        The embedder truncates at ~500 chars, so the declaration, its supertypes,
        the class-level doc sentence and the most informative signatures come first.
        No license, no package, no imports, and only the basename of the path -- the
        full path stays in the item `path`/`id`/`title`, so path scoring, dedup and
        retrieval are unaffected.
        """
        if Path(rel_path).suffix.lower() not in JVM_SUFFIXES:
            return [
                f"filename: {Path(rel_path).name}",
                self._config_section(rel_path, text),
                self._surface_symbols_section(symbols),
            ]
        declaration = self._primary_declaration(text)
        return [
            self._declaration_section(declaration),
            self._doc_section(text),
            self._surface_symbols_section(symbols, declaration[1] if declaration else None),
            f"filename: {Path(rel_path).name}",
        ]

    def _declaration_section(self, declaration: tuple[str, str, str] | None) -> str:
        if not declaration:
            return ""
        kind, name, tail = declaration
        supertypes = self._supertypes(tail)
        row = f"declaration: {kind} {name}"
        if supertypes:
            row += " : " + ", ".join(supertypes)
        return row

    def _doc_section(self, text: str) -> str:
        declaration_line = self._primary_declaration_line(text)
        if declaration_line is None:
            return ""
        sentence = self._preceding_doc_sentence(text, declaration_line)
        if not sentence:
            return ""
        return "doc: " + self._cap(sentence, SURFACE_MAX_DOC_CHARS)

    def _surface_symbols_section(
        self, symbols: list[CodeSymbol], declared_name: str | None = None
    ) -> str:
        rows = [
            f"- {self._cap(self._normalize(symbol.signature) or symbol.name, SURFACE_MAX_SIGNATURE_CHARS)}"
            for symbol in self._informative_symbols(symbols, declared_name)
        ]
        if not rows:
            return "api: none"
        return "api:\n" + "\n".join(rows)

    def _informative_symbols(
        self, symbols: list[CodeSymbol], declared_name: str | None = None
    ) -> list[CodeSymbol]:
        candidates = [
            symbol
            for symbol in symbols[: self.max_symbols]
            if symbol.name.lower() not in TRIVIAL_SYMBOL_NAMES
            and not symbol.name.startswith("_")
            and "private" not in self._normalize(symbol.signature).split()
            and symbol.name != declared_name
        ]
        ranked = sorted(
            enumerate(candidates),
            key=lambda pair: (-self._informativeness(pair[1]), pair[0]),
        )
        keep = sorted(index for index, _ in ranked[:SURFACE_MAX_SYMBOLS])
        return [candidates[index] for index in keep]

    @staticmethod
    def _informativeness(symbol: CodeSymbol) -> int:
        words = [word for word in IDENTIFIER_WORD_RE.split(symbol.name) if word]
        score = len(words)
        if symbol.kind in {"class", "interface", "object", "enum"}:
            score += 2
        if words and words[0].lower() in {"get", "set", "is", "has"}:
            score -= 1
        return score

    def _primary_declaration(self, text: str) -> tuple[str, str, str] | None:
        for line in text.splitlines():
            match = JVM_DECLARATION_RE.match(line)
            if match:
                return match.group("kind"), match.group("name"), match.group("tail").strip()
        return None

    def _primary_declaration_line(self, text: str) -> int | None:
        for line_number, line in enumerate(text.splitlines(), start=1):
            if JVM_DECLARATION_RE.match(line):
                return line_number
        return None

    def _preceding_doc_sentence(self, text: str, line_number: int) -> str | None:
        lines = text.splitlines()
        end = line_number - 2
        while end >= 0 and not lines[end].strip():
            end -= 1
        if end < 0 or not JVM_DOC_END_RE.search(lines[end]):
            return None
        start = end
        while start >= 0 and not JVM_DOC_START_RE.match(lines[start]):
            start -= 1
        if start < 0:
            return None
        doc_lines = []
        for line in lines[start : end + 1]:
            cleaned = re.sub(r"^\s*/\*\*?\s?", "", line)
            cleaned = re.sub(r"^\s*\*\s?", "", cleaned)
            cleaned = re.sub(r"\s*\*/\s*$", "", cleaned)
            if cleaned.strip():
                doc_lines.append(cleaned.strip())
        doc = " ".join(doc_lines)
        sentence = re.split(r"(?<=[.!?])\s+", doc, maxsplit=1)[0]
        return sentence or None

    def _supertypes(self, tail: str) -> list[str]:
        match = re.search(r"(?::|\bextends\s+|\bimplements\s+)(.+)$", self._strip_parens(tail))
        if not match:
            return []
        clauses = re.split(r"\b(?:extends|implements)\b", match.group(1))
        return [
            item.strip().split("<", 1)[0].split("(", 1)[0].strip()
            for clause in clauses
            for item in clause.split(",")
            if item.strip()
        ]

    def _strip_parens(self, tail: str) -> str:
        kept: list[str] = []
        depth = 0
        for char in tail:
            if char == "(":
                depth += 1
                continue
            if char == ")":
                depth = max(depth - 1, 0)
                continue
            if depth == 0:
                kept.append(char)
        return "".join(kept)

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(str(value).split())

    @staticmethod
    def _cap(value: str, limit: int) -> str:
        return value if len(value) <= limit else value[:limit].rstrip()

    def _path_section(self, rel_path: str) -> str:
        parts = [part for part in Path(rel_path).parts if part]
        tokens = self._unique_tokens(" ".join(parts))
        rows = [f"directories: {' / '.join(parts[:-1]) or 'none'}"]
        rows.append("path_tokens: " + (" ".join(tokens) if tokens else "none"))
        return "\n".join(rows)

    def _package_section(self, text: str) -> str:
        packages = self._unique(PACKAGE_RE.findall(text))
        if not packages:
            return "package: none"
        return "package: " + packages[0]

    def _imports_section(self, text: str) -> str:
        imports = [match.group(0).strip().rstrip(";") for match in IMPORT_RE.finditer(text)]
        rows = self._unique(imports)[: self.max_imports]
        if not rows:
            return "imports: none"
        return "imports:\n" + "\n".join(f"- {row}" for row in rows)

    def _symbols_section(self, symbols: list[CodeSymbol]) -> str:
        if not symbols:
            return "symbols: none"
        rows = [
            f"- {symbol.kind} {symbol.name}: {symbol.signature}"
            for symbol in symbols[: self.max_symbols]
        ]
        return "symbols:\n" + "\n".join(rows)

    def _config_section(self, rel_path: str, text: str) -> str:
        suffix = Path(rel_path).suffix.lower()
        keys: list[str] = []
        if suffix in {".properties", ".yaml", ".yml", ".toml"}:
            keys.extend(CONFIG_KEY_RE.findall(text))
        if suffix == ".xml":
            keys.extend(XML_NAME_RE.findall(text))
        keys = self._unique(keys)[: self.max_config_keys]
        if not keys:
            return "config_keys: none"
        return "config_keys:\n" + "\n".join(f"- {key}" for key in keys)

    def _unique_tokens(self, text: str) -> list[str]:
        return self._unique(token.lower() for token in PATH_SPLIT_RE.split(text) if len(token) >= 2)

    def _unique(self, values) -> list[str]:
        seen: set[str] = set()
        rows: list[str] = []
        for value in values:
            row = " ".join(str(value).split())
            key = row.lower()
            if not row or key in seen:
                continue
            seen.add(key)
            rows.append(row)
        return rows
