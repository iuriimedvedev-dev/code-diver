from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..domain import CodeItem, CodeItemIndexKind, CodeItemMetadata
from .documentation_metadata_extractor import DocumentationMetadataExtractor

PATH_SPLIT_RE = re.compile(r"[^A-Za-z0-9]+")


class DocumentationManifestItemBuilder:
    def __init__(self, extractor: DocumentationMetadataExtractor | None = None):
        self.extractor = extractor or DocumentationMetadataExtractor()

    def build(self, rel_path: str, text: str) -> CodeItem:
        metadata = self.extractor.extract(rel_path, text)
        digest = hashlib.sha1(f"{rel_path}:doc-manifest".encode("utf-8")).hexdigest()[:12]
        content = "\n".join(
            [
                f"doc: {rel_path}",
                f"filename: {Path(rel_path).name}",
                f"extension: {Path(rel_path).suffix.lower()}",
                f"title: {metadata['title']}",
                f"role: {metadata['role']}",
                self._path_section(rel_path),
                self._list_section("headings", metadata["headings"]),
                self._list_section("links", metadata["links"]),
                self._list_section("code_languages", metadata["code_languages"]),
            ]
        ).strip()
        return CodeItem(
            id=f"{rel_path}::doc_manifest#{digest}",
            path=rel_path,
            title=f"{rel_path}::doc_manifest",
            content=content,
            start_line=1,
            end_line=max(1, len(text.splitlines())),
            metadata={
                CodeItemMetadata.SOURCE: "scanner",
                CodeItemMetadata.INDEX_KIND: CodeItemIndexKind.DOC_MANIFEST,
                CodeItemMetadata.KIND: "documentation",
                "doc_role": metadata["role"],
                "doc_title": metadata["title"],
            },
        )

    def _path_section(self, rel_path: str) -> str:
        parts = [part for part in Path(rel_path).parts if part]
        tokens = self._unique(token.lower() for token in PATH_SPLIT_RE.split(" ".join(parts)) if len(token) >= 2)
        return "\n".join(
            [
                f"directories: {' / '.join(parts[:-1]) or 'none'}",
                "path_tokens: " + (" ".join(tokens) if tokens else "none"),
            ]
        )

    def _list_section(self, label: str, values: object) -> str:
        rows = values if isinstance(values, list) else []
        if not rows:
            return f"{label}: none"
        return f"{label}:\n" + "\n".join(f"- {row}" for row in rows)

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
