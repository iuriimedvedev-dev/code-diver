from __future__ import annotations

import ast
import hashlib
import re
import warnings
from pathlib import Path

from ..domain import CodeItem, CodeItemIndexKind, CodeItemMetadata, CodeSymbol

IDENTIFIER_SPLIT_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|[^A-Za-z0-9]+")
COMMENT_PREFIX_RE = re.compile(r"^\s*(?://+|#+|\*+)\s?")
GENERIC_CALL_RE = re.compile(r"\b([A-Za-z_][\w.]{1,160})\s*\(")
GENERIC_ATTRIBUTE_RE = re.compile(r"\b([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*){1,5})\b")
QUOTED_TEXT_RE = re.compile(r"['\"]([^'\"]{2,180})['\"]")
URL_RE = re.compile(r"\b(?:https?|s3|gs|wasbs?|hdfs|file)://[^\s'\"<>]+", re.IGNORECASE)
DOMAIN_RE = re.compile(r"\b[A-Za-z0-9][A-Za-z0-9.-]{1,120}\.[A-Za-z]{2,12}\b")

EFFECT_KEYWORDS = {
    "auth": ("auth", "authorize", "authentication", "permission", "token", "jwt", "login", "credential"),
    "database": ("db", "database", "sql", "query", "session", "metadata", "drop", "create", "insert", "select"),
    "network": ("http", "https", "request", "response", "url", "uri", "socket", "api", "client"),
    "filesystem": ("file", "path", "open", "read", "write", "upload", "download", "stream", "blob"),
    "process": ("process", "subprocess", "terminate", "kill", "run", "execute", "command", "ffmpeg"),
    "message": ("slack", "queue", "message", "publish", "subscribe", "notify", "event"),
    "config": ("config", "setting", "option", "env", "environment", "yaml", "json", "toml"),
}


class FileApiManifestItemBuilder:
    def __init__(
        self,
        max_symbols: int = 96,
        max_identifier_terms: int = 120,
        max_call_terms: int = 80,
        max_attribute_terms: int = 80,
        max_resource_terms: int = 80,
        max_effect_tags: int = 24,
        max_doc_hints: int = 24,
        max_doc_hint_chars: int = 180,
    ):
        self.max_symbols = max_symbols
        self.max_identifier_terms = max_identifier_terms
        self.max_call_terms = max_call_terms
        self.max_attribute_terms = max_attribute_terms
        self.max_resource_terms = max_resource_terms
        self.max_effect_tags = max_effect_tags
        self.max_doc_hints = max_doc_hints
        self.max_doc_hint_chars = max_doc_hint_chars

    def build(self, rel_path: str, text: str, symbols: list[CodeSymbol]) -> CodeItem:
        digest = hashlib.sha1(f"{rel_path}:file-api-manifest".encode("utf-8")).hexdigest()[:12]
        call_terms = self._call_terms(rel_path, text)
        attribute_terms = self._attribute_terms(rel_path, text)
        resource_terms = self._resource_terms(text)
        effect_tags = self._effect_tags(rel_path, symbols, call_terms, attribute_terms, resource_terms)
        content = "\n".join(
            [
                f"file: {rel_path}",
                f"filename: {Path(rel_path).name}",
                f"extension: {Path(rel_path).suffix.lower()}",
                self._symbol_count_section(symbols),
                self._api_section(symbols),
                self._identifier_terms_section(rel_path, symbols),
                self._terms_section("call_terms", call_terms, self.max_call_terms),
                self._terms_section("attribute_terms", attribute_terms, self.max_attribute_terms),
                self._terms_section("resource_terms", resource_terms, self.max_resource_terms),
                self._terms_section("effect_tags", effect_tags, self.max_effect_tags),
                self._doc_hints_section(rel_path, text, symbols),
            ]
        ).strip()
        return CodeItem(
            id=f"{rel_path}::file_api_manifest#{digest}",
            path=rel_path,
            title=f"{rel_path}::file_api_manifest",
            content=content,
            metadata={
                CodeItemMetadata.SOURCE: "scanner",
                CodeItemMetadata.INDEX_KIND: CodeItemIndexKind.FILE_API_MANIFEST,
            },
        )

    def _symbol_count_section(self, symbols: list[CodeSymbol]) -> str:
        if not symbols:
            return "symbol_count: 0"
        kinds: dict[str, int] = {}
        for symbol in symbols:
            kinds[symbol.kind] = kinds.get(symbol.kind, 0) + 1
        counts = ", ".join(f"{kind}={count}" for kind, count in sorted(kinds.items()))
        return f"symbol_count: {len(symbols)} ({counts})"

    def _api_section(self, symbols: list[CodeSymbol]) -> str:
        if not symbols:
            return "api_symbols: none"
        rows = [
            f"- {symbol.kind} {symbol.name}: {self._compact_signature(symbol.signature)}"
            for symbol in symbols[: self.max_symbols]
        ]
        return "api_symbols:\n" + "\n".join(rows)

    def _identifier_terms_section(self, rel_path: str, symbols: list[CodeSymbol]) -> str:
        values = [Path(rel_path).stem, *Path(rel_path).parts]
        for symbol in symbols[: self.max_symbols]:
            values.extend([symbol.name, symbol.signature])
        terms = self._unique_terms(values)[: self.max_identifier_terms]
        if not terms:
            return "identifier_terms: none"
        return "identifier_terms: " + " ".join(terms)

    def _call_terms(self, rel_path: str, text: str) -> list[str]:
        suffix = Path(rel_path).suffix.lower()
        if suffix == ".py":
            tree = self._python_tree(text)
            if tree is not None:
                names = [self._python_call_name(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)]
                return self._unique_terms([name for name in names if name])
        return self._unique_terms(match.group(1) for match in GENERIC_CALL_RE.finditer(text))

    def _attribute_terms(self, rel_path: str, text: str) -> list[str]:
        suffix = Path(rel_path).suffix.lower()
        if suffix == ".py":
            tree = self._python_tree(text)
            if tree is not None:
                values = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.Attribute):
                        values.append(self._python_attribute_name(node))
                    elif isinstance(node, ast.Import):
                        values.extend(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        values.append(node.module)
                        values.extend(f"{node.module}.{alias.name}" for alias in node.names)
                return self._unique_terms([value for value in values if value])
        return self._unique_terms(match.group(1) for match in GENERIC_ATTRIBUTE_RE.finditer(text))

    def _resource_terms(self, text: str) -> list[str]:
        values: list[str] = []
        values.extend(URL_RE.findall(text))
        values.extend(DOMAIN_RE.findall(text))
        for match in QUOTED_TEXT_RE.finditer(text):
            value = match.group(1)
            if self._looks_resource_like(value):
                values.append(value)
        return self._unique_terms(values)

    def _effect_tags(
        self,
        rel_path: str,
        symbols: list[CodeSymbol],
        call_terms: list[str],
        attribute_terms: list[str],
        resource_terms: list[str],
    ) -> list[str]:
        values = [rel_path, *(symbol.name for symbol in symbols[: self.max_symbols])]
        values.extend(symbol.signature for symbol in symbols[: self.max_symbols])
        values.extend(call_terms)
        values.extend(attribute_terms)
        values.extend(resource_terms)
        haystack = " ".join(self._unique_terms(values))
        tags = [
            tag
            for tag, keywords in EFFECT_KEYWORDS.items()
            if any(keyword in haystack for keyword in keywords)
        ]
        return tags

    def _terms_section(self, label: str, terms: list[str], limit: int) -> str:
        rows = terms[:limit]
        if not rows:
            return f"{label}: none"
        return f"{label}: " + " ".join(rows)

    def _doc_hints_section(self, rel_path: str, text: str, symbols: list[CodeSymbol]) -> str:
        hints = self._doc_hints(rel_path, text, symbols)[: self.max_doc_hints]
        if not hints:
            return "doc_hints: none"
        return "doc_hints:\n" + "\n".join(f"- {hint}" for hint in hints)

    def _doc_hints(self, rel_path: str, text: str, symbols: list[CodeSymbol]) -> list[str]:
        suffix = Path(rel_path).suffix.lower()
        if suffix == ".py":
            return self._python_doc_hints(text)
        return self._nearby_comment_hints(text, symbols)

    def _python_doc_hints(self, text: str) -> list[str]:
        tree = self._python_tree(text)
        if tree is None:
            return []
        hints: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            docstring = ast.get_docstring(node, clean=True)
            if not docstring:
                continue
            name = getattr(node, "name", "symbol")
            hints.append(self._compact_hint(f"{name}: {docstring}"))
        return self._unique_rows(hints)

    def _nearby_comment_hints(self, text: str, symbols: list[CodeSymbol]) -> list[str]:
        lines = text.splitlines()
        hints: list[str] = []
        for symbol in symbols[: self.max_symbols]:
            start = max(0, symbol.start_line - 5)
            end = max(0, symbol.start_line - 1)
            comments = []
            for line in lines[start:end]:
                stripped = COMMENT_PREFIX_RE.sub("", line).strip(" */")
                if stripped:
                    comments.append(stripped)
            if comments:
                hints.append(self._compact_hint(f"{symbol.name}: {' '.join(comments)}"))
        return self._unique_rows(hints)

    def _python_tree(self, text: str) -> ast.AST | None:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                return ast.parse(text)
        except SyntaxError:
            return None

    def _python_call_name(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            owner = self._python_call_name(node.value)
            return f"{owner}.{node.attr}" if owner else node.attr
        if isinstance(node, ast.Call):
            return self._python_call_name(node.func)
        return None

    def _python_attribute_name(self, node: ast.Attribute) -> str | None:
        owner = self._python_call_name(node.value)
        return f"{owner}.{node.attr}" if owner else node.attr

    def _looks_resource_like(self, value: str) -> bool:
        lowered = value.lower()
        if URL_RE.search(value) or DOMAIN_RE.search(value):
            return True
        separators = ("/", ".", "-", "_", ":")
        resource_words = (
            "http",
            "api",
            "sql",
            "select",
            "insert",
            "update",
            "delete",
            "file",
            "path",
            "bucket",
            "blob",
            "stream",
            "token",
            "auth",
            "db",
        )
        return any(separator in value for separator in separators) and any(word in lowered for word in resource_words)

    def _compact_signature(self, signature: str) -> str:
        return " ".join(signature.split())[:240] if signature else "none"

    def _compact_hint(self, value: str) -> str:
        return " ".join(value.split())[: self.max_doc_hint_chars]

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
            key = row.lower()
            if not row or key in seen:
                continue
            seen.add(key)
            unique_rows.append(row)
        return unique_rows
