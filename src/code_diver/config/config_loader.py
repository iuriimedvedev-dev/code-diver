from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..settings import Defaults
from .app_config import AppConfig
from .editor_config import EditorConfig
from .embedding_config import EmbeddingConfig
from .evaluation_config import EvaluationConfig
from .graph_config import GraphConfig
from .pi_config import PiConfig
from .qdrant_config import QdrantConfig
from .recursive_search_config import RecursiveSearchConfig
from .scanner_config import ScannerConfig
from .search_config import SearchConfig
from .storage_config import StorageConfig
from .ui_config import UiConfig


class ConfigLoader:
    def load(self, path: Path | None) -> AppConfig:
        config_path = path or Defaults.CONFIG_PATH
        data = self._load_yaml(config_path)
        return AppConfig(
            root=Path(data.get("root", Defaults.ROOT)),
            artifact=Path(data.get("artifact", Defaults.ARTIFACT)),
            storage=self._storage(data.get("storage")),
            embedding=self._embedding(data.get("embedding")),
            pi=self._pi(data.get("pi")),
            scanner=self._scanner(data.get("scanner")),
            search=self._search(data.get("search")),
            recursive_search=self._recursive_search(data.get("recursive_search")),
            graph=self._graph(data.get("graph")),
            ui=self._ui(data.get("ui")),
            evaluation=self._evaluation(data.get("evaluation")),
            plugins=self._string_list(data.get("plugins")),
        )

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if loaded is None:
            return {}
        if not isinstance(loaded, dict):
            raise ValueError(f"Config must be a YAML mapping: {path}")
        return loaded

    def _storage(self, data: Any) -> StorageConfig:
        mapping = self._mapping(data)
        return StorageConfig(
            provider=str(mapping.get("provider", Defaults.STORAGE_PROVIDER)),
            qdrant=self._qdrant(mapping.get("qdrant")),
        )

    def _qdrant(self, data: Any) -> QdrantConfig:
        mapping = self._mapping(data)
        return QdrantConfig(
            url=str(mapping.get("url", Defaults.QDRANT_URL)),
            location=mapping.get("location"),
            collection=str(mapping.get("collection", Defaults.QDRANT_COLLECTION)),
            api_key=mapping.get("api_key"),
            api_key_env=mapping.get("api_key_env", Defaults.QDRANT_API_KEY_ENV),
            batch_size=int(mapping.get("batch_size", Defaults.QDRANT_BATCH_SIZE)),
        )

    def _embedding(self, data: Any) -> EmbeddingConfig:
        mapping = self._mapping(data)
        return EmbeddingConfig(
            provider=str(mapping.get("provider", Defaults.EMBEDDING_PROVIDER)),
            model=mapping.get("model", Defaults.EMBEDDING_MODEL),
            dimensions=self._optional_int(mapping.get("dimensions", Defaults.EMBEDDING_DIMENSIONS)),
            api_key=mapping.get("api_key"),
            batch_size=int(mapping.get("batch_size", Defaults.EMBEDDING_BATCH_SIZE)),
        )

    def _pi(self, data: Any) -> PiConfig:
        mapping = self._mapping(data)
        return PiConfig(
            binary=str(mapping.get("binary", Defaults.PI_BINARY)),
            extension=Path(mapping.get("extension", Defaults.PI_EXTENSION)),
            prompt_template=self._optional_path(mapping.get("prompt_template", Defaults.PI_PROMPT_TEMPLATE)),
            provider=mapping.get("provider", Defaults.PI_PROVIDER),
            model=mapping.get("model", Defaults.PI_MODEL),
            tools=self._string_list(mapping.get("tools")),
            extra_args=self._string_list(mapping.get("extra_args")),
            env={str(key): str(value) for key, value in self._mapping(mapping.get("env")).items()},
        )

    def _scanner(self, data: Any) -> ScannerConfig:
        mapping = self._mapping(data)
        return ScannerConfig(
            include=self._string_list(mapping.get("include")),
            exclude=self._string_list(mapping.get("exclude")),
            max_file_bytes=int(mapping.get("max_file_bytes", Defaults.MAX_FILE_BYTES)),
            chunk_lines=int(mapping.get("chunk_lines", Defaults.CHUNK_LINES)),
        )

    def _search(self, data: Any) -> SearchConfig:
        mapping = self._mapping(data)
        return SearchConfig(
            limit=int(mapping.get("limit", Defaults.SEARCH_LIMIT)),
            preview_lines=int(mapping.get("preview_lines", Defaults.PREVIEW_LINES)),
            strategy=str(mapping.get("strategy", "vector")),
        )

    def _recursive_search(self, data: Any) -> RecursiveSearchConfig:
        mapping = self._mapping(data)
        return RecursiveSearchConfig(
            rounds=int(mapping.get("rounds", Defaults.RECURSIVE_ROUNDS)),
            branch_limit=int(mapping.get("branch_limit", Defaults.RECURSIVE_BRANCH_LIMIT)),
            limit=int(mapping.get("limit", Defaults.RECURSIVE_PER_ROUND_LIMIT)),
        )

    def _graph(self, data: Any) -> GraphConfig:
        mapping = self._mapping(data)
        return GraphConfig(
            enabled=bool(mapping.get("enabled", True)),
            artifact=Path(mapping.get("artifact", Defaults.GRAPH_ARTIFACT)),
            expansion_depth=int(mapping.get("expansion_depth", Defaults.GRAPH_EXPANSION_DEPTH)),
            neighbor_limit=int(mapping.get("neighbor_limit", Defaults.GRAPH_NEIGHBOR_LIMIT)),
        )

    def _ui(self, data: Any) -> UiConfig:
        mapping = self._mapping(data)
        return UiConfig(
            color=bool(mapping.get("color", Defaults.UI_COLOR)),
            pager=str(mapping.get("pager", Defaults.UI_PAGER)),
            links=bool(mapping.get("links", Defaults.UI_LINKS)),
            editor=self._editor(mapping.get("editor")),
        )

    def _editor(self, data: Any) -> EditorConfig:
        mapping = self._mapping(data)
        return EditorConfig(
            command=str(mapping.get("command", Defaults.EDITOR_COMMAND)),
            args=self._string_list(mapping.get("args")) or list(Defaults.EDITOR_ARGS),
        )

    def _evaluation(self, data: Any) -> EvaluationConfig:
        mapping = self._mapping(data)
        return EvaluationConfig(
            dataset=Path(mapping.get("dataset", Defaults.DATASET)),
            limit=int(mapping.get("limit", Defaults.SEARCH_LIMIT)),
        )

    def _mapping(self, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("Expected a YAML mapping.")
        return value

    def _string_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("Expected a YAML list.")
        return [str(item) for item in value]

    def _optional_int(self, value: Any) -> int | None:
        if value is None:
            return None
        return int(value)

    def _optional_path(self, value: Any) -> Path | None:
        if value is None:
            return None
        return Path(value)
