from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..config import AppConfig
from ..graph.code_graph_store import CodeGraphStore
from ..store.vector_store_factory import create_vector_store


def _format_bytes(bytes_count: int) -> str:
    """Format bytes count to human-readable string."""
    units = ["B", "KB", "MB", "GB", "TB"]
    val = float(bytes_count)
    for unit in units:
        if val < 1024.0 or unit == units[-1]:
            return f"{val:.2f} {unit}" if unit != "B" else f"{int(val)} B"
        val /= 1024.0
    return f"{val:.2f} TB"


def _dir_size(path: Path) -> int:
    """Recursively calculate directory size in bytes."""
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    try:
        for entry in os.scandir(path):
            try:
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
                elif entry.is_dir(follow_symlinks=False):
                    total += _dir_size(Path(entry.path))
            except OSError:
                continue
    except OSError:
        pass
    return total


@dataclass(slots=True)
class StoreInfo:
    provider: str
    items_count: int
    metadata: dict[str, Any]
    disk_size_bytes: int | None = None
    disk_size_human: str | None = None
    location: str | None = None


@dataclass(slots=True)
class GraphInfo:
    enabled: bool
    exists: bool
    path: str
    disk_size_bytes: int
    disk_size_human: str


@dataclass(slots=True)
class CodeDiverDirInfo:
    path: str
    exists: bool
    disk_size_bytes: int
    disk_size_human: str


@dataclass(slots=True)
class CodebaseInfo:
    root: str
    store: StoreInfo
    graph: GraphInfo
    code_diver_dir: CodeDiverDirInfo
    embedding: dict[str, Any]
    generation: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class InfoService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def get_info(self) -> CodebaseInfo:
        # 1. Vector Store info
        store_provider = self.config.storage.provider
        store_disk_size = None
        store_location = None
        items_count = 0
        metadata: dict[str, Any] = {}

        try:
            store = create_vector_store(self.config)
            items_count = store.count_items()
            metadata = store.metadata() or {}
        except Exception:
            pass

        if store_provider == "json":
            json_path = Path(self.config.artifact).expanduser()
            store_location = str(json_path)
            if json_path.exists():
                store_disk_size = json_path.stat().st_size
        elif store_provider == "qdrant":
            store_location = self.config.storage.qdrant.url
            storage_path = getattr(self.config.storage.qdrant, "storage_path", None)
            if storage_path:
                sp = Path(storage_path).expanduser()
                if sp.exists():
                    store_disk_size = _dir_size(sp)
            else:
                default_qdrant_dir = Path("~/.qdrant_storage").expanduser()
                if default_qdrant_dir.exists():
                    store_disk_size = _dir_size(default_qdrant_dir)

        store_info = StoreInfo(
            provider=store_provider,
            items_count=items_count,
            metadata=metadata,
            disk_size_bytes=store_disk_size,
            disk_size_human=_format_bytes(store_disk_size) if store_disk_size is not None else None,
            location=store_location,
        )

        # 2. Graph Store info
        raw_graph_path = Path(self.config.graph.artifact).expanduser()
        graph_path = raw_graph_path if raw_graph_path.is_absolute() else (self.config.root / raw_graph_path)
        graph_store = CodeGraphStore(graph_path)
        graph_exists = graph_store.exists()
        graph_size = graph_path.stat().st_size if graph_exists else 0
        graph_info = GraphInfo(
            enabled=self.config.graph.enabled,
            exists=graph_exists,
            path=str(raw_graph_path),
            disk_size_bytes=graph_size,
            disk_size_human=_format_bytes(graph_size),
        )

        # 3. .code-diver directory info
        cd_dir = self.config.root / ".code-diver"
        cd_exists = cd_dir.exists()
        cd_size = _dir_size(cd_dir) if cd_exists else 0
        cd_info = CodeDiverDirInfo(
            path=str(cd_dir),
            exists=cd_exists,
            disk_size_bytes=cd_size,
            disk_size_human=_format_bytes(cd_size),
        )

        # 4. Model details
        emb_info = {
            "provider": self.config.embedding.provider,
            "model": self.config.embedding.model,
            "dimensions": self.config.embedding.dimensions,
            "batch_size": self.config.embedding.batch_size,
        }
        gen_info = {
            "provider": self.config.generation.provider,
            "model": self.config.generation.model,
            "timeout_ms": self.config.generation.timeout_ms,
        }

        return CodebaseInfo(
            root=str(self.config.root.resolve()),
            store=store_info,
            graph=graph_info,
            code_diver_dir=cd_info,
            embedding=emb_info,
            generation=gen_info,
        )
