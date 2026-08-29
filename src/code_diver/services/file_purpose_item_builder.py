from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..domain import CodeItem, CodeItemIndexKind, CodeItemMetadata, CodeSymbol

_KDOC_OR_JAVADOC = re.compile(r"/\*\*.*?\*/", re.DOTALL)

_SOURCE_SUFFIXES = frozenset({
    ".java",
    ".kt",
    ".kts",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".swift",
    ".scala",
    ".go",
    ".rs",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
})


class FilePurposeItemBuilder:
    """Extract the first meaningful KDoc/Javadoc or class-level comment as a separate purpose vector.

    H-59: If a file has a KDoc/Javadoc block before its first class/interface/object declaration,
    extract it as a dense vector under the `file_purpose` kind. This provides semantic purpose
    signal that is not diluted by path/name echo.
    If no KDoc/Javadoc exists, the item is skipped (no purpose vector for that file).
    """

    def __init__(self, max_lines: int = 30, max_chars: int = 500):
        self.max_lines = max_lines
        self.max_chars = max_chars

    def build(self, rel_path: str, text: str, symbols: list[CodeSymbol] | None = None) -> CodeItem | None:
        if not _is_source_file(rel_path):
            return None
        purpose = self._extract_purpose(text)
        if not purpose:
            return None
        truncated = self._truncate(purpose)
        digest = hashlib.sha1(f"{rel_path}:file-purpose".encode()).hexdigest()[:12]
        return CodeItem(
            id=f"{rel_path}::file_purpose#{digest}",
            path=rel_path,
            title=f"{rel_path}::file_purpose",
            content=f"file: {rel_path}\ncontent:\n{truncated}",
            metadata={
                CodeItemMetadata.SOURCE: "scanner",
                CodeItemMetadata.INDEX_KIND: CodeItemIndexKind.FILE_PURPOSE,
            },
        )

    def _extract_purpose(self, text: str) -> str | None:
        """Extract the first meaningful KDoc/Javadoc block before the first class declaration."""
        # Find the first class/interface/object/enum declaration
        class_match = re.search(
            r"^\s*(public|protected|private|internal|open|abstract|sealed|data)?"
            r"(\s+(public|protected|private|internal|open|abstract|sealed|data))*"
            r"\s+(class|interface|object|enum)",
            text,
            re.MULTILINE,
        )
        if class_match:
            # Search for KDoc before the class declaration
            pre_class = text[: class_match.start()]
            kdoc = _KDOC_OR_JAVADOC.search(pre_class)
            if kdoc:
                return kdoc.group(0).strip()
        # If no class-level KDoc, search for any KDoc in the first 8000 chars
        first_kdoc = _KDOC_OR_JAVADOC.search(text[:8000])
        if first_kdoc:
            return first_kdoc.group(0).strip()
        return None

    def _truncate(self, text: str) -> str:
        lines = text.splitlines()
        if len(lines) <= self.max_lines and len(text) <= self.max_chars:
            return text
        truncated_lines = lines[: self.max_lines]
        truncated = "\n".join(truncated_lines)
        if len(truncated) > self.max_chars:
            truncated = truncated[: self.max_chars] + " ..."
        return truncated


def _is_source_file(rel_path: str) -> bool:
    return Path(rel_path).suffix.lower() in _SOURCE_SUFFIXES