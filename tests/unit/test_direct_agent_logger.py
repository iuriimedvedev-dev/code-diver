from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from code_diver.agent.direct_agent_logger import DirectAgentLogger


pytestmark = pytest.mark.unit


def test_direct_agent_logger_instances_share_artifact_lock(tmp_path) -> None:
    log_path = tmp_path / "agent.jsonl"
    first = DirectAgentLogger(log_path, include_prompts=True)
    second = DirectAgentLogger(log_path, include_prompts=True)
    payload = {"text": "x" * 60_000}

    def write_events(logger: DirectAgentLogger, prefix: str) -> None:
        for index in range(12):
            logger.write("large_event", {"prefix": prefix, "index": index, **payload})

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(write_events, first, "a"),
            executor.submit(write_events, second, "b"),
        ]
        for future in futures:
            future.result()

    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 24
    assert {record["payload"]["prefix"] for record in records} == {"a", "b"}
