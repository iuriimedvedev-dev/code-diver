from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Expand expected files for duplicate natural-language eval queries.")
    parser.add_argument("--input", type=Path, default=Path("datasets/intellij_eval_1000.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("datasets/intellij_eval_1000.multi_expected.jsonl"))
    args = parser.parse_args()

    rows = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line.strip()]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[normalize_query(str(row.get("query") or ""))].append(row)

    expanded = []
    duplicate_groups = 0
    expanded_rows = 0
    for row in rows:
        group = grouped[normalize_query(str(row.get("query") or ""))]
        if len(group) > 1:
            duplicate_groups += 1 if group[0] is row else 0
            expanded_rows += 1
        expected = []
        seen: set[str] = set()
        for item in group:
            values = item.get("expected") or item.get("relevant") or []
            if isinstance(values, str):
                values = [values]
            for value in values:
                text = str(value)
                if text in seen:
                    continue
                seen.add(text)
                expected.append(text)
        clone = dict(row)
        clone["expected"] = expected
        expanded.append(clone)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in expanded) + "\n", encoding="utf-8")
    print(json.dumps({"rows": len(expanded), "duplicate_groups": duplicate_groups, "expanded_rows": expanded_rows, "output": str(args.output)}, indent=2))
    return 0


def normalize_query(query: str) -> str:
    return " ".join(query.lower().split())


if __name__ == "__main__":
    raise SystemExit(main())
