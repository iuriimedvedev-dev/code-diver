from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..settings import SchemaKey


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
            SchemaKey.ID.value: self.id,
            SchemaKey.PATH.value: self.path,
            SchemaKey.TITLE.value: self.title,
            SchemaKey.CONTENT.value: self.content,
            SchemaKey.START_LINE.value: self.start_line,
            SchemaKey.END_LINE.value: self.end_line,
            SchemaKey.METADATA.value: self.metadata,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "CodeItem":
        item_id = data.get(SchemaKey.ID.value)
        path = data.get(SchemaKey.PATH.value)
        content = data.get(SchemaKey.CONTENT.value)
        if not item_id or not path or content is None:
            raise ValueError("CodeItem requires id, path, and content.")
        return cls(
            id=str(item_id),
            path=str(path),
            title=str(data.get(SchemaKey.TITLE.value) or path),
            content=str(content),
            start_line=data.get(SchemaKey.START_LINE.value),
            end_line=data.get(SchemaKey.END_LINE.value),
            metadata=dict(data.get(SchemaKey.METADATA.value) or {}),
        )
