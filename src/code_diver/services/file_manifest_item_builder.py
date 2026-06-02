from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..domain import CodeItem, CodeItemIndexKind, CodeItemMetadata, CodeSymbol

PACKAGE_RE = re.compile(r"^\s*package\s+([A-Za-z_][\w.]*);?\s*$", re.MULTILINE)
IMPORT_RE = re.compile(
    r"^\s*(?:import\s+(?:static\s+)?[A-Za-z_][\w.*]*(?:\s+as\s+[A-Za-z_][\w]*)?;?"
    r"|from\s+[\w.]+\s+import\s+.+)\s*$",
    re.MULTILINE,
)
CONFIG_KEY_RE = re.compile(r"^\s*([A-Za-z_][\w.-]{1,120})\s*[:=]", re.MULTILINE)
XML_NAME_RE = re.compile(r"<\s*([A-Za-z_][\w.-]*)(?:\s|>|/)")
PATH_SPLIT_RE = re.compile(r"[^A-Za-z0-9]+")


class FileManifestItemBuilder:
    def __init__(self, max_imports: int = 20, max_symbols: int = 80, max_config_keys: int = 80):
        self.max_imports = max_imports
        self.max_symbols = max_symbols
        self.max_config_keys = max_config_keys

    def build(self, rel_path: str, text: str, symbols: list[CodeSymbol]) -> CodeItem:
        digest = hashlib.sha1(f"{rel_path}:file-manifest".encode("utf-8")).hexdigest()[:12]
        content = "\n".join(
            [
                f"file: {rel_path}",
                f"filename: {Path(rel_path).name}",
                f"extension: {Path(rel_path).suffix.lower()}",
                self._path_section(rel_path),
                self._package_section(text),
                self._symbols_section(symbols),
                self._imports_section(text),
                self._config_section(rel_path, text),
            ]
        ).strip()
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
