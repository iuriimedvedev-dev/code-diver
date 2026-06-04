from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_diver.services import CodebaseScanner, LocalEvalDatasetGenerator


pytestmark = pytest.mark.unit


def test_local_eval_dataset_generator_writes_deterministic_cases(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "team_builder.py"
    source.write_text(
        "class TeamBuilder:\n"
        "    def create_team(self, user_id):\n"
        "        return user_id\n",
        encoding="utf-8",
    )
    output = tmp_path / "local_eval.jsonl"
    scanner = CodebaseScanner(
        include=["*.py"],
        line_chunks=False,
        file_summary_chunks=True,
        file_manifest_chunks=True,
    )

    rows = LocalEvalDatasetGenerator(scanner).generate(repo, output, 5)

    assert output.exists()
    assert rows == [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["expected"] == ["team_builder.py"]
    assert rows[0]["metadata"]["source"] == "local_eval_generator"
    queries = [row["query"] for row in rows]
    assert "find the file named team_builder.py" in queries
    assert "where is TeamBuilder defined?" in queries


def test_local_eval_dataset_generator_rejects_empty_repository(tmp_path: Path) -> None:
    scanner = CodebaseScanner(include=["*.py"], line_chunks=False, file_summary_chunks=True)

    with pytest.raises(ValueError, match="No local evaluation cases"):
        LocalEvalDatasetGenerator(scanner).generate(tmp_path, tmp_path / "eval.jsonl", 10)
