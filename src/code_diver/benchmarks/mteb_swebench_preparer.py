from __future__ import annotations

import hashlib
import json
import shutil
from typing import Any

from .benchmark_preparation import BenchmarkPreparation
from .benchmark_preparer_utils import extension_for_language, load_datasets_module


class MtebSweBenchPreparer:
    """Prepares `mteb/SWEbenchCodeRetrieval`-shaped benchmarks.

    This dataset is packaged differently from `mteb/CodeSearchNetRetrieval`, which
    `MtebCodeSearchNetPreparer` targets:

    * It is not split per language -- there is a single flat `corpus`/`queries`/`default`
      (qrels) config, not `{language}-corpus`/`{language}-queries`/`{language}-qrels`.
    * Corpus and query rows key on `_id`, not `id`.
    * Critically, the `corpus` split is the FULL per-instance candidate pool used by the
      MTEB task (tens of thousands of files across every SWE-bench Verified repo snapshot),
      not just the files referenced by a positive qrel. `MtebCodeSearchNetPreparer` only
      writes qrel-referenced rows to disk, which is safe for CodeSearchNetRetrieval (whose
      corpus rows are 1:1 with a query's gold snippet) but would silently shrink this
      benchmark's candidate pool down to ~1 file per query -- inflating hit-rate by removing
      the realistic distractor set. This preparer always writes every row of the `corpus`
      split, regardless of `limit`, so retrieval must discriminate among the full pool.
    """

    _CORPUS_CONFIG = "corpus"
    _QUERIES_CONFIG = "queries"
    _QRELS_CONFIG = "default"

    def __init__(self, preparation: BenchmarkPreparation):
        self.preparation = preparation

    def run(self) -> dict[str, Any]:
        datasets = self._load_datasets_module()
        dataset_name = self.preparation.dataset_name
        corpus_rows = list(datasets.load_dataset(dataset_name, self._CORPUS_CONFIG, split="test"))
        query_rows = list(datasets.load_dataset(dataset_name, self._QUERIES_CONFIG, split="test"))
        qrel_rows = list(datasets.load_dataset(dataset_name, self._QRELS_CONFIG, split="test"))
        positive_qrels = [qrel for qrel in qrel_rows if self._qrel_score(qrel) > 0]
        selected_qrels = positive_qrels[: self.preparation.limit]
        queries_by_id = {str(row["_id"]): row for row in query_rows}

        if self.preparation.output_root.exists():
            shutil.rmtree(self.preparation.output_root)
        self.preparation.corpus_dir.mkdir(parents=True)

        rel_path_by_corpus_id: dict[str, str] = {}
        corpus_files = 0
        for corpus in corpus_rows:
            corpus_id = str(corpus["_id"])
            rel_path = self._rel_path(corpus_id)
            rel_path_by_corpus_id[corpus_id] = rel_path
            target = self.preparation.corpus_dir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(corpus["text"]).rstrip() + "\n", encoding="utf-8")
            corpus_files += 1

        cases: list[dict[str, Any]] = []
        missing_corpus_ids: list[str] = []
        for qrel in selected_qrels:
            query_id = str(qrel["query-id"])
            corpus_id = str(qrel["corpus-id"])
            rel_path = rel_path_by_corpus_id.get(corpus_id)
            if rel_path is None:
                missing_corpus_ids.append(corpus_id)
                continue
            query = queries_by_id[query_id]
            cases.append(
                {
                    "id": f"swebench-{query_id}",
                    "query": str(query["text"]).strip(),
                    "expected": [rel_path],
                    "metadata": {
                        "benchmark": dataset_name,
                        "language": self.preparation.language,
                        "query_id": query_id,
                        "corpus_id": corpus_id,
                        "score": self._qrel_score(qrel),
                    },
                }
            )

        if missing_corpus_ids:
            preview = ", ".join(missing_corpus_ids[:3])
            raise RuntimeError(
                f"{len(missing_corpus_ids)} qrel(s) reference corpus ids missing from the "
                f"'{self._CORPUS_CONFIG}' split of '{dataset_name}', e.g. {preview}."
            )

        self.preparation.dataset_path.write_text(
            "".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases),
            encoding="utf-8",
        )
        manifest = {
            "benchmark": dataset_name,
            "language": self.preparation.language,
            "limit": self.preparation.limit,
            "corpus_dir": str(self.preparation.corpus_dir),
            "dataset": str(self.preparation.dataset_path),
            "cases": len(cases),
            "corpus_files": corpus_files,
            "qrels_total": len(qrel_rows),
            "positive_qrels": len(positive_qrels),
            "selected_qrels": len(selected_qrels),
            "qrel_selection": "score>0_then_first_limit",
            "corpus_scope": "full_corpus_split",
        }
        self.preparation.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest

    def _load_datasets_module(self):
        return load_datasets_module()

    def _qrel_score(self, qrel: dict[str, Any]) -> float:
        try:
            return float(qrel.get("score", 1))
        except (TypeError, ValueError):
            return 0.0

    def _rel_path(self, corpus_id: str) -> str:
        # Corpus ids look like "{owner}/{repo}:{commit}:{path/within/repo.py}". The commit
        # segment must stay in the on-disk path: the same repo+path pair recurs at many
        # different commits across SWE-bench instances (~73% of repo+path pairs in the
        # Python corpus do), and collapsing the commit would let one snapshot silently
        # overwrite another, corrupting the corpus without any error.
        parts = corpus_id.split(":", 2)
        if len(parts) == 3:
            repo, commit, path = parts
            repo_slug = repo.replace("/", "__")
            return f"{repo_slug}/{commit}/{path}"
        digest = hashlib.sha1(corpus_id.encode("utf-8")).hexdigest()[:16]
        extension = extension_for_language(self.preparation.language)
        return f"unmapped/{digest}{extension}"
