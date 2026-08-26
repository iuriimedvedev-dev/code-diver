from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit
SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "replay_listwise_where.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("replay_listwise_where", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


replay = _module()


def test_metrics_cover_missing_empty_and_multiple_gold() -> None:
    records = [replay.DumpRecord("a", "q", (), ("a", "b")), replay.DumpRecord("b", "q", (), ()), replay.DumpRecord("c", "q", (), ("z",))]
    ranked = [["a", "x", "b"], ["x"], ["x"]]
    assert replay.file_recall_at_k(records, ranked, 2) == pytest.approx(1 / 6)
    assert replay.reciprocal_rank_at_k(records, ranked, 2) == pytest.approx(1 / 3)


def test_prompt_path_only_excludes_snippet_and_full_includes_it() -> None:
    record = replay.DumpRecord("a", "where", (replay.Candidate("a.py", 1.0, "SECRET BODY"),), ("a.py",))
    assert "SECRET BODY" not in replay.build_listwise_prompt(record, path_only=True)
    assert "SECRET BODY" in replay.build_listwise_prompt(record)
    assert "implementation" in replay.build_listwise_prompt(record).lower()


def test_load_dump_actual_and_rich_schema(tmp_path: Path) -> None:
    path = tmp_path / "dump.jsonl"
    path.write_text(
        json.dumps({"id": "a", "query": "q", "expected": ["a.py"]})
        + "\n"
        + json.dumps({"query_id": "b", "query_text": "q2", "candidates": [{"path": "b.py", "score": 2, "snippet": "s"}], "gold_paths": ["b.py"]})
        + "\n",
        encoding="utf-8",
    )
    records = replay.load_dump(path)
    assert records[0].candidates[0].snippet == ""
    assert records[1].candidates[0].snippet == "s"


def test_parse_ranking_accepts_keys_plain_list_and_appends() -> None:
    assert replay.parse_ranking('{"ranking": [2]}', 3) == [2, 0, 1]
    assert replay.parse_ranking("1. 0\n2. 2", 3) == [1, 0, 2]


class FakeClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        return '{"ranked_indices": [0]}'


def test_baseline_and_dry_run_do_not_call_llm_and_listwise_replays(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dump = tmp_path / "dump.jsonl"
    dump.write_text(json.dumps({"id": "a", "query": "q", "expected": ["a.py"]}) + "\n", encoding="utf-8")
    client = FakeClient()
    assert replay.main(["--dump", str(dump), "--baseline"], client) == 0
    assert client.calls == 0
    assert replay.main(["--dump", str(dump), "--dry-run"], client) == 0
    assert client.calls == 0
    assert replay.main(["--dump", str(dump)], client) == 0
    assert client.calls == 1
    assert '"mode": "full"' in capsys.readouterr().out
