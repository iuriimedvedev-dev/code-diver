from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.config import ConfigLoader


pytestmark = pytest.mark.unit


def test_config_loader_maps_yaml_to_typed_config(tmp_path: Path) -> None:
    config_path = tmp_path / "code-diver.yml"
    config_path.write_text(
        f"""
root: {tmp_path}/repo
artifact: {tmp_path}/index.json
storage:
  provider: qdrant
  qdrant:
    location: ":memory:"
    collection: custom_collection
embedding:
  provider: hash
  dimensions: 64
pi:
  binary: pi-dev
  tools: [read, code_diver_search]
scanner:
  include: ["*.py"]
  chunk_lines: 10
search:
  strategy: recursive
  limit: 7
recursive_search:
  rounds: 3
  branch_limit: 2
  limit: 4
graph:
  artifact: {tmp_path}/graph.json
  expansion_depth: 2
ui:
  editor:
    command: vim
    args: ["+{{line}}", "{{path}}"]
evaluation:
  dataset: {tmp_path}/eval.jsonl
plugins:
  - plugin.py
""".strip(),
        encoding="utf-8",
    )

    config = ConfigLoader().load(config_path)

    assert config.root == tmp_path / "repo"
    assert config.storage.provider == "qdrant"
    assert config.storage.qdrant.location == ":memory:"
    assert config.storage.qdrant.collection == "custom_collection"
    assert config.embedding.provider == "hash"
    assert config.embedding.dimensions == 64
    assert config.pi.binary == "pi-dev"
    assert config.pi.tools == ["read", "code_diver_search"]
    assert config.scanner.include == ["*.py"]
    assert config.scanner.chunk_lines == 10
    assert config.search.strategy == "recursive"
    assert config.search.limit == 7
    assert config.recursive_search.rounds == 3
    assert config.recursive_search.branch_limit == 2
    assert config.recursive_search.limit == 4
    assert config.graph.artifact == tmp_path / "graph.json"
    assert config.graph.expansion_depth == 2
    assert config.ui.editor.command == "vim"
    assert config.ui.editor.args == ["+{line}", "{path}"]
    assert config.evaluation.dataset == tmp_path / "eval.jsonl"
    assert config.plugins == ["plugin.py"]


def test_config_loader_rejects_non_mapping_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "code-diver.yml"
    config_path.write_text("- not\n- a\n- mapping\n", encoding="utf-8")

    with pytest.raises(ValueError, match="YAML mapping"):
        ConfigLoader().load(config_path)


def test_config_loader_rejects_invalid_list_shape(tmp_path: Path) -> None:
    config_path = tmp_path / "code-diver.yml"
    config_path.write_text("plugins: plugin.py\n", encoding="utf-8")

    with pytest.raises(ValueError, match="YAML list"):
        ConfigLoader().load(config_path)
