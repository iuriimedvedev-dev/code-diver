from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_diver.pi import PiRunLogParser

pytestmark = pytest.mark.unit


def test_pi_run_log_parser_sums_usage_and_tool_calls(tmp_path: Path) -> None:
    log_path = tmp_path / "pi.jsonl"
    log_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "message_end",
                        "message": {
                            "role": "assistant",
                            "model": "gemini",
                            "usage": {
                                "input": 10,
                                "output": 5,
                                "cacheRead": 2,
                                "cacheWrite": 1,
                                "totalTokens": 18,
                                "cost": {
                                    "input": 0.1,
                                    "output": 0.2,
                                    "cacheRead": 0.01,
                                    "cacheWrite": 0.02,
                                    "total": 0.33,
                                },
                            },
                        },
                    }
                ),
                json.dumps({"type": "turn_end", "toolResults": [{}, {}]}),
            ]
        ),
        encoding="utf-8",
    )

    summary = PiRunLogParser().parse(log_path)

    assert summary.model_calls == 1
    assert summary.tool_calls == 2
    assert summary.total_tokens == 18
    assert summary.total_cost == pytest.approx(0.33)
    assert summary.models == ["gemini"]
