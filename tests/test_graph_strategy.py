from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.cli import main


pytestmark = pytest.mark.e2e


def test_graph_strategy_expands_from_import_seed(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "service.py").write_text("from repository import save_user\n\ndef register():\n    save_user()\n", encoding="utf-8")
    (repo / "repository.py").write_text("def save_user():\n    return 'saved'\n", encoding="utf-8")
    config = tmp_path / "code-diver.yml"
    artifact = tmp_path / "index.json"
    graph_artifact = tmp_path / "graph.json"
    config.write_text(
        f"""
root: {repo}
artifact: {artifact}
embedding:
  provider: hash
  dimensions: 128
scanner:
  include:
    - "*.py"
search:
  strategy: graph
  limit: 5
graph:
  enabled: true
  artifact: {graph_artifact}
  expansion_depth: 1
plugins: []
""".strip(),
        encoding="utf-8",
    )

    assert main(["--config", str(config), "index"]) == 0
    capsys.readouterr()
    assert graph_artifact.exists()

    assert main(["--config", str(config), "search", "register user", "--json"]) == 0
    output = capsys.readouterr().out
    assert "repository.py" in output
