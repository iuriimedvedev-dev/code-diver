from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_diver.cli import main
from code_diver.config import ConfigLoader


pytestmark = [pytest.mark.e2e, pytest.mark.protogen]

CONFIG_PATH = Path("configs/protogen.yml")
AI_CONFIG_PATH = Path("configs/protogen-ai.yml")
PROTOGEN_ROOT = Path("../protogen")


def protogen_available() -> bool:
    return (PROTOGEN_ROOT / "pyproject.toml").exists() and (PROTOGEN_ROOT / "src").is_dir()


@pytest.mark.skipif(not protogen_available(), reason="../protogen is not available")
def test_protogen_config_targets_external_repo() -> None:
    config = ConfigLoader().load(CONFIG_PATH)

    assert config.root == PROTOGEN_ROOT
    assert config.artifact == Path(".code-diver/protogen-index.json")
    assert config.embedding.provider == "hash"
    assert "src/**/*.py" in config.scanner.include
    assert "src/templates/**" in config.scanner.exclude
    assert config.evaluation.dataset == Path("datasets/protogen_eval.jsonl")
    assert config.experiments.suite == "protogen-local"
    assert config.experiments.strategies == ["vector", "recursive", "graph"]
    assert config.metrics.enabled is True
    assert config.metrics.docker_container == "code-diver-clickhouse"

    ai_config = ConfigLoader().load(AI_CONFIG_PATH)
    assert ai_config.root == PROTOGEN_ROOT
    assert ai_config.indexing.mode == "orchestrated"
    assert ai_config.embedding.provider == "gemini"
    assert ai_config.embedding.model == "gemini-embedding-2"
    assert ai_config.generation.model == "gemini-3.5-flash"
    assert ai_config.generation.api_version == "v1alpha"


@pytest.mark.skipif(not protogen_available(), reason="../protogen is not available")
def test_protogen_read_only_inspection_commands(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--config", str(CONFIG_PATH), "tree", "--path", "src", "--limit", "25", "--depth", "2"]) == 0
    tree_output = capsys.readouterr().out
    assert "src" in tree_output

    assert main(["--config", str(CONFIG_PATH), "grep", "class OpenRouterSettings", "--path", "src/config/settings.py"]) == 0
    grep_output = capsys.readouterr().out
    assert "src/config/settings.py" in grep_output
    assert "OpenRouterSettings" in grep_output


@pytest.mark.skipif(not protogen_available(), reason="../protogen is not available")
def test_protogen_index_and_evaluate(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--config", str(CONFIG_PATH), "index"]) == 0
    index_output = capsys.readouterr().out
    assert "Indexed" in index_output
    assert Path(".code-diver/protogen-index.json").exists()

    assert main(["--config", str(CONFIG_PATH), "evaluate", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["metrics"]["cases"] == 10
    assert f"hit_rate@10" in payload["metrics"]
