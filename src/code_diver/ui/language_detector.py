from __future__ import annotations

from pathlib import Path


class LanguageDetector:
    def detect(self, path: str) -> str:
        suffix = Path(path).suffix.lower().lstrip(".")
        if suffix == "py":
            return "python"
        if suffix in {"js", "jsx"}:
            return "javascript"
        if suffix in {"ts", "tsx"}:
            return "typescript"
        if suffix in {"yml", "yaml"}:
            return "yaml"
        if suffix in {"md", "markdown"}:
            return "markdown"
        if suffix == "sh":
            return "bash"
        if suffix:
            return suffix
        return "text"
