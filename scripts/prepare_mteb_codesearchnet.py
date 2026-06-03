from __future__ import annotations

import argparse
import json
from pathlib import Path

from code_diver.benchmarks import BenchmarkPreparation
from code_diver.benchmarks.mteb_codesearchnet_preparer import MtebCodeSearchNetPreparer


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare an MTEB CodeSearchNetRetrieval benchmark corpus.")
    parser.add_argument("--dataset", default="mteb/CodeSearchNetRetrieval")
    parser.add_argument("--language", default="python")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(".code-diver/benchmarks/mteb-codesearchnet-python"),
    )
    args = parser.parse_args()
    preparation = BenchmarkPreparation(
        kind="mteb_codesearchnet",
        dataset_name=args.dataset,
        language=args.language,
        limit=args.limit,
        output_root=args.output_root,
        estimated_download_mb=25,
    )
    manifest = MtebCodeSearchNetPreparer(preparation).run()
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
