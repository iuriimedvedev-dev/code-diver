from __future__ import annotations

import hashlib
import json
import re
import shutil
from typing import Any

from .benchmark_preparation import BenchmarkPreparation


class MtebCodeSearchNetPreparer:
    def __init__(self, preparation: BenchmarkPreparation):
        self.preparation = preparation

    def run(self) -> dict[str, Any]:
        datasets = self._load_datasets_module()
        language = self.preparation.language
        dataset_name = self.preparation.dataset_name
        corpus_rows = list(datasets.load_dataset(dataset_name, f"{language}-corpus", split="test"))
        query_rows = list(datasets.load_dataset(dataset_name, f"{language}-queries", split="test"))
        qrel_rows = list(datasets.load_dataset(dataset_name, f"{language}-qrels", split="test"))
        selected_qrels = qrel_rows[: self.preparation.limit]
        corpus_by_id = {str(row["id"]): row for row in corpus_rows}
        queries_by_id = {str(row["id"]): row for row in query_rows}

        if self.preparation.output_root.exists():
            shutil.rmtree(self.preparation.output_root)
        self.preparation.corpus_dir.mkdir(parents=True)

        corpus_files = 0
        cases: list[dict[str, Any]] = []
        for index, qrel in enumerate(selected_qrels, start=1):
            query_id = str(qrel["query-id"])
            corpus_id = str(qrel["corpus-id"])
            corpus = corpus_by_id[corpus_id]
            query = queries_by_id[query_id]
            rel_path = self._rel_path(index, corpus_id, corpus)
            target = self.preparation.corpus_dir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(corpus["text"]).rstrip() + "\n", encoding="utf-8")
            corpus_files += 1
            cases.append(
                {
                    "id": f"{language}-{query_id}",
                    "query": str(query["text"]).strip(),
                    "expected": [rel_path],
                    "metadata": {
                        "benchmark": dataset_name,
                        "language": language,
                        "query_id": query_id,
                        "corpus_id": corpus_id,
                        "score": qrel.get("score", 1),
                    },
                }
            )

        self.preparation.dataset_path.write_text(
            "".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases),
            encoding="utf-8",
        )
        manifest = {
            "benchmark": dataset_name,
            "language": language,
            "limit": self.preparation.limit,
            "corpus_dir": str(self.preparation.corpus_dir),
            "dataset": str(self.preparation.dataset_path),
            "cases": len(cases),
            "corpus_files": corpus_files,
        }
        self.preparation.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest

    def _load_datasets_module(self):
        try:
            import datasets
        except ImportError as exc:
            raise RuntimeError(
                "The benchmark downloader needs the `datasets` package. "
                "Install dependencies with `uv sync` and retry."
            ) from exc
        return datasets

    def _rel_path(self, index: int, corpus_id: str, corpus: dict[str, Any]) -> str:
        title = str(corpus.get("title") or "")
        stem = self._slug(title) or f"snippet_{index:04d}"
        digest = hashlib.sha1(corpus_id.encode("utf-8")).hexdigest()[:10]
        return f"{self.preparation.language}/{index:04d}_{stem}_{digest}.py"

    def _slug(self, text: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("._-").lower()
        return slug[:80]
