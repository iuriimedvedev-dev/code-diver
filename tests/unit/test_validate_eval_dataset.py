from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_validate_eval_dataset_reports_errors_and_warnings(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "src").mkdir()
    (root / "src" / "UserService.kt").write_text("class UserService", encoding="utf-8")
    (root / "src" / "OtherService.kt").write_text("class OtherService", encoding="utf-8")
    dataset = tmp_path / "eval.jsonl"
    dataset.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "case",
                        "query": "where is user service",
                        "expected": ["src/UserService.kt", "glob:**/*Service.kt"],
                    }
                ),
                json.dumps({"id": "case", "query": "duplicate", "expected": ["src/Missing.kt"]}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "scripts/validate_eval_dataset.py",
            str(dataset),
            "--root",
            str(root),
            "--max-glob-matches",
            "1",
        ],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["issue_counts"]["error"] == 2
    assert payload["issue_counts"]["warning"] >= 3
    messages = {issue["message"] for issue in payload["issues"]}
    assert "duplicate case id" in messages
    assert "expected path does not exist" in messages
    assert "glob matches too many files" in messages
    assert "glob overlaps exact expected paths" in messages
    assert "high query/path token overlap" in messages
