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


def test_tool_observation_compressor_drops_nested_matches_in_lists_and_sections() -> None:
    compressed = ToolObservationCompressor().compress(
        json.dumps(
            {
                "sections": [
                    {
                        "kind": "rg",
                        "result": {
                            "matches": [{"path": "src/app.py", "line": 1, "text": "raw"}],
                            "candidates": [{"path": "src/app.py", "evidenceLines": [1]}],
                        },
                    }
                ],
                "nested": [
                    {
                        "matches": [{"path": "src/other.py", "line": 2}],
                        "metrics": {"matchCount": 1},
                    }
                ],
            }
        )
    )

    assert compressed["sections"][0]["result"] == {
        "candidates": [{"path": "src/app.py", "evidenceLines": [1]}]
    }
    assert compressed["nested"] == [{"metrics": {"matchCount": 1}}]


def test_tool_observation_compressor_keeps_non_json_content() -> None:
    assert ToolObservationCompressor().compress("plain text") == "plain text"
