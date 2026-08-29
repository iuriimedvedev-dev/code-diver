from __future__ import annotations

import json
import logging
import os
import re
import ssl
import threading
import urllib.request
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
    H-57 (`use_llm_purpose_document`): LLM-generated purpose blurb (1-2 sentences)
    from the source file, cached by file path.
    H-62 (`use_enhanced_file_document`): scan the entire file for ALL KDocs,
    method signatures, and class declarations, then pick the best content.
    H-55 (`use_file_head_document`): first `max_document_chars` of the real file,
    skipping license boilerplate and imports, preferring the first class-level
    KDoc/Javadoc or the class declaration itself.
    Missing/unreadable files fall back to the default fused text so the candidate
    is still reranked rather than dropped.
    """
    if config.use_llm_purpose_document:
        doc = _llm_purpose_document(result, config, repository_root)
        if doc is not None:
            return doc
    if config.use_enhanced_file_document:
        doc = _enhanced_file_document(result, config, repository_root)
        if doc is not None:
            return doc
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


# H-62: enhanced file document — scan entire file for ALL KDocs, method signatures, class declarations

_METHOD_SIG_RE = re.compile(
    r"^\s*(public|protected|private|internal|open|override|abstract|final|static)?"
    r"(\s+(public|protected|private|internal|open|override|abstract|final|static))*"
    r"\s+(fun\s+|def\s+|fun\s+.*\(|def\s+.*\(|suspend\s+fun\s+)"
)
_CLASS_DECL_RE = re.compile(
    r"^\s*(public|protected|private|internal|open|abstract|final|sealed|data)?"
    r"(\s+(public|protected|private|internal|open|abstract|final|sealed|data))*"
    r"\s+(class|interface|object|enum|abstract\s+class|data\s+class|sealed\s+class)"
)


def _extract_all_purpose_content(text: str, rel_path: str, budget: int) -> str:
    """Extract the most informative content from the entire file.

    Scans all KDoc/Javadoc blocks, method signatures, and class declarations
    in the file, then selects the best content within the budget.
    Priority: class-level KDocs > method-level KDocs > method signatures > class declarations.
    """
    suffix = Path(rel_path).suffix.lower()
    if suffix not in _SOURCE_SUFFIXES:
        return text[:budget]

    # Find all KDoc blocks with their approximate position
    kdoc_blocks: list[tuple[int, str]] = []  # (line_number, text)
    for match in _KDOC_OR_JAVADOC.finditer(text):
        start_line = text[:match.start()].count("\n")
        kdoc_blocks.append((start_line, match.group(0)))

    lines = text.splitlines()
    method_signatures: list[str] = []
    class_declarations: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _METHOD_SIG_RE.match(stripped):
            method_signatures.append(stripped)
        elif _CLASS_DECL_RE.match(stripped):
            class_declarations.append(stripped)

    # Classify KDocs: those near the top of a file before a class decl are class-level
    class_line = len(lines)
    for line in lines:
        stripped = line.strip()
        if _CLASS_DECL_RE.match(stripped):
            class_line = lines.index(line)
            break

    class_kdocs = [k for ln, k in kdoc_blocks if ln < class_line]
    method_kdocs = [k for ln, k in kdoc_blocks if ln >= class_line]

    # Build content within budget
    result_parts = [f"path: {rel_path}", "content:"]
    header_size = sum(len(p) + 1 for p in result_parts)
    char_budget = budget - header_size
    if char_budget <= 0:
        return "\n".join(result_parts) + "\n" + (text[:budget] if text else "")

    content_lines: list[str] = []
    chars_used = 0

    def add_lines(lines_to_add: list[str]) -> None:
        nonlocal chars_used
        for line in lines_to_add:
            line_len = len(line) + 1
            if chars_used + line_len > char_budget:
                remaining = char_budget - chars_used
                if remaining > 10:
                    content_lines.append(line[:remaining])
                    chars_used = char_budget
                return
            content_lines.append(line)
            chars_used += line_len

    # Priority 1: class-level KDocs
    for kdoc in class_kdocs:
        if chars_used >= char_budget:
            break
        add_lines([kdoc])

    # Priority 2: method-level KDocs (first 3)
    for kdoc in method_kdocs[:3]:
        if chars_used >= char_budget:
            break
        add_lines([kdoc])

    # Priority 3: method signatures (first 5)
    for sig in method_signatures[:5]:
        if chars_used >= char_budget:
            break
        add_lines([sig])

    # Priority 4: class declarations (first 2)
    for decl in class_declarations[:2]:
        if chars_used >= char_budget:
            break
        add_lines([decl])

    # If nothing was extracted, fall back to first meaningful lines
    if not content_lines:
        return _extract_meaningful_head(text, rel_path, budget)

    result_parts.append("\n".join(content_lines))
    return "\n".join(result_parts)


def _enhanced_file_document(
    result: SearchResult,
    config: CrossEncoderRerankConfig,
    repository_root: Path | None,
) -> str | None:
    """Return the best content from the entire file for the CE.

    H-62: scans the entire file for ALL KDoc/Javadoc blocks, method
    signatures, and class declarations, then picks the best content
    within the budget. Falls back to fused locator if file can't be read.
    """
    if repository_root is None:
        logger.warning(
            "use_enhanced_file_document is on but repository_root is missing; "
            "falling back to fused text for %s",
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
            "source file missing for enhanced CE document (%s); falling back to fused text",
            result.item.path,
        )
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning(
            "failed to read source for enhanced CE document (%s): %s; "
            "falling back to fused text",
            result.item.path,
            exc,
        )
        return None
    budget = config.max_document_chars
    return _extract_all_purpose_content(text, result.item.path, budget)


# H-57: LLM-generated purpose blurb for CE document

_LLM_PURPOSE_ENDPOINT = "https://litellm.labs.jb.gg/v1/chat/completions"
_LLM_PURPOSE_MODEL = "gpt-4o-mini"
_PURPOSE_CACHE_FILE = "/tmp/llm_purposes_cache.json"
_PURPOSE_BATCH_SIZE = 5  # Files per LLM call


def _llm_api_key() -> str | None:
    """Return the LLM API key from environment, or None."""
    return os.environ.get("LITE_LLM_KEY") or os.environ.get("OPENAI_API_KEY")


def _load_purpose_disk_cache() -> dict[str, str]:
    """Load the persistent purpose cache from disk."""
    try:
        with open(_PURPOSE_CACHE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


# In-memory cache on top of disk cache for fast access within a session
_purpose_disk_cache: dict[str, str] = _load_purpose_disk_cache()
_purpose_in_memory_cache: dict[str, str | None] = {}
_purpose_cache_lock = threading.Lock()


def _save_purpose_disk_cache() -> None:
    """Save the persistent purpose cache to disk."""
    try:
        with open(_PURPOSE_CACHE_FILE, 'w') as f:
            json.dump(_purpose_disk_cache, f)
    except OSError as exc:
        logger.debug("Failed to save purpose cache: %s", exc)


def _generate_purpose_llm_call(file_path: str, source: str, suffix: str) -> str | None:
    """Make a single LLM call to generate a purpose blurb."""
    api_key = _llm_api_key()
    if not api_key:
        return None
    prompt = (
        f"Describe the purpose of this {suffix} file in 1-2 sentences. "
        f"Focus on what the class/file does, not its structure or path.\n\n"
        f"```{suffix}\n{source}\n```"
    )
    data = json.dumps({
        "model": _LLM_PURPOSE_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 100,
        "temperature": 0.0,
    }).encode()
    req = urllib.request.Request(
        _LLM_PURPOSE_ENDPOINT,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
        result = json.loads(resp.read())
        return result["choices"][0]["message"]["content"].strip()


def _generate_purposes_batch(file_paths: list[str]) -> dict[str, str | None]:
    """Generate purpose blurbs for a batch of files in one LLM call.

    Sends all file contents in a single prompt, gets all blurbs back.
    Falls back to individual calls if the batch call fails.
    """
    api_key = _llm_api_key()
    if not api_key:
        return {fp: None for fp in file_paths}
    # Read all files
    file_sources: list[tuple[str, str, str]] = []
    for fp in file_paths:
        path = Path(fp)
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            source = text[:2000].strip()
            if not source:
                continue
            suffix = path.suffix.lower()
            file_sources.append((fp, source, suffix))
        except OSError:
            continue
    if not file_sources:
        return {fp: None for fp in file_paths}
    # Build batch prompt: list each file with a numbered label
    lines = ["Generate a 1-2 sentence purpose description for each of these files."]
    for i, (fp, source, suffix) in enumerate(file_sources, 1):
        lines.append(f"\n--- FILE {i}: {fp} ---")
        lines.append(f"```{suffix}\n{source}\n```")
    lines.append(
        "\nRespond with one line per file in this exact format:\n"
        "FILE 1: <purpose>\nFILE 2: <purpose>\n..."
    )
    prompt = "\n".join(lines)
    try:
        data = json.dumps({
            "model": _LLM_PURPOSE_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 500,
            "temperature": 0.0,
        }).encode()
        req = urllib.request.Request(
            _LLM_PURPOSE_ENDPOINT,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            result = json.loads(resp.read())
            response_text = result["choices"][0]["message"]["content"].strip()
        # Parse response: "FILE 1: ..." lines
        purposes: dict[str, str | None] = {}
        for i, (fp, _, _) in enumerate(file_sources, 1):
            # Try to find the FILE i: line
            for line in response_text.splitlines():
                line = line.strip()
                if line.startswith(f"FILE {i}:") or line.startswith(f"file {i}:"):
                    purpose = line.split(":", 1)[1].strip()
                    purposes[fp] = purpose if purpose else None
                    break
            else:
                purposes[fp] = None
        # Fall back to individual calls for any missing files
        for fp, _, _ in file_sources:
            if fp not in purposes or purposes[fp] is None:
                try:
                    purposes[fp] = _generate_purpose_llm_call(
                        fp, dict(file_sources)[fp][1], dict(file_sources)[fp][2]
                    )
                except Exception:
                    purposes[fp] = None
        return purposes
    except Exception as exc:
        logger.debug("Batch purpose generation failed: %s; falling back to individual calls", exc)
        # Fall back to individual calls
        results: dict[str, str | None] = {}
        for fp, source, suffix in file_sources:
            try:
                results[fp] = _generate_purpose_llm_call(fp, source, suffix)
            except Exception:
                results[fp] = None
        return results


def _generate_purpose_cached(file_path: str) -> str | None:
    """Generate a purpose blurb, checking disk cache first.

    Cache hierarchy:
    1. In-memory cache (fastest)
    2. Disk cache (persistent across sessions)
    3. LLM call (slowest, then saved to both caches)
    """
    # Check in-memory cache (read-only, no lock needed for in-memory dict)
    if file_path in _purpose_in_memory_cache:
        return _purpose_in_memory_cache[file_path]
    # Check disk cache under lock
    with _purpose_cache_lock:
        if file_path in _purpose_disk_cache:
            purpose = _purpose_disk_cache[file_path]
            _purpose_in_memory_cache[file_path] = purpose
            return purpose
    # Generate via LLM (outside lock, IO-bound)
    path = Path(file_path)
    if not path.is_file():
        _purpose_in_memory_cache[file_path] = None
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        source = text[:4000].strip()
        if not source:
            _purpose_in_memory_cache[file_path] = None
            return None
        suffix = path.suffix.lower()
        purpose = _generate_purpose_llm_call(file_path, source, suffix)
    except Exception as exc:
        logger.debug("LLM purpose generation failed for %s: %s", file_path, exc)
        purpose = None
    # Save to caches under lock
    with _purpose_cache_lock:
        _purpose_in_memory_cache[file_path] = purpose
        if purpose is not None:
            _purpose_disk_cache[file_path] = purpose
            _save_purpose_disk_cache()
    return purpose


def precompute_llm_purposes(file_paths: list[str]) -> dict[str, str | None]:
    """Pre-compute purpose blurbs for a list of file paths.

    Batches files into groups of _PURPOSE_BATCH_SIZE for efficiency.
    Results are saved to the disk cache.
    Already-cached files are skipped.

    Returns dict of file_path -> purpose (None if generation failed).
    """
    # Filter out already-cached files (under lock for disk cache)
    with _purpose_cache_lock:
        uncached = [fp for fp in file_paths if fp not in _purpose_disk_cache and fp not in _purpose_in_memory_cache]
        if not uncached:
            return {fp: _purpose_disk_cache.get(fp) or _purpose_in_memory_cache.get(fp) for fp in file_paths}
    # Process in batches
    results: dict[str, str | None] = {}
    for i in range(0, len(uncached), _PURPOSE_BATCH_SIZE):
        batch = uncached[i:i + _PURPOSE_BATCH_SIZE]
        batch_results = _generate_purposes_batch(batch)
        results.update(batch_results)
        # Save to caches under lock
        with _purpose_cache_lock:
            for fp, purpose in batch_results.items():
                _purpose_in_memory_cache[fp] = purpose
                if purpose is not None:
                    _purpose_disk_cache[fp] = purpose
            _save_purpose_disk_cache()
        logger.info(
            "Pre-computed %d/%d purposes (%.0f%%)",
            min(i + _PURPOSE_BATCH_SIZE, len(uncached)),
            len(uncached),
            min(i + _PURPOSE_BATCH_SIZE, len(uncached)) / len(uncached) * 100,
        )
    # Include already-cached files (under lock)
    with _purpose_cache_lock:
        for fp in file_paths:
            if fp not in results:
                if fp in _purpose_disk_cache:
                    results[fp] = _purpose_disk_cache[fp]
                elif fp in _purpose_in_memory_cache:
                    results[fp] = _purpose_in_memory_cache[fp]
    return results


def _llm_purpose_document(
    result: SearchResult,
    config: CrossEncoderRerankConfig,
    repository_root: Path | None,
) -> str | None:
    """Return LLM-generated purpose blurb for the CE.

    H-57: reads the source file, sends it to LiteLLM (gpt-4o-mini) to
    generate a 1-2 sentence purpose description, caches by file path.
    Falls back to fused locator if LLM call fails.
    """
    if repository_root is None:
        return None
    path = (repository_root / result.item.path).resolve()
    try:
        path.relative_to(repository_root.resolve())
    except ValueError:
        return None
    if not path.is_file():
        return None
    purpose = _generate_purpose_cached(str(path))
    if purpose is None:
        return None
    # Truncate purpose to budget
    budget = config.max_document_chars
    doc = f"path: {result.item.path}\ncontent:\n{purpose}"
    if len(doc) > budget:
        doc = doc[:budget] + "..."
    return doc
