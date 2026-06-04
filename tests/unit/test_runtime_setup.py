from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.runtime import RuntimeConfigStore, RuntimeSetupWizard


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
    assert store.load().install_dir == Path(".code-diver/runtime/vllm")


def test_runtime_setup_wizard_yes_uses_default_profile(tmp_path: Path) -> None:
    store = RuntimeConfigStore(tmp_path / "runtime.yml")

    config = RuntimeSetupWizard(store=store).run(
        platform="apple-metal",
        backend="host-uv",
        install=False,
        yes=True,
    )

    assert config.embedding_profile == "qwen3-0.6b"
