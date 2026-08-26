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
