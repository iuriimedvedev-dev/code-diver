from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..settings import Defaults
from .app_config import AppConfig
from .editor_config import EditorConfig
from .embedding_config import EmbeddingConfig
from .env_file_config import EnvFileConfig
from .evaluation_config import EvaluationConfig
from .experiments_config import ExperimentsConfig
from .generation_config import GenerationConfig
from .graph_config import GraphConfig
from .ai_index_config import AiIndexConfig
from .indexing_config import IndexingConfig
from .metrics_config import MetricsConfig
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
            env_file=self._env_file(data.get("env_file")),
            storage=self._storage(data.get("storage")),
            embedding=self._embedding(data.get("embedding")),
            generation=self._generation(data.get("generation")),
            indexing=self._indexing(data.get("indexing")),
            pi=self._pi(data.get("pi")),
            scanner=self._scanner(data.get("scanner")),
            search=self._search(data.get("search")),
            recursive_search=self._recursive_search(data.get("recursive_search")),
            graph=self._graph(data.get("graph")),
            ui=self._ui(data.get("ui")),
            evaluation=self._evaluation(data.get("evaluation")),
            experiments=self._experiments(data.get("experiments")),
            metrics=self._metrics(data.get("metrics")),
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

    def _env_file(self, data: Any) -> EnvFileConfig:
        if isinstance(data, str):
            return EnvFileConfig(path=Path(data))
        mapping = self._mapping(data)
        return EnvFileConfig(
            path=Path(mapping.get("path", Defaults.ENV_FILE)),
            override=bool(mapping.get("override", False)),
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
            url=mapping.get("url"),
            batch_size=int(mapping.get("batch_size", Defaults.EMBEDDING_BATCH_SIZE)),
            retry_attempts=int(mapping.get("retry_attempts", Defaults.EMBEDDING_RETRY_ATTEMPTS)),
            retry_delay_seconds=float(mapping.get("retry_delay_seconds", Defaults.EMBEDDING_RETRY_DELAY_SECONDS)),
        )

    def _generation(self, data: Any) -> GenerationConfig:
        mapping = self._mapping(data)
        return GenerationConfig(
            provider=str(mapping.get("provider", Defaults.GENERATION_PROVIDER)),
            model=str(mapping.get("model", Defaults.GENERATION_MODEL)),
            fallback_models=self._string_list(mapping.get("fallback_models"))
            or list(Defaults.GENERATION_FALLBACK_MODELS),
            api_key=mapping.get("api_key"),
            url=mapping.get("url"),
            temperature=float(mapping.get("temperature", Defaults.GENERATION_TEMPERATURE)),
            thinking_budget=self._optional_int(mapping.get("thinking_budget", Defaults.GENERATION_THINKING_BUDGET)),
            api_version=mapping.get("api_version", Defaults.GENERATION_API_VERSION),
        )

    def _indexing(self, data: Any) -> IndexingConfig:
        mapping = self._mapping(data)
        return IndexingConfig(
            mode=str(mapping.get("mode", Defaults.INDEXING_MODE)),
            ai=self._ai_index(mapping.get("ai")),
        )

    def _ai_index(self, data: Any) -> AiIndexConfig:
        mapping = self._mapping(data)
        return AiIndexConfig(
            max_files=int(mapping.get("max_files", Defaults.AI_INDEX_MAX_FILES)),
            max_items=int(mapping.get("max_items", Defaults.AI_INDEX_MAX_ITEMS)),
            max_context_chars=int(mapping.get("max_context_chars", Defaults.AI_INDEX_MAX_CONTEXT_CHARS)),
            tree_depth=int(mapping.get("tree_depth", Defaults.AI_INDEX_TREE_DEPTH)),
            tree_limit=int(mapping.get("tree_limit", Defaults.AI_INDEX_TREE_LIMIT)),
            discovery_limit=int(mapping.get("discovery_limit", Defaults.AI_INDEX_DISCOVERY_LIMIT)),
            discovery_patterns=self._string_list(mapping.get("discovery_patterns"))
            or list(Defaults.AI_INDEX_DISCOVERY_PATTERNS),
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

    def _experiments(self, data: Any) -> ExperimentsConfig:
        mapping = self._mapping(data)
        return ExperimentsConfig(
            suite=str(mapping.get("suite", Defaults.EXPERIMENT_SUITE)),
            strategies=self._string_list(mapping.get("strategies")) or list(Defaults.EXPERIMENT_STRATEGIES),
        )

    def _metrics(self, data: Any) -> MetricsConfig:
        mapping = self._mapping(data)
        return MetricsConfig(
            enabled=bool(mapping.get("enabled", Defaults.METRICS_ENABLED)),
            url=str(mapping.get("url", Defaults.CLICKHOUSE_URL)),
            database=str(mapping.get("database", Defaults.CLICKHOUSE_DATABASE)),
            username=str(mapping.get("username", Defaults.CLICKHOUSE_USERNAME)),
            password=str(mapping.get("password", Defaults.CLICKHOUSE_PASSWORD)),
            docker_container=mapping.get("docker_container"),
            metrics_table=str(mapping.get("metrics_table", Defaults.CLICKHOUSE_METRICS_TABLE)),
            cases_table=str(mapping.get("cases_table", Defaults.CLICKHOUSE_CASES_TABLE)),
            timeout_seconds=float(mapping.get("timeout_seconds", Defaults.CLICKHOUSE_TIMEOUT_SECONDS)),
            retention_days=int(mapping.get("retention_days", Defaults.CLICKHOUSE_RETENTION_DAYS)),
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
