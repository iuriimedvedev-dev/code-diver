from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from code_diver.benchmarks import BenchmarkPreparation
from code_diver.benchmarks.mteb_codesearchnet_preparer import MtebCodeSearchNetPreparer


pytestmark = pytest.mark.unit


class FakeDatasets:
    def __init__(self) -> None:
        self.rows: dict[str, list[dict[str, Any]]] = {
            "python-corpus": [
                {"id": "bad", "title": "Bad", "text": "def wrong(): pass"},
                {"id": "one", "title": "First Result", "text": "def first(): pass"},
                {"id": "two", "title": "Second Result", "text": "def second(): pass"},
            ],
            "python-queries": [
                {"id": "q0", "text": "wrong query"},
                {"id": "q1", "text": "first query"},
                {"id": "q2", "text": "second query"},
            ],
            "python-qrels": [
                {"query-id": "q0", "corpus-id": "bad", "score": 0},
                {"query-id": "q1", "corpus-id": "one", "score": 1},
                {"query-id": "q2", "corpus-id": "two", "score": 2},
            ],
        }

    def load_dataset(self, _name: str, subset: str, split: str) -> list[dict[str, Any]]:
        assert split == "test"
        return self.rows[subset]


def test_mteb_preparer_selects_positive_qrels_before_limit(tmp_path: Path) -> None:
    preparation = BenchmarkPreparation(
        kind="mteb_codesearchnet",
        dataset_name="mteb/CodeSearchNetRetrieval",
        language="python",
        limit=2,
        output_root=tmp_path / "bench",
        estimated_download_mb=1,
    )
    preparer = MtebCodeSearchNetPreparer(preparation)
    preparer._load_datasets_module = lambda: FakeDatasets()  # type: ignore[method-assign]

    manifest = preparer.run()

    cases = [json.loads(line) for line in preparation.dataset_path.read_text(encoding="utf-8").splitlines()]
    assert [case["metadata"]["corpus_id"] for case in cases] == ["one", "two"]
    assert all(case["metadata"]["score"] > 0 for case in cases)
    assert manifest["qrels_total"] == 3
    assert manifest["positive_qrels"] == 2
    assert manifest["selected_qrels"] == 2
    assert manifest["qrel_selection"] == "score>0_then_first_limit"
