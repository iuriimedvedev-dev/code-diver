from __future__ import annotations

import hashlib

from ..domain import CodeItem, CodeItemIndexKind, CodeItemMetadata
from .documentation_metadata_extractor import DocumentationMetadataExtractor


class DocumentationSummaryItemBuilder:
    def __init__(self, extractor: DocumentationMetadataExtractor | None = None):
        self.extractor = extractor or DocumentationMetadataExtractor()

    def build(self, rel_path: str, text: str) -> CodeItem:
        metadata = self.extractor.extract(rel_path, text)
        digest = hashlib.sha1(f"{rel_path}:doc-summary".encode()).hexdigest()[:12]
        content = "\n".join(
            [
                f"doc: {rel_path}",
                f"title: {metadata['title']}",
                f"role: {metadata['role']}",
                self._list_section("headings", metadata["headings"]),
                self._list_section("commands", metadata["commands"]),
                self._list_section("facts", metadata["facts"]),
                "compact_summary:",
                str(metadata["summary"]),
            ]
        ).strip()
        return CodeItem(
            id=f"{rel_path}::doc_summary#{digest}",
            path=rel_path,
            title=f"{rel_path}::doc_summary",
            content=content,
            start_line=1,
            end_line=max(1, len(text.splitlines())),
            metadata={
                CodeItemMetadata.SOURCE: "scanner",
                CodeItemMetadata.INDEX_KIND: CodeItemIndexKind.DOC_SUMMARY,
                CodeItemMetadata.KIND: "documentation",
                "doc_role": metadata["role"],
                "doc_title": metadata["title"],
            },
        )

    def _list_section(self, label: str, values: object) -> str:
        rows = values if isinstance(values, list) else []
        if not rows:
            return f"{label}: none"
        return f"{label}:\n" + "\n".join(f"- {row}" for row in rows)
