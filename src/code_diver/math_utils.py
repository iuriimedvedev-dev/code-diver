from __future__ import annotations

import math
from typing import Any

_native_module: Any = None
_native_loaded = False


def _get_native() -> Any | None:
    global _native_module, _native_loaded
    if _native_loaded:
        return _native_module
    _native_loaded = True
    try:
        import code_diver_search as mod

        if hasattr(mod, "normalize_py") and hasattr(mod, "dot_py"):
            _native_module = mod
    except Exception:
        _native_module = None
    return _native_module


def normalize(vector: list[float]) -> list[float]:
    mod = _get_native()
    if mod is not None:
        try:
            return list(mod.normalize_py(vector))
        except Exception:
            pass
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def dot(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError(f"Vector dimension mismatch: {len(left)} != {len(right)}")
    mod = _get_native()
    if mod is not None:
        try:
            return float(mod.dot_py(left, right))
        except Exception:
            pass
    return sum(a * b for a, b in zip(left, right, strict=True))
