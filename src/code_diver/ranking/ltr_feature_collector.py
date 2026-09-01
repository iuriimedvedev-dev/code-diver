from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from threading import Lock

from ..domain import EvalCase
from ..services.expected_path_matcher import ExpectedPathMatcher
from .ltr_feature_row import LTR_FEATURE_NAMES, LtrFeatureRow


class LtrFeatureCollector:
    """Captures per-query feature rows during a retrieval run and writes a training set.

    Rows are keyed by the query text the strategy actually saw, because the retrieval
    strategy has no notion of an evaluation case. Labelling happens afterwards, when the
    caller joins the captured rows back onto the cases -- keeping the strategy free of
    any knowledge of the ground truth it is being measured against.
    """

    def __init__(self) -> None:
        self._rows_by_query: dict[str, list[LtrFeatureRow]] = {}
        self._lock = Lock()
        self.expected_path_matcher = ExpectedPathMatcher()

    def collect(self, query: str, rows: Sequence[LtrFeatureRow]) -> None:
        with self._lock:
            self._rows_by_query[query] = list(rows)

    def rows_for(self, query: str) -> list[LtrFeatureRow]:
        with self._lock:
            return list(self._rows_by_query.get(query, ()))

    def write_jsonl(self, path: Path, cases: Sequence[EvalCase]) -> int:
        """Write one JSON object per (query, candidate). Returns the row count."""
        path.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with path.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps({"feature_names": list(LTR_FEATURE_NAMES)}) + "\n")
            for case in cases:
                for rank, row in enumerate(self.rows_for(case.query), start=1):
                    handle.write(
                        json.dumps(
                            {
                                "query_id": case.id,
                                "query": case.query,
                                "base_rank": rank,
                                "label": 1
                                if self.expected_path_matcher.matches_any(row.path, case.expected)
                                else 0,
                                **row.to_json(),
                            }
                        )
                        + "\n"
                    )
                    written += 1
        return written
