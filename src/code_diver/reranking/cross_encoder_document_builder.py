from __future__ import annotations

import logging
import re
from pathlib import Path

from ..config.cross_encoder_rerank_config import CrossEncoderRerankConfig
from ..domain import SearchResult

logger = logging.getLogger(__name__)

_KDOC_OR_JAVADOC = re.compile(r"/\*\*.*?\*/", re.DOTALL)
_SOURCE_SUFFIXES = {".kt", ".kts", ".java"}


def build_cross_encoder_document(
    result: SearchResult,
    config: CrossEncoderRerankConfig,
    repository_root: Path | None = None,
) -> str:
    """Build the text sent to the cross-encoder for one candidate.

    Default (flag off): path/title/score plus truncated indexed item content.
    H-55 (`use_file_head_document`): first `max_document_chars` of the real file,
    or the first KDoc/Javadoc block when one exists near the file head.
    Missing/unreadable files fall back to the default fused text so the candidate
    is still reranked rather than dropped.
    """
    if config.use_file_head_document:
        head = _file_head_document(result, config, repository_root)
        if head is not None:
            return head
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


def _file_head_document(
    result: SearchResult,
    config: CrossEncoderRerankConfig,
    repository_root: Path | None,
) -> str | None:
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
        logger.warning("candidate path escapes repository root (%s); falling back to fused text", result.item.path)
        return None
    if not path.is_file():
        logger.warning("source file missing for CE document (%s); falling back to fused text", result.item.path)
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
    extracted = _kdoc_or_javadoc(text, result.item.path)
    if extracted:
        return extracted[:budget]
    return text[:budget]


def _kdoc_or_javadoc(text: str, rel_path: str) -> str | None:
    suffix = Path(rel_path).suffix.lower()
    if suffix not in _SOURCE_SUFFIXES:
        return None
    match = _KDOC_OR_JAVADOC.search(text[:8000])
    if match is None:
        return None
    return match.group(0)
