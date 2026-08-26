from __future__ import annotations

import re
from typing import Any


def load_datasets_module() -> Any:
    try:
        import datasets
    except ImportError as exc:
        raise RuntimeError(
            "The benchmark downloader needs the `datasets` package. "
            "Install the benchmark extra with `uv sync --extra benchmarks` and retry."
        ) from exc
    return datasets


def extension_for_language(language: str) -> str:
    return {
        "go": ".go",
        "java": ".java",
        "javascript": ".js",
        "php": ".php",
        "python": ".py",
        "ruby": ".rb",
    }.get(language, f".{language}")


def slugify(text: str, max_length: int = 80) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("._-").lower()
    return slug[:max_length]
