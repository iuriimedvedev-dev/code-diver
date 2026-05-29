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
    trace = tmp_path / "trace.jsonl"
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
trace:
  enabled: true
  artifact: {trace}
  include_prompts: true
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
    trace_records = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    assert [record["event"] for record in trace_records] == ["index_items_prepared", "index_vectors_saved"]
    assert trace_records[0]["payload"]["indexed_items"] == 1
    assert trace_records[1]["payload"]["model"] == "hash-token-v1"
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


def test_index_selected_writes_qdrant_from_paths_only(tmp_path: Path, capsys, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "payments.py"
    source.write_text(
        """
class PaymentGateway:
    def charge_card(self, card_token, amount):
        return {"status": "paid", "amount": amount}
""".strip(),
        encoding="utf-8",
    )
    config = tmp_path / "code-diver.yml"
    config.write_text(
        f"""
root: {repo}
storage:
  provider: qdrant
  qdrant:
    location: {tmp_path}/qdrant
    collection: selected_items
embedding:
  provider: hash
  dimensions: 64
scanner:
  include:
    - "*.py"
  chunk_lines: 20
graph:
  enabled: false
trace:
  enabled: false
plugins: []
""".strip(),
        encoding="utf-8",
    )
    payload = {
        "items": [
            {
                "path": "payments.py",
                "startLine": 1,
                "endLine": 3,
                "title": "Payment gateway",
                "reason": "core payment API",
                "kind": "api",
            }
        ]
    }

    monkeypatch.setattr("sys.stdin", _StringInput(json.dumps(payload)))

    assert main(["--config", str(config), "index-selected", "--json"]) == 0
    index_payload = json.loads(capsys.readouterr().out)
    assert index_payload["indexed"] == 1
    assert index_payload["items"][0]["metadata"]["source"] == "ai_selected"
    assert index_payload["items"][0]["content"].startswith("class PaymentGateway")

    assert main(["--config", str(config), "search", "charge card payment gateway", "--json"]) == 0
    search_payload = json.loads(capsys.readouterr().out)
    assert search_payload[0]["item"]["path"] == "payments.py"


class _StringInput:
    def __init__(self, text: str):
        self.text = text

    def read(self) -> str:
        return self.text
