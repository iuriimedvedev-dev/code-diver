from __future__ import annotations

import json

import pytest

from code_diver.agent.tool_observation_compressor import ToolObservationCompressor


pytestmark = pytest.mark.unit


def test_tool_observation_compressor_parses_json_and_drops_raw_matches() -> None:
    compressed = ToolObservationCompressor().compress(
        json.dumps(
            {
                "tool": "code_diver_rg",
                "ok": True,
                "result": {
                    "candidates": [{"path": "src/app.py", "evidenceLines": [1]}],
                    "matches": [{"path": "src/app.py", "line": 1}],
                },
                "metrics": {"candidateCount": 1},
            }
        )
    )

    assert compressed["result"] == {"candidates": [{"path": "src/app.py", "evidenceLines": [1]}]}
    assert compressed["metrics"] == {"candidateCount": 1}


def test_tool_observation_compressor_keeps_non_json_content() -> None:
    assert ToolObservationCompressor().compress("plain text") == "plain text"
