from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..domain import CodeItem, CodeItemIndexKind, CodeItemMetadata, CodeSymbol

LICENSE_OR_COPYRIGHT_RE = re.compile(
    r"^\s*(//|#|%|;)\s*[Cc]opyright|^\s*/\*(?!\*)|^\s*\*[^/]|^[-]{20,}"
)

IMPORT_RE = re.compile(r"^\s*(?:from\s+[\w.]+\s+import\s+.+|import\s+[\w.,\s;]+)\s*$")
PACKAGE_RE = re.compile(r"^\s*package\s+[\w.]+")
FILE_ANNOTATION_RE = re.compile(r"^\s*@file:\s*")
IDENTIFIER_SPLIT_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|[^A-Za-z0-9]+")
JVM_DECLARATION_RE = re.compile(
    r"^\s*(?:(?:public|private|protected|internal|open|final|abstract|sealed|data|value|inner|static)\s+)*"
    r"(?P<kind>class|interface|object)\s+(?P<name>[A-Za-z_][\w$]*)"
    r"(?P<tail>[^\{\n]*)"
)
JVM_DOC_START_RE = re.compile(r"^\s*/\*\*?")
JVM_DOC_END_RE = re.compile(r"\*/\s*$")
JVM_PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)")

TRUNCATION_MARKER = " ...[truncated]"
MAX_TERM_COUNT = 40
MAX_TERMS_LINE_CHARS = 220
MAX_PURPOSE_LINE_CHARS = 220

# H-66b: the embedder truncates the summary at ~500 chars, so only the first lines reach the
# vector. Language keywords and repository-wide path words carry no discriminative signal and
# are dropped from `terms:` when the compact budget mode is on.
TERM_KEYWORD_STOPWORDS = frozenset(
    {
        "open",
        "class",
        "interface",
        "object",
        "fun",
        "val",
        "var",
        "private",
        "public",
        "protected",
        "internal",
        "override",
        "const",
        "static",
        "final",
        "abstract",
        "suspend",
        "companion",
        "get",
        "set",
        "constructor",
        "return",
        "void",
        "new",
        "extends",
        "implements",
        "package",
        "import",
        "this",
        "super",
        "null",
        "true",
        "false",
    }
)
TERM_PATH_STOPWORDS = frozenset(
    {
        "src",
        "com",
        "intellij",
        "jetbrains",
        "main",
        "java",
        "kotlin",
        "impl",
    }
)
COMPACT_FILE_PATH_SEGMENTS = 2


class FileSummaryItemBuilder:
    def __init__(
        self,
        max_imports: int = 24,
        max_symbols: int = 80,
        max_head_lines: int = 24,
        max_head_line_chars: int = 200,
        max_head_block_chars: int = 4000,
        max_head_import_lines: int = 5,
        compact_budget: bool = False,
        compact_path: bool | None = None,
        term_stopwords: bool | None = None,
    ):
        self.max_imports = max_imports
        self.max_symbols = max_symbols
        self.max_head_lines = max_head_lines
        self.max_head_line_chars = max_head_line_chars
        self.max_head_block_chars = max_head_block_chars
        self.max_head_import_lines = max_head_import_lines
        self.compact_budget = compact_budget
        self.compact_path = compact_path
        # None → follow compact_budget (H-66b). False → keep path/keyword tokens (H-69).
        self.term_stopwords = term_stopwords

    def build(self, rel_path: str, text: str, symbols: list[CodeSymbol]) -> CodeItem:
        digest = hashlib.sha1(f"{rel_path}:file-summary".encode()).hexdigest()[:12]
        sections = (
            [
                self._purpose_section(rel_path, text),
                self._terms_section(rel_path, text, symbols),
                f"file: {self._file_line_value(rel_path)}",
                f"extension: {Path(rel_path).suffix.lower()}",
                self._symbols_section(symbols),
                self._head_section(text),
                self._imports_section(text),
            ]
            if self.compact_budget
            else [
                f"file: {self._file_line_value(rel_path)}",
                f"extension: {Path(rel_path).suffix.lower()}",
                self._purpose_section(rel_path, text),
                self._terms_section(rel_path, text, symbols),
                self._symbols_section(symbols),
                self._head_section(text),
                self._imports_section(text),
            ]
        )
        content = "\n".join(sections).strip()
        return CodeItem(
            id=f"{rel_path}::file_summary#{digest}",
            path=rel_path,
            title=f"{rel_path}::file_summary",
            content=content,
            metadata={
                CodeItemMetadata.SOURCE: "scanner",
                CodeItemMetadata.INDEX_KIND: CodeItemIndexKind.FILE_SUMMARY,
            },
        )

    def _file_line_value(self, rel_path: str) -> str:
        """Return the path fragment embedded in the summary text.

        Compact path mode keeps only the basename plus the last two directory
        segments -- the full path stays in the item `path`/metadata, so path
        scoring, dedup and retrieval are unaffected. When `compact_path` is left
        unset it follows `compact_budget`, preserving existing behaviour.
        """
        compact = self.compact_budget if self.compact_path is None else self.compact_path
        if not compact:
            return rel_path
        parts = Path(rel_path).parts
        return "/".join(parts[-(COMPACT_FILE_PATH_SEGMENTS + 1) :])

    def _purpose_section(self, rel_path: str, text: str) -> str:
        declaration = (
            self._primary_jvm_declaration(text)
            if Path(rel_path).suffix.lower() in {".java", ".kt", ".kts"}
            else None
        )
        if declaration:
            doc = self._preceding_doc_sentence(text, declaration[3])
            if doc:
                return f"purpose: {self._cap_purpose(doc)}"
            kind, name, tail, line_number = declaration
            role = self._declaration_role(name)
            domain = self._domain(rel_path, text)
            supertypes = self._supertypes(tail)
            purpose = f"{role} {name}"
            if supertypes:
                purpose += f" for {', '.join(supertypes)}"
            if domain:
                purpose += f" in {domain}"
            return f"purpose: {self._cap_purpose(purpose)}"
        return f"purpose: {self._path_purpose(rel_path)}"

    def _path_purpose(self, rel_path: str) -> str:
        words = [
            token.lower()
            for token in IDENTIFIER_SPLIT_RE.split(Path(rel_path).stem)
            if len(token) >= 2
        ]
        return self._cap_purpose(" ".join(words)) if words else "none"

    def _terms_section(self, rel_path: str, text: str, symbols: list[CodeSymbol]) -> str:
        values = self._term_values(rel_path, text, symbols)
        extension = Path(rel_path).suffix.lower().lstrip(".")
        terms: list[str] = []
        seen: set[str] = set()
        for value in values:
            for token in IDENTIFIER_SPLIT_RE.split(value):
                normalized = token.lower()
                if len(normalized) < 2 or normalized in seen:
                    continue
                if self._term_stopwords_enabled() and self._is_noise_term(normalized, extension):
                    continue
                if len(f"terms: {' '.join(terms + [normalized])}") > MAX_TERMS_LINE_CHARS:
                    return f"terms: {' '.join(terms) if terms else 'none'}"
                seen.add(normalized)
                terms.append(normalized)
                if len(terms) >= MAX_TERM_COUNT:
                    return f"terms: {' '.join(terms)}"
        return f"terms: {' '.join(terms) if terms else 'none'}"

    def _term_values(self, rel_path: str, text: str, symbols: list[CodeSymbol]) -> list[str]:
        declaration = (
            self._primary_jvm_declaration(text)
            if Path(rel_path).suffix.lower() in {".java", ".kt", ".kts"}
            else None
        )
        package = self._package(text)
        if not self.compact_budget:
            values = [Path(rel_path).stem, *Path(rel_path).parts]
            if declaration:
                _, name, tail, _ = declaration
                values.extend([name, self._declaration_role(name), *self._supertypes(tail)])
                if package:
                    values.append(package)
            for symbol in symbols[: self.max_symbols]:
                values.extend([symbol.name, symbol.signature])
            return values
        # Compact budget: declaration identity first, then the API surface, then the
        # package tail -- the head of the line is what survives the embedding window.
        values = []
        if declaration:
            _, name, tail, _ = declaration
            values.extend([name, self._declaration_role(name), *self._supertypes(tail)])
        values.append(Path(rel_path).stem)
        for symbol in symbols[: self.max_symbols]:
            values.extend([symbol.name, symbol.signature])
        if package:
            values.append(package.split(".")[-1])
        # H-69: when stopwords are off, also inject full path parts so src/com/intellij/impl
        # re-enter the terms vocabulary (compact mode previously omitted them entirely).
        if not self._term_stopwords_enabled():
            values.extend(Path(rel_path).parts)
            if package:
                values.append(package)
        return values

    def _term_stopwords_enabled(self) -> bool:
        if self.term_stopwords is None:
            return self.compact_budget
        return self.term_stopwords

    @staticmethod
    def _is_noise_term(normalized: str, extension: str) -> bool:
        if normalized.isdigit():
            return True
        if normalized == extension:
            return True
        if normalized in TERM_KEYWORD_STOPWORDS:
            return True
        return normalized in TERM_PATH_STOPWORDS

    def _primary_jvm_declaration(self, text: str) -> tuple[str, str, str, int] | None:
        for line_number, line in enumerate(text.splitlines(), start=1):
            match = JVM_DECLARATION_RE.match(line)
            if match:
                return (
                    match.group("kind"),
                    match.group("name"),
                    match.group("tail").strip(),
                    line_number,
                )
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

    def _package(self, text: str) -> str | None:
        match = next((JVM_PACKAGE_RE.match(line) for line in text.splitlines()), None)
        return match.group(1) if match else None

    def _domain(self, rel_path: str, text: str) -> str | None:
        package = self._package(text)
        if package:
            return package.split(".")[-1]
        parts = Path(rel_path).parts
        if len(parts) > 1:
            return parts[-2]
        return None

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

    def _declaration_role(self, name: str) -> str:
        base = re.sub(r"Impl$", "", name)
        for suffix, role in (
            ("Service", "service"),
            ("Controller", "controller"),
            ("Manager", "manager"),
            ("Repository", "repository"),
            ("Factory", "factory"),
            ("Action", "action"),
            ("Handler", "handler"),
            ("Provider", "provider"),
        ):
            if base.endswith(suffix):
                return role + " implementation" if base != name else role
        return "implementation" if base != name else "type"

    def _imports_section(self, text: str) -> str:
        imports = [line.strip() for line in text.splitlines() if IMPORT_RE.match(line)]
        if not imports:
            return "imports: none"
        rows = imports[: self.max_imports]
        return "imports:\n" + "\n".join(f"- {row}" for row in rows)

    def _symbols_section(self, symbols: list[CodeSymbol]) -> str:
        if not symbols:
            return "symbols: none"
        rows = [
            f"- {symbol.kind} {symbol.name}: {symbol.signature}"
            for symbol in symbols[: self.max_symbols]
        ]
        return "symbols:\n" + "\n".join(rows)

    def _head_section(self, text: str) -> str:
        """Return the most informative head lines of the source file.

        Skips license headers, copyright boilerplate, and `@file:` annotations.
        Package declarations are kept — they provide useful module/layer signal.
        Import statements are capped at `max_head_import_lines` (default 5) to
        prevent them from dominating the head section. Returns the first
        meaningful lines: class/interface/object/enum declarations,
        KDoc/Javadoc blocks, annotations, and field/method signatures.
        """
        meaningful = self._skip_boilerplate(text)
        if not meaningful:
            return "head: empty"
        rows = [self._cap_line(row) for row in meaningful[: self.max_head_lines]]
        block = "head:\n" + "\n".join(f"- {row}" for row in rows)
        return self._cap_block(block)

    @staticmethod
    def _is_boilerplate(line: str) -> bool:
        """Return True if the line is purely legal/formatting boilerplate.

        Only copyright/license headers and @file annotations are skipped.
        Package declarations and code lines are preserved.
        Import statements are handled separately by `_skip_boilerplate`
        with a cap on the number of imported lines.
        """
        stripped = line.strip()
        if not stripped:
            return True
        if LICENSE_OR_COPYRIGHT_RE.search(stripped):
            return True
        if FILE_ANNOTATION_RE.match(stripped):
            return True
        return False

    def _skip_boilerplate(self, text: str) -> list[str]:
        """Return non-boilerplate lines, preserving relative order, up to max_head_lines.

        Skips only copyright/license headers and @file annotations.
        Package declarations and code lines are preserved.
        Import statements are capped at `max_head_import_lines` to prevent
        the head section from being consumed entirely by imports.
        Also includes any KDoc/Javadoc block that appears before the first
        meaningful line, so class-level doc is not lost.
        """
        lines = text.splitlines()
        kdoc_lines: list[str] = []
        meaningful: list[str] = []
        import_count = 0
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if self._is_boilerplate(stripped):
                if stripped.startswith("/**") or stripped.startswith("*"):
                    kdoc_lines.append(stripped)
                continue
            # Cap import lines to prevent them from dominating the head section
            if IMPORT_RE.match(stripped):
                if import_count < self.max_head_import_lines:
                    import_count += 1
                    if not meaningful and kdoc_lines:
                        meaningful.extend(kdoc_lines[:4])
                        kdoc_lines.clear()
                    meaningful.append(stripped)
                continue
            # First non-boilerplate, non-import line — flush KDoc
            if not meaningful and kdoc_lines:
                meaningful.extend(kdoc_lines[:4])
                kdoc_lines.clear()
            meaningful.append(stripped)
            if len(meaningful) >= self.max_head_lines:
                break
        if not meaningful and kdoc_lines:
            meaningful = kdoc_lines[: self.max_head_lines]
        return meaningful

    def _cap_line(self, line: str) -> str:
        if len(line) <= self.max_head_line_chars:
            return line
        return line[: self.max_head_line_chars] + TRUNCATION_MARKER

    def _cap_purpose(self, line: str) -> str:
        limit = min(self.max_head_line_chars, MAX_PURPOSE_LINE_CHARS)
        if len(line) <= limit:
            return line
        content_limit = max(limit - len(TRUNCATION_MARKER), 0)
        content = line[:content_limit].rstrip()
        if content:
            content = content.rsplit(" ", 1)[0] or content
        return content + TRUNCATION_MARKER

    def _cap_block(self, block: str) -> str:
        if len(block) <= self.max_head_block_chars:
            return block
        limit = max(self.max_head_block_chars - len(TRUNCATION_MARKER), 0)
        return block[:limit] + TRUNCATION_MARKER
