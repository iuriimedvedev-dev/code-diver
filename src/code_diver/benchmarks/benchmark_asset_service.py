from __future__ import annotations

import sys
from typing import Any

from .benchmark_profile import BenchmarkProfile
from .mteb_codesearchnet_preparer import MtebCodeSearchNetPreparer
from .mteb_swebench_preparer import MtebSweBenchPreparer


class BenchmarkAssetService:
    def ensure(self, profile: BenchmarkProfile, *, assume_yes: bool = False) -> dict[str, Any] | None:
        preparation = profile.preparation
        if preparation is None or self._assets_exist(profile):
            return None
        if not assume_yes and not self._confirm(profile):
            raise RuntimeError(f"Benchmark assets not prepared for '{profile.name}'.")
        print(f"Preparing benchmark assets for {profile.name}...", file=sys.stderr)
        if preparation.kind == "mteb_codesearchnet":
            return MtebCodeSearchNetPreparer(preparation).run()
        if preparation.kind == "mteb_swebench":
            return MtebSweBenchPreparer(preparation).run()
        raise ValueError(f"Unsupported benchmark preparation kind: {preparation.kind}")

    def _assets_exist(self, profile: BenchmarkProfile) -> bool:
        preparation = profile.preparation
        if preparation is None:
            return True
        return (
            profile.dataset.exists()
            and preparation.corpus_dir.exists()
            and any(preparation.corpus_dir.rglob("*"))
            and preparation.manifest_path.exists()
        )

    def _confirm(self, profile: BenchmarkProfile) -> bool:
        preparation = profile.preparation
        if preparation is None:
            return True
        message = (
            f"Benchmark '{profile.name}' is not downloaded yet.\n"
            f"Source: {preparation.dataset_name} ({preparation.language}, {preparation.limit} cases)\n"
            f"Estimated download/cache: about {preparation.estimated_download_mb} MB.\n"
            f"Local output: {preparation.output_root}\n"
            "Download and prepare it now? [y/N] "
        )
        if not sys.stdin.isatty():
            print(message + "No TTY; pass --yes to allow download.", file=sys.stderr)
            return False
        print(message, end="", file=sys.stderr)
        answer = input().strip().lower()
        return answer in {"y", "yes"}
