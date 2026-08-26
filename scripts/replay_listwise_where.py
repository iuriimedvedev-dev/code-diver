"""Replay a listwise LLM ranking experiment over a JSONL candidate dump."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

LISTWISE_RANK_PROMPT_TEMPLATE = """Rank the candidates for this developer question.
Prefer implementation and engine files that control execution or behavior over Dialog,
Handler, preview, or UI files. Output only a JSON object with the key
"ranked_indices", whose value is a complete ranking of candidate indices (zero-based).

Developer question: {query}

Candidates:
{candidates}
"""


@dataclass(frozen=True, slots=True)
class Candidate:
    path: str
    score: float
    snippet: str


@dataclass(frozen=True, slots=True)
class DumpRecord:
    query_id: str
    query_text: str
    candidates: tuple[Candidate, ...]
    gold_paths: tuple[str, ...]


class LLMClient(Protocol):
    def complete(self, prompt: str) -> str:
        ...


class OpenAICompatibleClient:
    def __init__(self, api_key: str, endpoint: str, model: str, timeout: float = 120.0) -> None:
        self.api_key = api_key
        self.endpoint = endpoint
        self.model = model
        self.timeout = timeout

    def complete(self, prompt: str) -> str:
        payload = json.dumps(
            {"model": self.model, "messages": [{"role": "user", "content": prompt}], "temperature": 0}
        ).encode("utf-8")
        request = Request(
            self.endpoint,
            data=payload,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"LLM request failed: {exc}") from exc
        try:
            return str(body["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("LLM response did not contain choices[0].message.content") from exc


def _text(value: Any) -> str:
    return str(value) if value is not None else ""


def _candidate(value: Any) -> Candidate:
    if isinstance(value, str):
        return Candidate(value, 0.0, "")
    if not isinstance(value, dict):
        raise ValueError("candidate must be a path string or object")
    return Candidate(_text(value.get("path")), float(value.get("score", 0.0)), _text(value.get("snippet", value.get("body", ""))))


def load_dump(path: Path) -> list[DumpRecord]:
    records: list[DumpRecord] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                if not isinstance(raw, dict):
                    raise ValueError("record must be an object")
                rich = "query_id" in raw or "query_text" in raw
                query_id = _text(raw.get("query_id" if rich else "id"))
                query_text = _text(raw.get("query_text" if rich else "query"))
                gold = tuple(_text(item) for item in raw.get("gold_paths" if rich else "expected", []))
                raw_candidates = raw.get("candidates")
                candidates = tuple(_candidate(item) for item in raw_candidates) if raw_candidates is not None else tuple(
                    Candidate(item, 0.0, "") for item in gold
                )
                if not query_id or not query_text:
                    raise ValueError("record requires an id and query")
                records.append(DumpRecord(query_id, query_text, candidates, gold))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"{path}:{line_number}: invalid dump record: {exc}") from exc
    return records


def file_recall_at_k(records: list[DumpRecord], ranked: list[list[str]], k: int = 10) -> float:
    if not records:
        return 0.0
    values = []
    for record, paths in zip(records, ranked, strict=True):
        gold = set(record.gold_paths)
        values.append(len(gold.intersection(paths[:k])) / len(gold) if gold else 0.0)
    return sum(values) / len(values)


def reciprocal_rank_at_k(records: list[DumpRecord], ranked: list[list[str]], k: int = 10) -> float:
    if not records:
        return 0.0
    values = []
    for record, paths in zip(records, ranked, strict=True):
        gold = set(record.gold_paths)
        rank = next((index for index, path in enumerate(paths[:k], 1) if path in gold), None) if gold else None
        values.append(1.0 / rank if rank is not None else 0.0)
    return sum(values) / len(values)


def build_listwise_prompt(record: DumpRecord, path_only: bool = False) -> str:
    lines = []
    for index, candidate in enumerate(record.candidates):
        detail = f"{index}: {candidate.path} (score={candidate.score:g})"
        if not path_only and candidate.snippet:
            detail += f"\n   snippet: {candidate.snippet}"
        lines.append(detail)
    return LISTWISE_RANK_PROMPT_TEMPLATE.format(query=record.query_text, candidates="\n".join(lines))


def parse_ranking(text: str, candidate_count: int) -> list[int]:
    parsed: Any = None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(?:\d+\s*[,.)]?\s*)+", text)
        if match:
            parsed = [int(value) for value in re.findall(r"\d+", match.group())]
    if isinstance(parsed, dict):
        for key in ("ranked_indices", "ranking", "indices"):
            if key in parsed:
                parsed = parsed[key]
                break
    if not isinstance(parsed, list) or not all(isinstance(item, int) and not isinstance(item, bool) for item in parsed):
        raise ValueError("model output must contain a JSON index list")
    result: list[int] = []
    for index in parsed:
        if index < 0 or index >= candidate_count:
            raise ValueError(f"model returned candidate index out of range: {index}")
        if index not in result:
            result.append(index)
    result.extend(index for index in range(candidate_count) if index not in result)
    return result[:10]


def _identity(records: list[DumpRecord]) -> list[list[str]]:
    return [[candidate.path for candidate in record.candidates[:10]] for record in records]


def _metrics(records: list[DumpRecord], ranked: list[list[str]]) -> dict[str, float]:
    return {"file_recall_at_10": file_recall_at_k(records, ranked), "mrr_at_10": reciprocal_rank_at_k(records, ranked)}


def _client_from_env() -> OpenAICompatibleClient:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for listwise modes")
    endpoint = os.getenv("OPENAI_ENDPOINT", os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions"))
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    return OpenAICompatibleClient(api_key, endpoint, model)


def main(argv: list[str] | None = None, client: LLMClient | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_dump = Path("datasets/intellij_eval_where_only.jsonl")
    parser.add_argument("--dump", type=Path, default=default_dump if default_dump.exists() else None)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--baseline", action="store_true")
    parser.add_argument("--path-only", action="store_true")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args(argv)
    if args.dump is None:
        parser.error("--dump is required when datasets/intellij_eval_where_only.jsonl does not exist")
    if args.json_out is not None and args.json_out.exists():
        parser.error(f"refusing to overwrite existing {args.json_out}")
    try:
        records = load_dump(args.dump)
        output: dict[str, Any] = {"dump": str(args.dump), "records": len(records)}
        expected_only = all(tuple(candidate.path for candidate in record.candidates) == record.gold_paths for record in records)
        if expected_only:
            output["candidate_note"] = "candidates are expected-only synthesized controls"
        if args.dry_run:
            covered = sum(bool(set(record.gold_paths).intersection(candidate.path for candidate in record.candidates[:20])) for record in records)
            output["mode"] = "dry_run"
            output["metrics"] = {"gold_in_pool_at_20": covered / len(records) if records else 0.0}
        else:
            if args.baseline:
                ranked = _identity(records)
                output["mode"] = "baseline"
                output["metrics"] = _metrics(records, ranked)
            else:
                active_client = client or _client_from_env()
                ranked = []
                for record in records:
                    ranked_indices = parse_ranking(active_client.complete(build_listwise_prompt(record, args.path_only)), len(record.candidates))
                    ranked.append([record.candidates[index].path for index in ranked_indices])
                output["mode"] = "path_only" if args.path_only else "full"
                output["metrics"] = _metrics(records, ranked)
        rendered = json.dumps(output, indent=2)
        print(rendered)
        if args.json_out is not None:
            args.json_out.write_text(rendered + "\n", encoding="utf-8")
            print(f"wrote {args.json_out}", file=sys.stderr)
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
