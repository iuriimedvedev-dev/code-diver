from __future__ import annotations

from enum import StrEnum


class PluginHook(StrEnum):
    COLLECT_ITEMS = "collect_items"
    PREPARE_QUERY = "prepare_query"
    TRANSFORM_ITEM = "transform_item"
