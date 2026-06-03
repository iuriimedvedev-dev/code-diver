from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Append compact eval partial snapshots to a log.")
    parser.add_argument("--partial-dir", type=Path, required=True)
    parser.add_argument("--output-glob", required=True)
    parser.add_argument("--expected-outputs", type=int, default=0)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--interval-seconds", type=float, default=300)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    while True:
        write_snapshot(args.partial_dir, args.output_glob, args.expected_outputs, args.log)
        if args.once or is_complete(args.output_glob, args.expected_outputs):
            return 0
        time.sleep(max(args.interval_seconds, 1))


def write_snapshot(partial_dir: Path, output_glob: str, expected_outputs: int, log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    partials = load_partials(partial_dir)
    output_count = len(list(Path().glob(output_glob)))
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{timestamp()}] outputs={output_count}/{expected_outputs or '?'} partials={len(partials)}\n")
        for payload in partials:
            metrics = payload.get("metrics") or {}
            handle.write(
                "  "
                f"{payload.get('hypothesis')} "
                f"completed={payload.get('completed_cases')}/{payload.get('total_cases')} "
                f"hit10={format_float(metrics.get('hit_rate@10'))} "
                f"hit5={format_float(metrics.get('hit_rate@5'))} "
                f"recall10={format_float(metrics.get('recall@10'))} "
                f"mean_ms={format_float(metrics.get('search_duration_ms_mean'), digits=0)} "
                f"degraded={metrics.get('degraded_cases', 0)} "
                f"errors={len(payload.get('errors') or [])}\n"
            )
        if output_count >= expected_outputs > 0:
            handle.write(f"[{timestamp()}] complete\n")


def load_partials(partial_dir: Path) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for path in sorted(partial_dir.glob("**/*.partial.json")):
        try:
            payloads.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            payloads.append({"hypothesis": str(path), "metrics": {}, "errors": [str(exc)]})
    return sorted(payloads, key=lambda item: str(item.get("hypothesis") or ""))


def is_complete(output_glob: str, expected_outputs: int) -> bool:
    return expected_outputs > 0 and len(list(Path().glob(output_glob))) >= expected_outputs


def format_float(value: Any, *, digits: int = 3) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "n/a"


def timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
