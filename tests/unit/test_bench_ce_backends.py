"""Unit tests for scripts/bench_ce_backends.py (pure helpers only, no network)."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "bench_ce_backends.py"


def load_module():
    spec = importlib.util.spec_from_file_location("bench_ce_backends", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bench = load_module()


class RerankBaseUrlTest(unittest.TestCase):
    def test_strips_v1_rerank(self):
        self.assertEqual(
            bench.rerank_base_url("http://127.0.0.1:18081/v1/rerank"),
            "http://127.0.0.1:18081",
        )

    def test_strips_legacy_rerank(self):
        self.assertEqual(
            bench.rerank_base_url("http://127.0.0.1:18083/rerank"),
            "http://127.0.0.1:18083",
        )

    def test_leaves_other_paths(self):
        self.assertEqual(
            bench.rerank_base_url("http://x:1/other"), "http://x:1/other"
        )


class TopNIndicesTest(unittest.TestCase):
    def test_best_first_ties_to_lower_index(self):
        scores = {0: 0.5, 1: 0.9, 2: 0.9, 3: 0.1}
        self.assertEqual(bench.top_n_indices(scores, 3), [1, 2, 0])

    def test_n_larger_than_docs(self):
        self.assertEqual(bench.top_n_indices({0: 0.2}, 10), [0])


class CompareRankingsTest(unittest.TestCase):
    def test_overlap_and_deltas(self):
        llama = {0: 0.9, 1: 0.8, 2: 0.1}
        mlx = {0: 0.85, 1: 0.2, 2: 0.75}
        result = bench.compare_rankings(llama, mlx, 2)
        self.assertEqual(result["llama_top"], [0, 1])
        self.assertEqual(result["mlx_top"], [0, 2])
        self.assertEqual(result["top_overlap"], 1)
        self.assertAlmostEqual(result["max_abs_delta"], 0.65)
        self.assertEqual(result["max_abs_delta_index"], 2)
        self.assertAlmostEqual(result["mean_abs_delta"], (0.05 + 0.6 + 0.65) / 3)

    def test_mismatched_doc_sets_raise(self):
        with self.assertRaises(ValueError):
            bench.compare_rankings({0: 1.0}, {1: 1.0}, 1)


if __name__ == "__main__":
    unittest.main()
