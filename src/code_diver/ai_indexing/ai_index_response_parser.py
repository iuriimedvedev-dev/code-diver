from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from ..domain import CodeItem


class AiIndexResponseParser:
    def parse(self, response: str, max_items: int) -> list[CodeItem]:
        payload = json.loads(self._json_text(response))
        rows = payload.get("items")
        if not isinstance(rows, list):
            raise ValueError("AI index response must contain an items list.")
        items: list[CodeItem] = []
        for row in rows[:max_items]:
            if not isinstance(row, dict):
                continue
            item = self._item(row)
            if item is not None:
                items.append(item)
        if not items:
            raise ValueError("AI index response did not contain usable items.")
        return items

    def _item(self, row: dict[str, Any]) -> CodeItem | None:
        path = str(row.get("path") or "").strip()
        summary = str(row.get("summary") or "").strip()
        if not path or not summary:
            return None
        title = str(row.get("title") or path).strip()
        keywords = [str(value) for value in row.get("keywords") or []]
        kind = str(row.get("kind") or "other")
        start_line = self._optional_int(row.get("start_line"))
        end_line = self._optional_int(row.get("end_line"))
        digest = hashlib.sha1(f"{path}:{title}:{summary}".encode("utf-8")).hexdigest()[:12]
        content = "\n".join(
            [
                f"summary: {summary}",
                f"keywords: {', '.join(keywords)}" if keywords else "keywords:",
                f"kind: {kind}",
            ]
        )
        return CodeItem(
            id=f"ai:{path}#{digest}",
            path=path,
            title=title,
            content=content,
            start_line=start_line,
            end_line=end_line,
            metadata={"source": "ai_index", "kind": kind, "keywords": keywords},
        )

    def _json_text(self, response: str) -> str:
        stripped = response.strip()
        fenced = re.search(r"```(?:json)?\s*(.*?)```", stripped, flags=re.DOTALL)
        return fenced.group(1).strip() if fenced else stripped

    def _optional_int(self, value: Any) -> int | None:
        if value is None or value == "":
            return None
        return int(value)
