"""Optional native search core dual-path.

Enable with environment variable ``CODE_DIVER_NATIVE_SEARCH=1`` (default off).
When the flag is off, or the optional ``code_diver_search`` extension is missing,
callers always use the pure-Python implementations.

Champion configs must not flip this flag.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from typing import Any

logger = logging.getLogger(__name__)

_ENV_FLAG = "CODE_DIVER_NATIVE_SEARCH"
_TRUTHY = {"1", "true", "yes", "on"}

_native_module: Any | None = None
_native_load_attempted = False


def native_search_enabled() -> bool:
    """Return True only when the env flag is on (default off)."""
    raw = os.environ.get(_ENV_FLAG, "").strip().lower()
    return raw in _TRUTHY


def native_module() -> Any | None:
    """Lazy-import ``code_diver_search`` once. Returns None if unavailable."""
    global _native_module, _native_load_attempted
    if not native_search_enabled():
        return None
    if _native_load_attempted:
        return _native_module
    _native_load_attempted = True
    try:
        import code_diver_search as mod  # type: ignore[import-not-found]

        _native_module = mod
    except Exception as exc:  # pragma: no cover - missing extension is normal
        logger.debug("native search module unavailable: %s", exc)
        _native_module = None
    return _native_module


def reset_native_search_cache() -> None:
    """Test helper: clear lazy import cache."""
    global _native_module, _native_load_attempted
    _native_module = None
    _native_load_attempted = False


def fuse_hybrid_total(
    *,
    vector: float,
    lexical: float,
    path: float,
    symbol: float,
    symbol_match: float,
    graph: float,
    file_vote: float,
    vector_weight: float,
    lexical_weight: float,
    path_weight: float,
    symbol_weight: float,
    symbol_match_weight: float,
    graph_weight: float,
    file_vote_weight: float,
    python_fallback: float,
) -> float:
    """Prefer native ``fuse_hybrid_py`` when enabled; else ``python_fallback``."""
    mod = native_module()
    if mod is None:
        return python_fallback
    try:
        return float(
            mod.fuse_hybrid_py(
                vector,
                lexical,
                path,
                symbol,
                symbol_match,
                graph,
                file_vote,
                vector_weight=vector_weight,
                lexical_weight=lexical_weight,
                path_weight=path_weight,
                symbol_weight=symbol_weight,
                symbol_match_weight=symbol_match_weight,
                graph_weight=graph_weight,
                file_vote_weight=file_vote_weight,
            )
        )
    except Exception as exc:  # pragma: no cover
        logger.debug("native fuse_hybrid failed, using Python: %s", exc)
        return python_fallback


def try_propagate_file_scores(
    adjacency: Mapping[str, Sequence[tuple[str, float]]],
    seed_file_scores: Mapping[str, float],
    *,
    depth: int,
    decay: float,
    seed_limit: int,
    neighbor_limit: int,
    frontier_limit: int | None,
) -> dict[str, float] | None:
    """Native graph-file propagate, or None to signal Python fallback."""
    mod = native_module()
    if mod is None or not hasattr(mod, "propagate_file_scores_py"):
        return None
    try:
        adj = {
            str(path): [(str(n), float(w)) for n, w in neighbors]
            for path, neighbors in adjacency.items()
        }
        seeds = {str(k): float(v) for k, v in seed_file_scores.items()}
        result = mod.propagate_file_scores_py(
            adj,
            seeds,
            int(depth),
            float(decay),
            int(seed_limit),
            int(neighbor_limit),
            frontier_limit if frontier_limit is None else int(frontier_limit),
        )
        return {str(k): float(v) for k, v in dict(result).items()}
    except Exception as exc:  # pragma: no cover
        logger.debug("native propagate_file_scores failed: %s", exc)
        return None


def try_expand_adjacency(
    adjacency: Mapping[str, Sequence[tuple[str, float]]],
    seed_file_scores: Mapping[str, float],
    *,
    depth: int,
    decay: float,
    neighbor_limit: int,
    min_score: float,
) -> dict[str, float] | None:
    """Native FileGraphAdjacencyIndex.expand, or None for Python fallback."""
    mod = native_module()
    if mod is None or not hasattr(mod, "expand_adjacency_py"):
        return None
    try:
        adj = {
            str(path): [(str(n), float(w)) for n, w in neighbors]
            for path, neighbors in adjacency.items()
        }
        seeds = {str(k): float(v) for k, v in seed_file_scores.items()}
        result = mod.expand_adjacency_py(
            adj,
            seeds,
            int(depth),
            float(decay),
            int(neighbor_limit),
            float(min_score),
        )
        return {str(k): float(v) for k, v in dict(result).items()}
    except Exception as exc:  # pragma: no cover
        logger.debug("native expand_adjacency failed: %s", exc)
        return None
