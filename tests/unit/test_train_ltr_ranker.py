from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from code_diver.ranking import LTR_FEATURE_NAMES, LtrRankerModel

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # The script declares dataclasses, and `dataclasses` resolves their annotations through
    # `sys.modules[cls.__module__]`, so the module has to be registered before it executes.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_ndcg_rewards_a_relevant_file_placed_first() -> None:
    script = load_script("train_ltr_ranker")

    assert script.ndcg_at_k([1, 0, 0], 3) == pytest.approx(1.0)
    assert script.ndcg_at_k([0, 0, 1], 3) < script.ndcg_at_k([0, 1, 0], 3)
    assert script.ndcg_at_k([0, 0, 0], 3) == 0.0


def test_recall_counts_only_the_relevant_files_inside_the_cut() -> None:
    script = load_script("train_ltr_ranker")

    assert script.recall_at_k([1, 0, 1], 3) == pytest.approx(1.0)
    assert script.recall_at_k([1, 0, 1], 1) == pytest.approx(0.5)


def test_loading_a_dump_exported_with_other_features_is_refused(tmp_path: Path) -> None:
    script = load_script("train_ltr_ranker")
    dump = tmp_path / "features.jsonl"
    dump.write_text(
        json.dumps({"feature_names": ["a", "b"]}) + "\n"
        + json.dumps({"query_id": "q1", "label": 1, "features": [0.0, 0.0]}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(script.TrainLtrRankerError):
        script.load_groups(dump)


def test_training_writes_a_loadable_artifact_and_holds_out_whole_queries(tmp_path: Path) -> None:
    script = load_script("train_ltr_ranker")
    dump = _dump(tmp_path / "features.jsonl", queries=40)
    out = tmp_path / "artifacts" / "ranker.json"

    assert script.main([str(dump), "--out", str(out), "--backend", "sklearn", "--seed", "3"]) == 0

    manifest = json.loads(out.read_text(encoding="utf-8"))
    assert manifest["feature_names"] == list(LTR_FEATURE_NAMES)
    assert manifest["metrics"]["train_queries"] + manifest["metrics"]["test_queries"] == 40
    assert LtrRankerModel.load(out) is not None


def _dump(path: Path, queries: int) -> Path:
    fused_index = LTR_FEATURE_NAMES.index("fused_score")
    lines = [json.dumps({"feature_names": list(LTR_FEATURE_NAMES)})]
    for query in range(queries):
        for rank in range(5):
            features = [0.0] * len(LTR_FEATURE_NAMES)
            # One clean signal so the fit is not degenerate: the relevant file is the one
            # with the highest fused score, which is the relationship the ranker should find.
            features[fused_index] = 1.0 - rank * 0.1
            lines.append(
                json.dumps(
                    {
                        "query_id": f"case-{query}",
                        "query": f"query {query}",
                        "base_rank": rank + 1,
                        "label": 1 if rank == 0 else 0,
                        "item_id": f"item-{query}-{rank}",
                        "path": f"src/file_{query}_{rank}.py",
                        "features": features,
                    }
                )
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
