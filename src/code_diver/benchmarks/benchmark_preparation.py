from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BenchmarkPreparation:
    kind: str
    dataset_name: str
    language: str
    limit: int
    output_root: Path
    estimated_download_mb: int

    @property
    def corpus_dir(self) -> Path:
        return self.output_root / "corpus"

    @property
    def dataset_path(self) -> Path:
        if self.kind == "mteb_swebench":
            return self.output_root / f"swebench_code_retrieval_{self.limit}.jsonl"
        return self.output_root / f"codesearchnet_{self.language}_{self.limit}.jsonl"

    @property
    def manifest_path(self) -> Path:
        return self.output_root / "manifest.json"
