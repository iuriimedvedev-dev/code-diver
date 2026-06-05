from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SweQaProDatasetPreparer:
    DATASET_NAME = "TIGER-Lab/SWE-QA-Pro-Bench"
    SPLIT = "test"

    def prepare(self, output: Path, *, limit: int, repo: str | None = None) -> dict[str, Any]:
        datasets = self._load_datasets_module()
        rows = datasets.load_dataset(self.DATASET_NAME, split=self.SPLIT, streaming=True)
        output.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        scanned = 0
        with output.open("w", encoding="utf-8") as handle:
            for row in rows:
                scanned += 1
                row_repo = str(row.get("repo") or "")
                if repo and row_repo != repo:
                    continue
                written += 1
                payload = {
                    "id": f"swe-qa-pro-{written:05d}",
                    "question": str(row.get("question") or "").strip(),
                    "reference": str(row.get("answer") or "").strip(),
                    "metadata": {
                        "benchmark": self.DATASET_NAME,
                        "repo": row_repo,
                        "commit_id": row.get("commit_id"),
                        "qa_type": row.get("qa_type"),
                        "cluster": row.get("cluster"),
                    },
                }
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
                if written >= limit:
                    break
        return {
            "benchmark": self.DATASET_NAME,
            "split": self.SPLIT,
            "repo": repo,
            "output": str(output),
            "cases": written,
            "scanned": scanned,
        }

    def _load_datasets_module(self):
        try:
            import datasets
        except ImportError as exc:
            raise RuntimeError("SWE-QA-Pro preparation needs the `datasets` package. Run `uv sync`.") from exc
        return datasets
