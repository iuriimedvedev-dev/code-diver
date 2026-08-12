from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .explanation_case import ExplanationCase


class CodeExplanationDatasetPreparer:
    DATASET_NAME = "google/code_x_glue_ct_code_to_text"
    DEFAULT_LANGUAGE = "python"

    def prepare_codexglue_python(self, output: Path, *, limit: int) -> dict[str, Any]:
        try:
            from datasets import load_dataset
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError("Install the benchmark extra with `uv sync --extra benchmarks`; the `datasets` package is required.") from exc

        split = f"test[:{max(limit, 1)}]"
        dataset = load_dataset(self.DATASET_NAME, self.DEFAULT_LANGUAGE, split=split)
        cases = [self._case_from_codexglue_row(row).to_json() for row in dataset]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            "".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases),
            encoding="utf-8",
        )
        return {
            "dataset": self.DATASET_NAME,
            "language": self.DEFAULT_LANGUAGE,
            "split": split,
            "cases": len(cases),
            "output": str(output),
        }

    def _case_from_codexglue_row(self, row: dict[str, Any]) -> ExplanationCase:
        func_name = str(row.get("func_name") or "")
        prompt = (
            "Explain this Python function for a developer who is trying to understand the code. "
            "State the purpose, important inputs/outputs, and key behavior."
        )
        return ExplanationCase(
            id=f"codexglue-python-{row.get('id')}",
            code=str(row.get("code") or row.get("original_string") or ""),
            reference=str(row.get("docstring") or ""),
            prompt=prompt,
            metadata={
                "benchmark": "codexglue-code-to-text",
                "language": row.get("language") or self.DEFAULT_LANGUAGE,
                "repo": row.get("repo"),
                "path": row.get("path"),
                "func_name": func_name,
                "url": row.get("url"),
            },
        )
