from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class CodeItem:
    id: str
    path: str
    title: str
    content: str
    start_line: int | None = None
    end_line: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_embedding_text(self) -> str:
        location = self.path
        if self.start_line is not None:
            location = f"{location}:{self.start_line}"
        return f"title: {self.title} | path: {location} | text: {self.content}"

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "title": self.title,
            "content": self.content,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "metadata": self.metadata,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "CodeItem":
        item_id = data.get("id")
        path = data.get("path")
        content = data.get("content")
        if not item_id or not path or content is None:
            raise ValueError("CodeItem requires id, path, and content.")
        return cls(
            id=str(item_id),
            path=str(path),
            title=str(data.get("title") or path),
            content=str(content),
            start_line=data.get("start_line"),
            end_line=data.get("end_line"),
            metadata=dict(data.get("metadata") or {}),
        )
