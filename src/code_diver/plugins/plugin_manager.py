from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable

from ..domain import CodeItem
from .plugin_error import PluginError


class PluginManager:
    def __init__(self, plugin_paths: list[Path] | None = None):
        self.modules = [self._load_module(path) for path in plugin_paths or []]

    def collect_items(self, root: Path, config: dict[str, Any] | None = None) -> list[CodeItem]:
        items: list[CodeItem] = []
        for module in self.modules:
            hook = getattr(module, "collect_items", None)
            if hook is None:
                continue
            try:
                raw_items = hook(root, config or {})
            except Exception as exc:  # pragma: no cover - plugin code is external
                raise PluginError(f"{module.__name__}.collect_items failed: {exc}") from exc
            items.extend(self._coerce_items(raw_items))
        return items

    def transform_items(self, items: list[CodeItem]) -> list[CodeItem]:
        transformed = items
        for module in self.modules:
            hook = getattr(module, "transform_item", None)
            if hook is None:
                continue
            next_items: list[CodeItem] = []
            for item in transformed:
                try:
                    raw = hook(item.to_json())
                except Exception as exc:  # pragma: no cover - plugin code is external
                    raise PluginError(f"{module.__name__}.transform_item failed for {item.id}: {exc}") from exc
                if raw is None:
                    continue
                next_items.append(self._coerce_item(raw))
            transformed = next_items
        return transformed

    def prepare_query(self, query: str) -> str:
        prepared = query
        for module in self.modules:
            hook = getattr(module, "prepare_query", None)
            if hook is None:
                continue
            try:
                prepared = str(hook(prepared))
            except Exception as exc:  # pragma: no cover - plugin code is external
                raise PluginError(f"{module.__name__}.prepare_query failed: {exc}") from exc
        return prepared

    def _load_module(self, path: Path) -> ModuleType:
        path = path.resolve()
        if not path.exists():
            raise PluginError(f"Plugin file does not exist: {path}")
        module_name = f"code_diver_plugin_{abs(hash(path))}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise PluginError(f"Unable to load plugin: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _coerce_items(self, raw_items: Iterable[Any]) -> list[CodeItem]:
        return [self._coerce_item(raw) for raw in raw_items]

    def _coerce_item(self, raw: Any) -> CodeItem:
        if isinstance(raw, CodeItem):
            return raw
        if not isinstance(raw, dict):
            raise PluginError(f"Plugin item must be a dict or CodeItem, got {type(raw).__name__}")
        return CodeItem.from_json(
            {
                "id": raw.get("id"),
                "path": raw.get("path"),
                "title": raw.get("title") or raw.get("path"),
                "content": raw.get("content"),
                "start_line": raw.get("start_line"),
                "end_line": raw.get("end_line"),
                "metadata": raw.get("metadata") or {},
            }
        )
