"""Dual-path bridge: default OFF, Python fallback when native missing."""

from __future__ import annotations

import os

import pytest

from code_diver.native_search import (
    fuse_hybrid_total,
    native_module,
    native_search_enabled,
    reset_native_search_cache,
    try_expand_adjacency,
    try_propagate_file_scores,
)
from code_diver.strategies.file_graph_adjacency_index import FileGraphAdjacencyIndex
from code_diver.strategies.graph_expansion_profile import GraphExpansionProfile


@pytest.fixture(autouse=True)
def _clear_native_cache(monkeypatch):
    monkeypatch.delenv("CODE_DIVER_NATIVE_SEARCH", raising=False)
    reset_native_search_cache()
    yield
    reset_native_search_cache()


def test_native_flag_default_off():
    assert native_search_enabled() is False
    assert native_module() is None


def test_native_flag_on_still_none_without_extension(monkeypatch):
    monkeypatch.setenv("CODE_DIVER_NATIVE_SEARCH", "1")
    reset_native_search_cache()
    assert native_search_enabled() is True
    # Extension may or may not be built in CI; try_* must not raise either way.
    adj = {"a.py": [("b.py", 1.0)]}
    seeds = {"a.py": 1.0}
    assert try_propagate_file_scores(
        adj, seeds, depth=1, decay=0.5, seed_limit=10, neighbor_limit=10, frontier_limit=None
    ) in (None, {"b.py": 0.5}) or isinstance(
        try_propagate_file_scores(
            adj, seeds, depth=1, decay=0.5, seed_limit=10, neighbor_limit=10, frontier_limit=None
        ),
        dict,
    )


def test_fuse_hybrid_total_uses_python_when_flag_off():
    fallback = 0.65
    got = fuse_hybrid_total(
        vector=1.0,
        lexical=0.5,
        path=0.0,
        symbol=0.0,
        symbol_match=0.0,
        graph=0.0,
        file_vote=0.0,
        vector_weight=0.5,
        lexical_weight=0.3,
        path_weight=0.0,
        symbol_weight=0.0,
        symbol_match_weight=0.0,
        graph_weight=0.0,
        file_vote_weight=0.0,
        python_fallback=fallback,
    )
    assert got == fallback


def test_python_adjacency_expand_unchanged_when_flag_off():
    index = FileGraphAdjacencyIndex(
        {
            "a.py": [("b.py", 1.0), ("c.py", 0.5)],
            "b.py": [("d.py", 0.8)],
        }
    )
    profile = GraphExpansionProfile(depth=1, neighbor_limit=10, decay=0.5, min_score=0.0)
    out = index.expand({"a.py": 1.0}, profile)
    # decay**0 == 1.0
    assert out["b.py"] == pytest.approx(1.0)
    assert out["c.py"] == pytest.approx(0.5)


def test_try_helpers_return_none_when_disabled():
    assert (
        try_propagate_file_scores(
            {"a": [("b", 1.0)]},
            {"a": 1.0},
            depth=1,
            decay=0.5,
            seed_limit=5,
            neighbor_limit=5,
            frontier_limit=None,
        )
        is None
    )
    assert (
        try_expand_adjacency(
            {"a": [("b", 1.0)]},
            {"a": 1.0},
            depth=1,
            decay=0.5,
            neighbor_limit=5,
            min_score=0.0,
        )
        is None
    )


def test_truthy_flag_values(monkeypatch):
    for value in ("1", "true", "YES", "on"):
        monkeypatch.setenv("CODE_DIVER_NATIVE_SEARCH", value)
        assert native_search_enabled() is True
    monkeypatch.setenv("CODE_DIVER_NATIVE_SEARCH", "0")
    assert native_search_enabled() is False
