from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.runtime import EmbeddingRuntimeManager, RuntimeConfig, RuntimeConfigStore, RuntimeSetupWizard


pytestmark = pytest.mark.unit


def test_runtime_setup_wizard_writes_external_runtime_without_install(tmp_path: Path) -> None:
    store = RuntimeConfigStore(tmp_path / "runtime.yml")

    config = RuntimeSetupWizard(store=store).run(
        profile_key="qwen3-0.6b",
        backend="external",
        install=False,
        yes=True,
    )

    loaded = store.load()
    assert config.backend == "external"
    assert loaded.embedding_profile == "qwen3-0.6b"
    assert loaded.backend == "external"
    assert loaded.auto_start is False


def test_runtime_setup_wizard_defaults_external_platform_to_external_backend(tmp_path: Path) -> None:
    store = RuntimeConfigStore(tmp_path / "runtime.yml")

    config = RuntimeSetupWizard(store=store).run(
        profile_key="qwen3-0.6b-vllm",
        platform="external",
        install=False,
        yes=True,
    )

    assert config.backend == "external"
    assert config.auto_start is False


def test_runtime_setup_wizard_writes_cuda_runtime_profile(tmp_path: Path) -> None:
    store = RuntimeConfigStore(tmp_path / "runtime.yml")

    config = RuntimeSetupWizard(store=store).run(
        profile_key="qwen3-0.6b-vllm",
        platform="nvidia-cuda",
        backend="host-uv",
        install=False,
        yes=True,
    )

    loaded = store.load()
    assert config.platform == "nvidia-cuda"
    assert loaded.embedding_profile == "qwen3-0.6b-vllm"
    assert loaded.backend == "host-uv"
    assert loaded.auto_start is True


def test_runtime_setup_wizard_writes_host_uv_runtime_without_install(tmp_path: Path) -> None:
    store = RuntimeConfigStore(tmp_path / "runtime.yml")

    config = RuntimeSetupWizard(store=store).run(
        profile_key="qwen3-4b",
        backend="host-uv",
        install=False,
        yes=True,
    )

    assert config.embedding_profile == "qwen3-4b"
    assert config.backend == "host-uv"
    assert config.auto_start is True
    assert store.load().install_dir == Path(".code-diver/runtime/vllm-metal")


def test_runtime_setup_wizard_yes_uses_default_profile(tmp_path: Path) -> None:
    store = RuntimeConfigStore(tmp_path / "runtime.yml")

    config = RuntimeSetupWizard(store=store).run(
        platform="apple-metal",
        backend="host-uv",
        install=False,
        yes=True,
    )

    assert config.embedding_profile == "qwen3-0.6b"


def test_runtime_config_selects_dependency_groups() -> None:
    assert RuntimeConfig("qwen3-0.6b", Path(".runtime"), platform="apple-metal").dependency_group == (
        "runtime-apple-metal"
    )
    assert RuntimeConfig("qwen3-0.6b-vllm", Path(".runtime"), platform="nvidia-cuda").dependency_group == (
        "runtime-vllm"
    )
    assert RuntimeConfig("qwen3-0.6b", Path(".runtime"), platform="external").dependency_group is None


def test_runtime_manager_uses_uv_group_for_vllm_runtime(tmp_path: Path, monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append([str(part) for part in command])
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr("subprocess.run", fake_run)
    manager = EmbeddingRuntimeManager(
        RuntimeConfig("qwen3-0.6b-vllm", tmp_path / "runtime", platform="nvidia-cuda")
    )

    manager.install()

    assert calls[0] == ["uv", "venv", str(tmp_path / "runtime"), "--python", "3.12"]
    assert "--group" in calls[1]
    assert "runtime-vllm" in calls[1]


def test_runtime_manager_uses_vllm_metal_group_for_apple_runtime(tmp_path: Path, monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append([str(part) for part in command])
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr("subprocess.run", fake_run)
    manager = EmbeddingRuntimeManager(RuntimeConfig("qwen3-0.6b", tmp_path / "runtime", platform="apple-metal"))
    monkeypatch.setattr(manager, "_python_can_import", lambda python, module: False)

    manager.install()

    assert calls[0] == ["uv", "venv", str(tmp_path / "runtime"), "--python", "3.12"]
    assert any("vllm-0.22.0.tar.gz" in " ".join(call) for call in calls)
    assert "--group" in calls[-1]
    assert "runtime-apple-metal" in calls[-1]


def test_runtime_wait_reports_process_exit_with_log(tmp_path: Path, monkeypatch) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "embedding-server.log").write_text("first\nlast failure\n", encoding="utf-8")
    manager = EmbeddingRuntimeManager(RuntimeConfig("qwen3-0.6b", tmp_path / "runtime"), log_dir=log_dir)

    monkeypatch.setattr(manager, "is_running", lambda timeout_seconds=1.0: False)

    class DeadProcess:
        returncode = 42

        def poll(self):
            return self.returncode

    with pytest.raises(RuntimeError, match="exit_code=42") as exc:
        manager.wait_until_ready(1, DeadProcess())

    assert "last failure" in str(exc.value)
