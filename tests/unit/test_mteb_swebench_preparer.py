from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from code_diver.benchmarks import BenchmarkPreparation
from code_diver.benchmarks.mteb_swebench_preparer import MtebSweBenchPreparer

pytestmark = pytest.mark.unit


class FakeSweBenchDatasets:
    """Mimics mteb/SWEbenchCodeRetrieval's real shape: flat configs, `_id` keys, and a
    corpus split that is much larger than the set of qrel-referenced gold files."""

    def __init__(self) -> None:
        self.rows: dict[str, list[dict[str, Any]]] = {
            "corpus": [
                {"_id": "acme/widget:aaa111:widget/core.py", "title": "", "text": "def core(): pass"},
                {"_id": "acme/widget:bbb222:widget/core.py", "title": "", "text": "def core_v2(): pass"},
                {"_id": "acme/widget:aaa111:widget/util.py", "title": "", "text": "def util(): pass"},
                {"_id": "acme/widget:aaa111:widget/unrelated.py", "title": "", "text": "def noise(): pass"},
            ],
            "queries": [
                {"_id": "acme__widget-1", "text": "core is broken"},
                {"_id": "acme__widget-2", "text": "core v2 regression"},
            ],
            "default": [
                {"query-id": "acme__widget-1", "corpus-id": "acme/widget:aaa111:widget/core.py", "score": 1},
                {"query-id": "acme__widget-2", "corpus-id": "acme/widget:bbb222:widget/core.py", "score": 1},
                {"query-id": "acme__widget-1", "corpus-id": "acme/widget:aaa111:widget/util.py", "score": 0},
            ],
        }

    def load_dataset(self, _name: str, config: str, split: str) -> list[dict[str, Any]]:
        assert split == "test"
        return self.rows[config]


def _preparer(tmp_path: Path, limit: int = 10) -> MtebSweBenchPreparer:
    preparation = BenchmarkPreparation(
        kind="mteb_swebench",
        dataset_name="mteb/SWEbenchCodeRetrieval",
        language="python",
        limit=limit,
        output_root=tmp_path / "bench",
        estimated_download_mb=1,
    )
    preparer = MtebSweBenchPreparer(preparation)
    preparer._load_datasets_module = lambda: FakeSweBenchDatasets()  # type: ignore[attr-defined]
    return preparer


def test_dataset_path_uses_swebench_naming(tmp_path: Path) -> None:
    preparer = _preparer(tmp_path, limit=10)

    assert preparer.preparation.dataset_path.name == "swebench_code_retrieval_10.jsonl"


def test_swebench_preparer_writes_full_corpus_not_only_gold_files(tmp_path: Path) -> None:
    preparer = _preparer(tmp_path)

    manifest = preparer.run()

    corpus_files = sorted(
        str(path.relative_to(preparer.preparation.corpus_dir))
        for path in preparer.preparation.corpus_dir.rglob("*.py")
    )
    # All 4 corpus rows are written, including the one with no positive qrel and the
    # "unrelated" distractor file -- this is the corpus-easiness fix.
    assert len(corpus_files) == 4
    assert manifest["corpus_files"] == 4
    assert manifest["corpus_scope"] == "full_corpus_split"


def test_swebench_preparer_keeps_commit_scoped_paths_distinct(tmp_path: Path) -> None:
    preparer = _preparer(tmp_path)

    preparer.run()

    core_v1 = preparer.preparation.corpus_dir / "acme__widget/aaa111/widget/core.py"
    core_v2 = preparer.preparation.corpus_dir / "acme__widget/bbb222/widget/core.py"
    assert core_v1.exists()
    assert core_v2.exists()
    assert core_v1.read_text(encoding="utf-8") != core_v2.read_text(encoding="utf-8")


def test_swebench_preparer_selects_only_positive_qrels(tmp_path: Path) -> None:
    preparer = _preparer(tmp_path)

    manifest = preparer.run()

    cases = [
        json.loads(line)
        for line in preparer.preparation.dataset_path.read_text(encoding="utf-8").splitlines()
    ]
    assert manifest["qrels_total"] == 3
    assert manifest["positive_qrels"] == 2
    assert manifest["selected_qrels"] == 2
    assert [case["id"] for case in cases] == ["swebench-acme__widget-1", "swebench-acme__widget-2"]
    assert cases[0]["expected"] == ["acme__widget/aaa111/widget/core.py"]
    assert cases[1]["expected"] == ["acme__widget/bbb222/widget/core.py"]


def test_swebench_preparer_respects_limit_on_positive_qrels(tmp_path: Path) -> None:
    preparer = _preparer(tmp_path, limit=1)

    manifest = preparer.run()

    assert manifest["selected_qrels"] == 1
    cases = [
        json.loads(line)
        for line in preparer.preparation.dataset_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(cases) == 1
    # Full corpus is still written even though only one qrel was selected.
    assert manifest["corpus_files"] == 4


def test_swebench_preparer_raises_on_qrel_missing_from_corpus(tmp_path: Path) -> None:
    preparer = _preparer(tmp_path)
    preparer._load_datasets_module = lambda: _DatasetsWithDanglingQrel()  # type: ignore[attr-defined]

    with pytest.raises(RuntimeError, match="missing from the"):
        preparer.run()


class _DatasetsWithDanglingQrel(FakeSweBenchDatasets):
    def __init__(self) -> None:
        super().__init__()
        self.rows["default"].append(
            {"query-id": "acme__widget-1", "corpus-id": "acme/widget:zzz999:missing.py", "score": 1}
        )
