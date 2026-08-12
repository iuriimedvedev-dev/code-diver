from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

from code_diver.reranking.rerank_score import RerankScore

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_postrank_h2_deterministic.py"
SPEC = importlib.util.spec_from_file_location("run_postrank_h2_deterministic", SCRIPT_PATH)
assert SPEC is not None
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
DeterministicPostrankH2 = MODULE.DeterministicPostrankH2


class FakeRerankProvider:
    model = "fake-cross-encoder"

    def rerank(self, query: str, documents: list[str], top_n: int) -> list[RerankScore]:
        assert query == "where is auth"
        assert "path: src/a.py" in documents[0]
        assert top_n == 2
        return [RerankScore(index=1, score=0.9), RerankScore(index=0, score=0.1)]


def test_postrank_cross_encoder_reranks_structured_candidates() -> None:
    runner = object.__new__(DeterministicPostrankH2)
    runner.limit = 2
    runner.args = SimpleNamespace(
        dedupe_final_files=True,
        llm_prefix_files=0,
        protected_base_files=0,
        protected_base_mode="prefix",
        rerank_return_limit=0,
    )
    config = SimpleNamespace(
        cross_encoder_rerank=SimpleNamespace(candidate_limit=3, max_document_chars=80, model="fake-cross-encoder")
    )

    ranked, metrics, degraded = runner._cross_encoder_rerank(
        FakeRerankProvider(),
        "where is auth",
        [
            {"path": "src/a.py", "title": "A", "score": 0.8, "preview": "alpha"},
            {"path": "src/b.py", "title": "B", "score": 0.7, "preview": "beta"},
            {"path": "src/c.py", "title": "C", "score": 0.6, "preview": "gamma"},
        ],
        {
            "rerank_calls": 0,
            "rerank_errors": 0,
            "rerank_error_attempts": 0,
        },
        config,
    )

    assert degraded is False
    assert metrics["modelCalls"] == 1
    assert metrics["models"] == ["fake-cross-encoder"]
    assert [candidate["path"] for candidate in ranked] == ["src/b.py", "src/a.py"]
    assert ranked[0]["crossEncoderScore"] == 0.9
