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


@pytest.mark.parametrize(
    ("ranked_paths", "gold_paths", "expected"),
    [
        (("a.py", "b.py"), ("a.py",), 1.0),
        (("b.py", "c.py"), ("a.py",), 0.0),
        (("a.py",), (), 0.0),
        (("x.py", "b.py", "c.py"), ("a.py", "b.py"), 0.5),
    ],
    ids=["within", "not-within", "empty-gold", "multiple-gold-one-present"],
)
def test_file_recall_at_k_cases(
    ranked_paths: tuple[str, ...], gold_paths: tuple[str, ...], expected: float
) -> None:
    """Recall is the fraction of unique gold paths found in the top k."""
    assert replay.file_recall_at_k(ranked_paths, gold_paths, 2) == expected


@pytest.mark.parametrize(
    ("ranked_paths", "gold_paths", "k", "expected"),
    [
        (("a.py", "b.py"), ("a.py",), 2, 1.0),
        (("x.py", "b.py", "a.py"), ("a.py",), 3, 1 / 3),
        (("x.py", "b.py"), ("a.py",), 2, 0.0),
        (("x.py",), (), 10, 0.0),
    ],
    ids=["rank-1", "rank-k", "absent", "empty-gold"],
)
def test_reciprocal_rank_at_k_cases(
    ranked_paths: tuple[str, ...], gold_paths: tuple[str, ...], k: int, expected: float
) -> None:
    """Reciprocal rank is zero when no gold path appears in the cutoff."""
    assert replay.reciprocal_rank_at_k(ranked_paths, gold_paths, k) == expected


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


def test_load_dump_returns_exact_dataclass_values_for_three_records(tmp_path: Path) -> None:
    """Both dump schemas populate every dataclass field deterministically."""
    path = tmp_path / "dump.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"id": "one", "query": "first", "expected": ["one.py"]}),
                json.dumps(
                    {
                        "query_id": "two",
                        "query_text": "second",
                        "candidates": [{"path": "two.py", "score": 2.5, "body": "body"}],
                        "gold_paths": ["two.py"],
                    }
                ),
                json.dumps(
                    {
                        "query_id": "three",
                        "query_text": "third",
                        "candidates": ["three.py"],
                        "gold_paths": [],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert replay.load_dump(path) == [
        replay.QueryPool("one", "first", (replay.Candidate("one.py"),), ("one.py",)),
        replay.QueryPool(
            "two", "second", (replay.Candidate("two.py", 2.5, "body"),), ("two.py",)
        ),
        replay.QueryPool("three", "third", (replay.Candidate("three.py"),), ()),
    ]


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
