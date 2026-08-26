"""Replay listwise ranking over a JSONL dump without loading an application config."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)

LISTWISE_RANK_PROMPT_TEMPLATE: Final[str] = """Rank the candidates for this developer question.
Prefer implementation and engine files that control execution or behavior over Dialog,
Handler, preview, or UI files. Return JSON only with the key "ranked_indices". Its value
must be a complete ranking of the candidate indices (zero-based), with no duplicates.

Developer question:
{query}

Candidates:
{candidates}
"""


@dataclass(frozen=True, slots=True)
class Candidate:
    path: str
    score: float = 0.0
    snippet: str = ""


@dataclass(frozen=True, slots=True)
class QueryPool:
    query_id: str
    query_text: str
    candidates: tuple[Candidate, ...]
    gold_paths: tuple[str, ...]


DumpRecord = QueryPool


class DumpParseError(ValueError):
    """A JSONL dump exists but contains an invalid record."""


class LLMClient(Protocol):
    def complete(self, prompt: str) -> str:
        ...


class OpenAICompatibleClient:
    def __init__(self, api_key: str, endpoint: str, model: str, timeout: float = 120.0) -> None:
        self.api_key, self.endpoint, self.model, self.timeout = api_key, endpoint, model, timeout

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
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("LLM response did not contain choices[0].message.content") from exc
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("LLM response content was empty")
        return content


def _text(value: Any) -> str:
    return str(value) if value is not None else ""


def _candidate(value: Any) -> Candidate:
    if isinstance(value, str):
        return Candidate(value)
    if not isinstance(value, dict):
        raise ValueError("candidate must be a path string or object")
    return Candidate(
        path=_text(value.get("path")),
        score=float(value.get("score", 0.0)),
        snippet=_text(value.get("snippet", value.get("body", ""))),
    )


def load_dump(path: Path) -> list[QueryPool]:
    records: list[QueryPool] = []
    try:
        handle = path.open(encoding="utf-8")
    except OSError:
        raise
    with handle:
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
                gold_value = raw.get("gold_paths" if rich else "expected", [])
                if not isinstance(gold_value, list):
                    raise ValueError("gold paths must be a list")
                gold_paths = tuple(_text(item) for item in gold_value if _text(item))
                raw_candidates = raw.get("candidates")
                candidates = (
                    tuple(_candidate(item) for item in raw_candidates)
                    if raw_candidates is not None
                    else tuple(Candidate(path) for path in gold_paths)
                )
                if not query_id or not query_text:
                    raise ValueError("record requires an id and query")
                if any(not candidate.path for candidate in candidates):
                    raise ValueError("candidate path must not be empty")
                records.append(QueryPool(query_id, query_text, candidates, gold_paths))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise DumpParseError(f"{path}:{line_number}: invalid dump record: {exc}") from exc
    return records


def file_recall_at_k(ranked_paths: Sequence[str], gold_paths: Sequence[str], k: int = 10) -> float:
    if k < 0:
        raise ValueError("k must not be negative")
    if ranked_paths and isinstance(ranked_paths[0], QueryPool):
        records = ranked_paths
        ranked_lists = gold_paths
        return _mean(
            file_recall_at_k(paths, record.gold_paths, k)
            for record, paths in zip(records, ranked_lists, strict=True)
        )
    gold = set(gold_paths)
    return len(gold.intersection(ranked_paths[:k])) / len(gold) if gold else 0.0


def reciprocal_rank_at_k(ranked_paths: Sequence[str], gold_paths: Sequence[str], k: int = 10) -> float:
    if k < 0:
        raise ValueError("k must not be negative")
    if ranked_paths and isinstance(ranked_paths[0], QueryPool):
        records = ranked_paths
        ranked_lists = gold_paths
        return _mean(
            reciprocal_rank_at_k(paths, record.gold_paths, k)
            for record, paths in zip(records, ranked_lists, strict=True)
        )
    gold = set(gold_paths)
    for rank, path in enumerate(ranked_paths[:k], 1):
        if path in gold:
            return 1.0 / rank
    return 0.0


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def build_listwise_prompt(
    query_text: str | QueryPool, candidates: Sequence[Candidate] | None = None, path_only: bool = False
) -> str:
    if isinstance(query_text, QueryPool):
        candidates = query_text.candidates
        query_text = query_text.query_text
    if candidates is None:
        raise TypeError("candidates are required")
    lines: list[str] = []
    for index, candidate in enumerate(candidates):
        line = f"{index}: {candidate.path} (score={candidate.score:g})"
        if not path_only and candidate.snippet:
            line += f"\n   snippet: {candidate.snippet}"
        lines.append(line)
    return LISTWISE_RANK_PROMPT_TEMPLATE.format(query=query_text, candidates="\n".join(lines))


def parse_listwise_response(response: str, candidates: Sequence[Candidate]) -> list[Candidate]:
    try:
        payload: Any = json.loads(response)
    except json.JSONDecodeError:
        match = re.search(r"(?:\d+\s*[,.)]?\s*)+", response)
        payload = [int(value) for value in re.findall(r"\d+", match.group())] if match else None
    if isinstance(payload, dict):
        payload = next((payload[key] for key in ("ranked_indices", "ranking", "indices") if key in payload), None)
    if not isinstance(payload, list) or not all(isinstance(item, int) and not isinstance(item, bool) for item in payload):
        raise ValueError("model output must contain a JSON index list")
    indices: list[int] = []
    for index in payload:
        if index < 0 or index >= len(candidates):
            raise ValueError(f"model returned candidate index out of range: {index}")
        if index in indices:
            raise ValueError(f"model returned duplicate candidate index: {index}")
        indices.append(index)
    indices.extend(index for index in range(len(candidates)) if index not in indices)
    return [candidates[index] for index in indices]


def parse_ranking(response: str, candidate_count: int) -> list[int]:
    try:
        payload: Any = json.loads(response)
    except json.JSONDecodeError:
        match = re.search(r"(?:\d+\s*[,.)]?\s*)+", response)
        payload = [int(value) for value in re.findall(r"\d+", match.group())] if match else None
    if isinstance(payload, dict):
        payload = next((payload[key] for key in ("ranked_indices", "ranking", "indices") if key in payload), None)
    if not isinstance(payload, list):
        raise ValueError("model output must contain a JSON index list")
    result: list[int] = []
    for index in payload:
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < candidate_count:
            raise ValueError(f"model returned invalid candidate index: {index}")
        if index not in result:
            result.append(index)
    result.extend(index for index in range(candidate_count) if index not in result)
    return result


def _client_from_env() -> OpenAICompatibleClient:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for listwise mode")
    endpoint = os.getenv("OPENAI_ENDPOINT", os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions"))
    return OpenAICompatibleClient(api_key, endpoint, os.getenv("OPENAI_MODEL", "gpt-4o-mini"))


def main(argv: list[str] | None = None, client: LLMClient | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--path-only", action="store_true")
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--top-k-pool", type=int, default=20)
    parser.add_argument("--top-k-out", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.top_k_pool < 1 or args.top_k_out < 1:
        parser.error("--top-k-pool and --top-k-out must be positive")
    if args.output is not None and args.output.exists():
        parser.error(f"refusing to overwrite existing {args.output}")
    try:
        records = load_dump(args.dump)
        if args.dry_run:
            gold_in_pool = sum(
                bool(set(record.gold_paths).intersection(candidate.path for candidate in record.candidates[: args.top_k_pool]))
                for record in records
            )
            result: dict[str, Any] = {
                "mode": "dry_run",
                "dump": str(args.dump),
                "records": len(records),
                "top_k_pool": args.top_k_pool,
                "top_k_out": args.top_k_out,
                "pool": {"records_with_gold": gold_in_pool},
            }
        else:
            active_client = None if args.baseline else (client or _client_from_env())
            ranked: list[list[str]] = []
            for record in records:
                pool = record.candidates[: args.top_k_pool]
                if args.baseline:
                    ordered = pool
                else:
                    assert active_client is not None
                    ordered = parse_listwise_response(
                        active_client.complete(build_listwise_prompt(record.query_text, pool, args.path_only)), pool
                    )
                ranked.append([candidate.path for candidate in ordered])
                LOGGER.info("ranked query %s (%d candidates)", record.query_id, len(pool))
            result = {
                "mode": "baseline" if args.baseline else ("path_only" if args.path_only else "full"),
                "dump": str(args.dump),
                "records": len(records),
                "top_k_pool": args.top_k_pool,
                "top_k_out": args.top_k_out,
                "metrics": {
                    "file_recall_at_k": _mean(
                        [file_recall_at_k(paths, record.gold_paths, args.top_k_out) for record, paths in zip(records, ranked, strict=True)]
                    ),
                    "mrr_at_k": _mean(
                        [reciprocal_rank_at_k(paths, record.gold_paths, args.top_k_out) for record, paths in zip(records, ranked, strict=True)]
                    ),
                },
            }
        rendered = json.dumps(result, indent=2)
        print(rendered)
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n", encoding="utf-8")
            LOGGER.info("wrote %s", args.output)
        return 0
    except (OSError, DumpParseError, RuntimeError, ValueError) as exc:
        LOGGER.error("%s", exc)
        return 2


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(main())
