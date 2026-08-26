"""Thin Python binding test. Skips if the optional native module is not built."""

from __future__ import annotations

import math

import pytest

code_diver_search = pytest.importorskip("code_diver_search")


def test_bm25_native_matches_python_formula():
    from collections import Counter, defaultdict

    docs = {
        "target": ["authorization", "token", "helper"],
        "generic": ["authorization", "helper", "common", "common", "common", "common"],
    }
    idx = code_diver_search.InvertedIndex()
    for doc_id, tokens in docs.items():
        idx.ingest(doc_id, tokens)

    terms = ["authorization", "token"]
    k1, b = 1.2, 0.75
    rust_scores = idx.bm25_scores(terms, k1=k1, b=b)

    item_ids_by_term: dict[str, set[str]] = defaultdict(set)
    tfs = {i: Counter(toks) for i, toks in docs.items()}
    lengths = {i: sum(c.values()) for i, c in tfs.items()}
    for i, c in tfs.items():
        for t in c:
            item_ids_by_term[t].add(i)
    avgdl = sum(lengths.values()) / len(lengths)
    n = len(docs)
    expected: dict[str, float] = {}
    for item_id in docs:
        score = 0.0
        for term in terms:
            tf = tfs[item_id].get(term, 0)
            if tf <= 0:
                continue
            df = len(item_ids_by_term[term])
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            denom = tf + k1 * (1 - b + b * lengths[item_id] / max(avgdl, 1.0))
            score += idf * ((tf * (k1 + 1)) / denom)
        if score > 0:
            expected[item_id] = score

    assert set(rust_scores) == set(expected)
    for key, value in expected.items():
        assert rust_scores[key] == pytest.approx(value, rel=1e-12)


def test_propagate_file_scores_matches_python_decay():
    adjacency = {
        "a.py": [("b.py", 1.0), ("c.py", 0.5)],
        "b.py": [("d.py", 0.8)],
    }
    seeds = {"a.py": 1.0}
    rust = code_diver_search.propagate_file_scores_py(
        adjacency, seeds, depth=2, decay=0.5, seed_limit=10, neighbor_limit=10
    )
    # hop1 decay**1=0.5 → b=0.5, c=0.25; hop2 from b: 0.5*0.8*(0.5**2)=0.1
    assert rust["b.py"] == pytest.approx(0.5)
    assert rust["c.py"] == pytest.approx(0.25)
    assert rust["d.py"] == pytest.approx(0.1)


def test_expand_adjacency_matches_python_profile_decay():
    adjacency = {"a.py": [("b.py", 1.0), ("c.py", 0.5)]}
    rust = code_diver_search.expand_adjacency_py(
        adjacency, {"a.py": 1.0}, depth=1, decay=0.5, neighbor_limit=10, min_score=0.0
    )
    # decay**0 == 1.0
    assert rust["b.py"] == pytest.approx(1.0)
    assert rust["c.py"] == pytest.approx(0.5)
