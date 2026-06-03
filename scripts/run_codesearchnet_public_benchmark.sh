#!/usr/bin/env bash
set -euo pipefail

mkdir -p .code-diver/reports/codesearchnet

uv run python scripts/prepare_mteb_codesearchnet.py \
  --language python \
  --limit 1000 \
  --output-root .code-diver/benchmarks/mteb-codesearchnet-python

uv run code-diver \
  --config configs/codesearchnet-mteb-python-hash.yml \
  evaluate \
  --benchmark codesearchnet-mteb-python-1000 \
  --limit 10 \
  --json \
  --yes \
  --reindex \
  > .code-diver/reports/codesearchnet/codesearchnet-mteb-python-hash.json
