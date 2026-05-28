#!/usr/bin/env sh
set -eu

if [ "${1:-}" = "code-diver" ]; then
  shift
fi

exec uv run --no-sync code-diver --config "${CODE_DIVER_CONFIG:-/app/configs/container.yml}" "$@"
