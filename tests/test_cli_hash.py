from __future__ import annotations

import json
from pathlib import Path

from code_diver.cli import main


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
evaluation:
  dataset: {dataset}
  limit: 3
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
