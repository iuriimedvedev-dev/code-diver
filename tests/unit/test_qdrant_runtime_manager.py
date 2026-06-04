from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.config.app_config import AppConfig
from code_diver.config.qdrant_config import QdrantConfig
from code_diver.config.storage_config import StorageConfig
from code_diver.runtime import QdrantRuntimeManager


pytestmark = pytest.mark.unit


def qdrant_config(url: str = "http://localhost:6333", location: str | None = None) -> AppConfig:
    return AppConfig(storage=StorageConfig(provider="qdrant", qdrant=QdrantConfig(url=url, location=location)))


def test_qdrant_runtime_manager_skips_embedded_storage(tmp_path: Path) -> None:
    manager = QdrantRuntimeManager(qdrant_config(location=str(tmp_path / "qdrant")))

    status = manager.ensure_running()

    assert status.managed is False


def test_qdrant_runtime_manager_skips_remote_url() -> None:
    manager = QdrantRuntimeManager(qdrant_config(url="https://qdrant.example.com"))

    status = manager.ensure_running()

    assert status.managed is False


def test_qdrant_runtime_manager_does_not_start_when_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    manager = QdrantRuntimeManager(qdrant_config(), compose_file=compose)
    calls: list[list[str]] = []

    monkeypatch.setattr(manager, "is_ready", lambda timeout_seconds=1.0: True)
    monkeypatch.setattr("subprocess.run", lambda command, **kwargs: calls.append(command))

    status = manager.ensure_running()

    assert status.managed is True
    assert status.ready is True
    assert status.started is False
    assert calls == []


def test_qdrant_runtime_manager_starts_local_compose_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    manager = QdrantRuntimeManager(qdrant_config(url="http://127.0.0.1:6333"), compose_file=compose)
    calls: list[list[str]] = []
    readiness = iter([False, True])

    def fake_run(command, **kwargs):
        calls.append([str(part) for part in command])
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(manager, "is_ready", lambda timeout_seconds=1.0: next(readiness))

    status = manager.ensure_running(timeout_seconds=1)

    assert status.managed is True
    assert status.ready is True
    assert status.started is True
    assert calls == [["docker", "compose", "-f", str(compose), "up", "-d", "qdrant"]]


def test_qdrant_runtime_manager_reports_compose_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    manager = QdrantRuntimeManager(qdrant_config(), compose_file=compose)

    def fake_run(command, **kwargs):
        return type("Result", (), {"returncode": 1, "stdout": "", "stderr": "docker is not running"})()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(manager, "is_ready", lambda timeout_seconds=1.0: False)

    with pytest.raises(RuntimeError, match="docker is not running"):
        manager.ensure_running(timeout_seconds=1)
