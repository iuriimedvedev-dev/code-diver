from __future__ import annotations

import json
from typing import Any

from .selected_index_item import SelectedIndexItem


class SelectedIndexPayloadParser:
    def parse(self, text: str) -> list[SelectedIndexItem]:
        payload = json.loads(text)
        values = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(values, list):
            raise ValueError("index-selected payload must be a JSON object with an items array.")
        return [self._item(value) for value in values]

    def _item(self, value: Any) -> SelectedIndexItem:
        if not isinstance(value, dict):
            raise ValueError("Each selected index item must be an object.")
        path = str(value.get("path") or "").strip()
        if not path:
            raise ValueError("Each selected index item requires a path.")
        return SelectedIndexItem(
            path=path,
            start_line=self._optional_int(value.get("startLine", value.get("start_line"))),
            end_line=self._optional_int(value.get("endLine", value.get("end_line"))),
            title=self._optional_string(value.get("title")),
            reason=self._optional_string(value.get("reason")),
            kind=self._optional_string(value.get("kind")),
        )

    def _optional_int(self, value: Any) -> int | None:
        if value is None or value == "":
            return None
        return int(value)

    def _optional_string(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
