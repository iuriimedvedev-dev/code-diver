"""Deterministic grounding metrics for generated answers.

These exist because the metrics that came before them cannot separate a correct answer
from a confident fabrication:

* `citation_path_valid_rate` asks only whether a cited path appears in the context bundle.
  An answer that cites a plausible neighbour of the right file -- which retrieval put in
  the bundle -- scores 1.0. The `where-angular-cli` case did exactly that.
* `context_file_recall` measures retrieval, not the answer. A bundle containing every
  expected file says nothing about whether the answer used any of them.

Everything here is computed from the case's `expected_paths` and the context bundle, with
no model involved. That is the point: these are the primary promotion signal, so a weak
local judge cannot inflate them, and they stay comparable across every model in a sweep.
"""

from __future__ import annotations

from typing import Any


class AnswerGroundingMetrics:
    def score(
        self,
        answer: str,
        citations: list[Any],
        context_files: list[str],
        expected_paths: list[str],
    ) -> dict[str, float]:
        expected = {self._normalize(path) for path in expected_paths if str(path).strip()}
        available = {self._normalize(path) for path in context_files if str(path).strip()}
        cited = self._cited_paths(citations)

        resolved = [path for path in cited if path in available]
        # A path the model named that is in no context file it was shown. The model cannot
        # have read it, so it invented the reference.
        fabricated = [path for path in cited if path not in available]
        on_target = {path for path in cited if path in expected}

        answer_nonempty = 1.0 if answer.strip() else 0.0
        metrics = {
            "answer_nonempty": answer_nonempty,
            "citation_expected_hit": 1.0 if on_target else 0.0,
            "citation_fabricated_count": float(len(fabricated)),
            "citation_fabricated_rate": len(fabricated) / max(len(cited), 1),
            "citation_resolved_rate": len(resolved) / max(len(cited), 1),
        }
        if expected:
            metrics["citation_expected_recall"] = len(on_target) / len(expected)
            metrics["citation_expected_precision"] = len(on_target) / max(len(cited), 1)
        # The promotion gate: answered, cited, every citation real, and at least one
        # citation on an expected file. Anything less is not a usable answer, whatever
        # its token overlap with the reference happens to be.
        grounded = bool(answer.strip()) and bool(cited) and not fabricated and bool(on_target)
        metrics["answer_grounded"] = 1.0 if grounded else 0.0
        return metrics

    def _cited_paths(self, citations: list[Any]) -> list[str]:
        paths: list[str] = []
        seen: set[str] = set()
        for citation in citations:
            path = self._citation_path(citation)
            if not path or path in seen:
                continue
            seen.add(path)
            paths.append(path)
        return paths

    def _citation_path(self, citation: Any) -> str:
        # Citations reach here straight from model output, so a bare string or a dict with
        # a missing path is expected input, not a bug to raise on.
        if isinstance(citation, str):
            return self._normalize(citation)
        if isinstance(citation, dict):
            return self._normalize(str(citation.get("path") or ""))
        return ""

    def _normalize(self, path: str) -> str:
        return path.strip().lstrip("./")
