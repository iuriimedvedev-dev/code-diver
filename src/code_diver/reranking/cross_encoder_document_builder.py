from __future__ import annotations

import logging
import re
from pathlib import Path

from ..config.cross_encoder_rerank_config import CrossEncoderRerankConfig
from ..domain import SearchResult

logger = logging.getLogger(__name__)

_KDOC_OR_JAVADOC = re.compile(r"/\*\*.*?\*/", re.DOTALL)
_SOURCE_SUFFIXES = {".kt", ".kts", ".java"}

# Boilerplate patterns to skip when building CE document from source.
_LICENSE_OR_COPYRIGHT_RE = re.compile(
    r"^\s*(//|#|%|;)\s*[Cc]opyright|^\s*/\*(?!\*)|^\s*\*[^/]|^[-]{20,}"
)
_IMPORT_RE = re.compile(r"^\s*(?:from\s+[\w.]+\s+import\s+.+|import\s+[\w.,\s;]+)\s*$")
_PACKAGE_RE = re.compile(r"^\s*package\s+[\w.]+")
_FILE_ANNOTATION_RE = re.compile(r"^\s*@file:\s*")


def build_cross_encoder_document(
    result: SearchResult,
    config: CrossEncoderRerankConfig,
    repository_root: Path | None = None,
) -> str:
    """Build the text sent to the cross-encoder for one candidate.

    Default (flag off): path/title/score plus truncated indexed item content.
    H-55 (`use_file_head_document`): first `max_document_chars` of the real file,
    skipping license boilerplate and imports, preferring the first class-level
    KDoc/Javadoc or the class declaration itself.
    Missing/unreadable files fall back to the default fused text so the candidate
    is still reranked rather than dropped.
    """
    if config.use_file_head_document:
        doc = _meaningful_file_head(result, config, repository_root)
        if doc is not None:
            return doc
    return _fused_locator_document(result, config)


def _fused_locator_document(result: SearchResult, config: CrossEncoderRerankConfig) -> str:
    item = result.item
    parts = [
        f"path: {item.path}",
        f"title: {item.title}",
        f"score: {result.score:.6f}",
        "content:",
        item.content[: config.max_document_chars],
    ]
    return "\n".join(parts)


def _meaningful_file_head(
    result: SearchResult,
    config: CrossEncoderRerankConfig,
    repository_root: Path | None,
) -> str | None:
    """Return the first meaningful block from the source file for the CE.

    Skips license headers, copyright boilerplate, @file annotations,
    and import lines. Package declarations are kept — they provide useful
    module/layer signal. Returns the first KDoc/Javadoc block that appears
    before the class declaration, or the first meaningful code lines
    (class/interface/object declaration, fields, methods).
    """
    if repository_root is None:
        logger.warning(
            "use_file_head_document is on but repository_root is missing; falling back to fused text for %s",
            result.item.path,
        )
        return None
    path = (repository_root / result.item.path).resolve()
    try:
        path.relative_to(repository_root.resolve())
    except ValueError:
        logger.warning(
            "candidate path escapes repository root (%s); falling back to fused text",
            result.item.path,
        )
        return None
    if not path.is_file():
        logger.warning(
            "source file missing for CE document (%s); falling back to fused text",
            result.item.path,
        )
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning(
            "failed to read source for CE document (%s): %s; falling back to fused text",
            result.item.path,
            exc,
        )
        return None
    budget = config.max_document_chars
    meaningful = _extract_meaningful_head(text, result.item.path, budget)
    if meaningful:
        return meaningful
    return text[:budget]


def _is_boilerplate(line: str) -> bool:
    """Return True if the line is purely legal/formatting boilerplate.

    Only copyright/license headers and @file annotations are skipped.
    Package declarations, import statements, and all code lines are
    preserved — they carry useful semantic signal.
    """
    stripped = line.strip()
    if not stripped:
        return True
    if _LICENSE_OR_COPYRIGHT_RE.search(stripped):
        return True
    if _FILE_ANNOTATION_RE.match(stripped):
        return True
    return False


def _extract_meaningful_head(text: str, rel_path: str, budget: int, max_head_import_lines: int = 5) -> str:
    """Build a concise CE document from source: path + meaningful content.

    Skips boilerplate, caps import lines at `max_head_import_lines`,
    includes class-level KDoc/Javadoc if present, then the first
    meaningful code lines within the character budget.
    """
    lines = text.splitlines()
    kdoc_lines: list[str] = []
    meaningful: list[str] = []
    import_count = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _is_boilerplate(stripped):
            if stripped.startswith("/**") or stripped.startswith("*"):
                kdoc_lines.append(stripped)
            continue
        # Cap import lines to prevent them from dominating
        if _IMPORT_RE.match(stripped):
            if import_count < max_head_import_lines:
                import_count += 1
                if not meaningful and kdoc_lines:
                    meaningful.extend(kdoc_lines[:4])
                    kdoc_lines.clear()
                meaningful.append(stripped)
            continue
        if not meaningful and kdoc_lines:
            meaningful.extend(kdoc_lines[:4])
            kdoc_lines.clear()
        meaningful.append(stripped)
        # Budget check: sum of lines so far
        size = sum(len(l) + 1 for l in meaningful)
        if size >= budget:
            break
    if not meaningful and kdoc_lines:
        meaningful = kdoc_lines[: budget // 80]

    if not meaningful:
        return ""

    # Build: path line + meaningful content (no score/title — CE doesn't need them)
    result_parts = [f"path: {rel_path}", "content:"]
    char_budget = budget - sum(len(p) + 1 for p in result_parts)
    if char_budget <= 0:
        return "\n".join(result_parts) + "\n" + meaningful[0][:budget]

    content_lines: list[str] = []
    chars_used = 0
    for line in meaningful:
        line_len = len(line) + 1  # +1 for newline
        if chars_used + line_len > char_budget:
            remaining = char_budget - chars_used
            if remaining > 10:
                content_lines.append(line[:remaining])
            break
        content_lines.append(line)
        chars_used += line_len

    result_parts.append("\n".join(content_lines))
    return "\n".join(result_parts)


def _kdoc_or_javadoc(text: str, rel_path: str) -> str | None:
    suffix = Path(rel_path).suffix.lower()
    if suffix not in _SOURCE_SUFFIXES:
        return None
    match = _KDOC_OR_JAVADOC.search(text[:8000])
    if match is None:
        return None
    return match.group(0)
