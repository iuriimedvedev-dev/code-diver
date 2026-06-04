from __future__ import annotations

import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from ..config import AppConfig
from ..settings import VectorStoreProviderId


@dataclass(frozen=True, slots=True)
class QdrantRuntimeStatus:
    managed: bool
    started: bool = False
    ready: bool = False


class QdrantRuntimeManager:
    LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

    def __init__(
        self,
        config: AppConfig,
        compose_file: Path | None = None,
        service_name: str = "qdrant",
    ) -> None:
        self.config = config
        self.compose_file = compose_file or self._default_compose_file()
        self.service_name = service_name

    def should_manage(self) -> bool:
        if self.config.storage.provider != VectorStoreProviderId.QDRANT.value:
            return False
        qdrant = self.config.storage.qdrant
        if qdrant.location:
            return False
        return self._is_local_url(qdrant.url)

    def ensure_running(self, timeout_seconds: float = 90.0) -> QdrantRuntimeStatus:
        if not self.should_manage():
            return QdrantRuntimeStatus(managed=False)
        if self.is_ready():
            return QdrantRuntimeStatus(managed=True, ready=True)
        self._compose_up()
        self.wait_until_ready(timeout_seconds)
        return QdrantRuntimeStatus(managed=True, started=True, ready=True)

    def is_ready(self, timeout_seconds: float = 1.0) -> bool:
        try:
            with urllib.request.urlopen(self._collections_url(), timeout=timeout_seconds) as response:
                return 200 <= response.status < 300
        except Exception:
            return False

    def wait_until_ready(self, timeout_seconds: float) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self.is_ready(timeout_seconds=2.0):
                return
            time.sleep(1.0)
        raise RuntimeError(
            "Timed out waiting for local Qdrant. "
            f"Configured URL: {self.config.storage.qdrant.url}. "
            f"Check `docker compose -f {self.compose_file} ps {self.service_name}`."
        )

    def _compose_up(self) -> None:
        if not self.compose_file.exists():
            raise RuntimeError(
                "Local Qdrant is configured but docker-compose.yml was not found. "
                f"Expected compose file: {self.compose_file}."
            )
        command = ["docker", "compose", "-f", str(self.compose_file), "up", "-d", self.service_name]
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=False)
        except FileNotFoundError as exc:
            raise RuntimeError(
                "Local Qdrant is configured but the Docker CLI was not found. "
                "Install Docker, start Qdrant yourself, or use JSON storage for offline smoke runs."
            ) from exc
        if result.returncode != 0:
            details = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(
                "Local Qdrant is configured but Docker Compose could not start it. "
                f"Command: {' '.join(command)}. "
                f"Details: {details or 'no output'}"
            )

    def _collections_url(self) -> str:
        return self.config.storage.qdrant.url.rstrip("/") + "/collections"

    def _is_local_url(self, url: str) -> bool:
        parsed = urlparse(url)
        return (parsed.hostname or "").lower() in self.LOCAL_HOSTS

    def _default_compose_file(self) -> Path:
        return Path(__file__).resolve().parents[3] / "docker-compose.yml"
