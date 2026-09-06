import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "research_candidate_budget", Path(__file__).parents[1] / "scripts/research_candidate_budget.py"
)
research = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(research)


class CandidateBudgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (Path(__file__).parents[1] / "artifacts/research/2026-09-05/candidate-budget").mkdir(parents=True, exist_ok=True)

    def rows(self, count=90):
        return [{"path": f"p{i}", "rank": i + 1,
                 "signals": {"vector_score": 1, "lexical_score": i,
                             "graph_score": 0, "fused_score": 1}} for i in range(count)]

    def test_fixed_and_quota_budget_and_deterministic_ties(self):
        rows = self.rows()
        self.assertEqual([r["path"] for r in research.select(rows)], [f"p{i}" for i in range(34)])
        chosen = research.select(rows, research.QUOTAS)
        self.assertEqual(len(chosen), 34)
        self.assertEqual(len({r["path"] for r in chosen}), 34)
        self.assertEqual(chosen, research.select(list(reversed(rows)), research.QUOTAS))

    def test_underfilled_channels_backfill_and_short_pool(self):
        rows = self.rows(5)
        self.assertEqual(research.select(rows, research.QUOTAS), rows)

    def test_labels_cannot_change_selection(self):
        rows = self.rows()
        expected = research.select(rows, research.QUOTAS)
        decorated = [{**row, "label": 1, "expected": ["other"]} for row in rows]
        self.assertEqual([r["path"] for r in expected],
                         [r["path"] for r in research.select(decorated, research.QUOTAS)])

    def test_absent_gold_and_rescue_are_distinct(self):
        case = {"id": "a", "expected": ["absent", "p89"]}
        result = research.evaluate_case(case, self.rows())
        self.assertEqual(result["gold_absent_from_export"], ["absent"])
        self.assertEqual(result["recall"]["fixed34"], 0)
        self.assertEqual(result["recall"]["quota34"], 0.5)
        self.assertEqual(result["rescued_by_quota"], ["p89"])

    def test_missing_provenance_and_globs_fail(self):
        with self.assertRaises(ValueError):
            research.select(self.rows(), (("unknown", 3),))
        with self.assertRaises(ValueError):
            research.evaluate_case({"id": "a", "expected": ["*.kt"]}, self.rows())

    def test_overbudget_fails(self):
        with self.assertRaises(ValueError):
            research.select(self.rows(), (("vector_score", 35),))

    def test_provider_error_does_not_become_zero_quality(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1] / "artifacts/research/2026-09-05/candidate-budget") as directory:
            path = Path(directory) / "report.json"
            path.write_text(json.dumps({"results": [{"case_id": "a", "error": "provider failed"}]}))
            result = research.inspect_json(path)
            self.assertEqual(result["counts"]["error_objects"], 1)
            self.assertNotIn("recall", result)

    def test_query_plan_must_join_id_and_question(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1] / "artifacts/research/2026-09-05/candidate-budget") as directory:
            path = Path(directory) / "report.json"
            path.write_text(json.dumps({"results": [{"case_id": "a", "question": "other", "query_plan": {"queries": ["q"]}}]}))
            self.assertEqual(research.inspect_json(path, {("a", "q")})["target_plan_case_ids"], [])
            self.assertEqual(research.inspect_json(path, {("a", "other")})["target_plan_case_ids"], ["a"])

    def test_top10_is_not_a_pool_or_query_plan(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1] / "artifacts/research/2026-09-05/candidate-budget") as directory:
            path = Path(directory) / "report.json"
            path.write_text(json.dumps({"results": [{"case_id": "a", "retrieved_paths": [f"p{i}" for i in range(10)], "error": "provider failed"}]}))
            report = research.inspect_json(path)
            self.assertEqual(report["counts"]["retrieved_paths_max_length"], 10)
            self.assertEqual(report["counts"].get("nonempty_query_plans", 0), 0)
            self.assertNotIn("recall34", report)

    def test_duplicate_rank_export_fails(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1] / "artifacts/research/2026-09-05/candidate-budget") as directory:
            path = Path(directory) / "features.jsonl"
            names = ["vector_score", "lexical_score", "graph_score", "fused_score"]
            row = {"query_id": "a", "query": "q", "base_rank": 1, "path": "p", "features": [1, 1, 1, 1]}
            path.write_text("\n".join(json.dumps(r) for r in ({"feature_names": names}, row, row)))
            with self.assertRaisesRegex(ValueError, "ranks"):
                research.load_pool(path)


if __name__ == "__main__":
    unittest.main()