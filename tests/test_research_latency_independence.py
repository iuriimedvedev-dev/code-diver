import importlib.util
from pathlib import Path
import sys

import pytest

SPEC = importlib.util.spec_from_file_location("latency_audit", Path(__file__).parents[1] / "scripts/research_latency_independence.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def test_normalized_query_and_answer_overlap_are_distinct():
    train = [{"id": "a", "query": "Where IS Foo?", "expected": ["src/A.kt"]}]
    test = [{"id": "b", "query": " where is foo ", "expected": ["src/B.kt"]},
            {"id": "c", "query": "Different", "expected": ["src/A.kt", "src/C.kt"]}]
    result = audit.overlap(train, test)
    assert result["counts"] == {"id": 0, "normalized_query": 1, "exact_answer_set": 0, "any_exact_answer": 1}
    assert result["case_ids"]["any_exact_answer"] == ["c"]


def test_label_policy_and_empty_overlap():
    row = {"expected": ["glob:**/*.kt", "src/dir/", "src/A.kt"]}
    assert len(audit.labels(row, "full")) == 3
    assert len(audit.labels(row, "no_glob")) == 2
    assert audit.labels(row) == {"src/A.kt"}
    assert audit.overlap([], [dict(row, id="x", query="x")])["shared_exact_labels"] == 0


def test_real_split_is_order_independent_and_id_disjoint():
    splitter = audit.LtrQuerySplitter()
    first = splitter.split(["a", "b", "a", "c"], 0.2, 42)
    assert first == splitter.split(["c", "b", "a"], 0.2, 42)
    assert not first.overlap()
    with pytest.raises(ValueError):
        splitter.split(["a"], 1, 42)


def test_timeout_and_failure_are_explicit():
    result = audit.run_child([sys.executable, "-c", "import time; time.sleep(2)"], 0.05)
    assert result["status"] == "timeout"
    result = audit.run_child([sys.executable, "-c", "raise RuntimeError('expected')"], 2)
    assert result["status"] == "error"


def test_percentiles_and_no_samples():
    assert audit.stats([]) == {"n": 0}
    assert audit.stats([1, 2, 3])["p50_ms"] == 2


def test_slices_exclude_train_queries_and_deduplicate_test():
    train = [{"id": "a", "query": "old", "expected": ["A.kt"]}]
    test = [{"id": "b", "query": "OLD!", "expected": ["B.kt"]},
            {"id": "c", "query": "new", "expected": ["A.kt"]},
            {"id": "d", "query": "NEW", "expected": ["C.kt"]},
            {"id": "e", "query": "novel", "expected": ["D.kt"]}]
    assert audit.slices(train, test) == {"deduplicated_query_novel": ["c", "e"],
                                       "query_and_answer_novel": ["e"],
                                       "family_overlap_risk": ["b", "c"]}