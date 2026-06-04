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

    assert main(["search", "authenticate", "user", "password", "-j", "--config", str(config)]) == 0
    search_payload = json.loads(capsys.readouterr().out)
    assert search_payload[0]["item"]["path"] == "auth.py"

    assert main(["--config", str(config), "evaluate", "--json"]) == 0
    eval_payload = json.loads(capsys.readouterr().out)
    assert eval_payload["metrics"]["cases"] == 1
    assert eval_payload["metrics"]["hit_rate@3"] == 1.0

    artifact.unlink()
    assert main(["evaluate", "--json", "--reindex", "--config", str(config)]) == 0
    captured = capsys.readouterr()
    reindex_payload = json.loads(captured.out)
    assert reindex_payload["metrics"]["cases"] == 1
    assert "Indexed 1 items" in captured.err

    assert main(["--config", str(config), "experiment", "--json"]) == 0
    experiment_payload = json.loads(capsys.readouterr().out)
    assert experiment_payload["suite"] == "test-suite"
    assert [result["strategy"] for result in experiment_payload["strategies"]] == ["vector", "recursive", "graph"]
    assert all(result["metrics"]["cases"] == 1 for result in experiment_payload["strategies"])


def test_evaluate_can_generate_local_dataset(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "team_builder.py").write_text(
        "class TeamBuilder:\n"
        "    def create_team(self, user_id):\n"
        "        return user_id\n",
        encoding="utf-8",
    )
    config = tmp_path / "code-diver.yml"
    config.write_text(
        f"""
root: {repo}
artifact: {tmp_path}/index.json
embedding:
  provider: hash
  dimensions: 128
scanner:
  include:
    - "*.py"
graph:
  enabled: false
trace:
  enabled: false
plugins: []
""".strip(),
        encoding="utf-8",
    )

    assert main(["--config", str(config), "evaluate", "--generate-dataset", "--cases", "3", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    dataset = repo / ".code-diver" / "eval" / "local_eval.jsonl"

    assert dataset.exists()
    assert payload["dataset"] == str(dataset)
    assert payload["generated_dataset"]["cases"] == 3
    assert payload["metrics"]["cases"] == 3


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


def test_search_without_index_reports_actionable_error(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "auth.py").write_text("def authenticate_user():\n    return True\n", encoding="utf-8")
    config = tmp_path / "code-diver.yml"
    config.write_text(
        f"""
root: {repo}
artifact: {tmp_path}/missing-index.json
embedding:
  provider: hash
  dimensions: 64
scanner:
  include:
    - "*.py"
trace:
  enabled: false
plugins: []
""".strip(),
        encoding="utf-8",
    )

    assert main(["search", "authenticate", "user", "--json", "--config", str(config)]) == 1
    assert "Run `code-diver index` first" in capsys.readouterr().err


def test_search_without_json_invokes_pi_code_explorer(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config = tmp_path / "code-diver.yml"
    config.write_text(
        f"""
root: {repo}
embedding:
  provider: hash
  dimensions: 64
pi:
  binary: pi
  tools:
    - code_diver_search
    - code_diver_inspect
plugins: []
""".strip(),
        encoding="utf-8",
    )
    calls: list[tuple[Path | None, str, str | None, str | None]] = []

    class FakePiRunner:
        def run_print_capture(
            self,
            config,
            config_path: Path | None,
            prompt: str,
            toolset: str | None = None,
            hypothesis: str | None = None,
        ) -> tuple[int, str]:
            calls.append((config_path, prompt, toolset, hypothesis))
            return 0, "## Answer\n\nIt is handled in `auth.py:1`."

    monkeypatch.setattr("code_diver.cli.PiRunner", FakePiRunner)
    monkeypatch.setattr("code_diver.cli.code_explorer_preflight", lambda config, config_path: True)
    monkeypatch.setattr("code_diver.cli.search_agent_binary_available", lambda config: True)

    assert main(["--config", str(config), "search", "where", "is", "auth", "handled"]) == 0

    assert calls
    assert calls[0][0] == config
    assert "where is auth handled" in calls[0][1]
    assert "code_diver_search" in calls[0][1]
    assert "Explain the code" in calls[0][1]
    assert calls[0][2] is None
    assert calls[0][3] is None


def test_search_interactive_invokes_search_agent_chat(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config = tmp_path / "code-diver.yml"
    config.write_text(
        f"""
root: {repo}
embedding:
  provider: hash
  dimensions: 64
pi:
  binary: pi
  tools:
    - code_diver_search
plugins: []
""".strip(),
        encoding="utf-8",
    )
    calls: list[str | None] = []

    class FakePiRunner:
        def run_interactive(self, config, config_path: Path | None, prompt: str | None = None) -> int:
            calls.append(prompt)
            return 0

    monkeypatch.setattr("code_diver.cli.PiRunner", FakePiRunner)
    monkeypatch.setattr("code_diver.cli.code_explorer_preflight", lambda config, config_path: True)
    monkeypatch.setattr("code_diver.cli.search_agent_binary_available", lambda config: True)

    assert main(["--config", str(config), "search", "-i", "explain", "indexing"]) == 0

    assert calls
    assert calls[0] is not None
    assert "explain indexing" in calls[0]


class _StringInput:
    def __init__(self, text: str):
        self.text = text

    def read(self) -> str:
        return self.text
