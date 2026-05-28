from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_diver.cli import main


pytestmark = pytest.mark.e2e


def test_index_search_and_evaluate_with_hash_provider(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "auth.py"
    source.write_text(
        """
def authenticate_user(username, password):
    if username == "admin" and password == "secret":
        return True
    return False
""".strip(),
        encoding="utf-8",
    )
    dataset = repo / "eval.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "id": "auth",
                "query": "authenticate user password",
                "expected": ["auth.py"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    config = tmp_path / "code-diver.yml"
    artifact = tmp_path / "index.json"
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
graph:
  artifact: {tmp_path}/graph.json
evaluation:
  dataset: {dataset}
  limit: 3
experiments:
  suite: test-suite
  strategies:
    - vector
    - recursive
    - graph
metrics:
  enabled: false
plugins: []
""".strip(),
        encoding="utf-8",
    )

    assert main(["--config", str(config), "index"]) == 0
    assert artifact.exists()
    capsys.readouterr()

    assert main(["--config", str(config), "search", "authenticate user password", "--json"]) == 0
    search_payload = json.loads(capsys.readouterr().out)
    assert search_payload[0]["item"]["path"] == "auth.py"

    assert main(["--config", str(config), "evaluate", "--json"]) == 0
    eval_payload = json.loads(capsys.readouterr().out)
    assert eval_payload["metrics"]["cases"] == 1
    assert eval_payload["metrics"]["hit_rate@3"] == 1.0

    assert main(["--config", str(config), "experiment", "--json"]) == 0
    experiment_payload = json.loads(capsys.readouterr().out)
    assert experiment_payload["suite"] == "test-suite"
    assert [result["strategy"] for result in experiment_payload["strategies"]] == ["vector", "recursive", "graph"]
    assert all(result["metrics"]["cases"] == 1 for result in experiment_payload["strategies"])
