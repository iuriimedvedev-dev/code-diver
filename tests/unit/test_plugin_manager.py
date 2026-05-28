from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.domain import CodeItem
from code_diver.plugins import PluginManager


pytestmark = pytest.mark.unit


def test_plugin_manager_collects_transforms_and_prepares_query(tmp_path: Path) -> None:
    plugin = tmp_path / "plugin.py"
    plugin.write_text(
        """
def collect_items(root, config):
    yield {"id": "plugin:item", "path": "plugin.md", "title": "Plugin", "content": "plugin content"}

def transform_item(item):
    item["content"] = item["content"].upper()
    return item

def prepare_query(query):
    return query + " prepared"
""".strip(),
        encoding="utf-8",
    )

    manager = PluginManager([plugin])
    collected = manager.collect_items(tmp_path)
    transformed = manager.transform_items([CodeItem("x", "x.py", "X", "hello"), *collected])

    assert [item.content for item in transformed] == ["HELLO", "PLUGIN CONTENT"]
    assert manager.prepare_query("query") == "query prepared"
