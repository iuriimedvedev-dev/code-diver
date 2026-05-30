from __future__ import annotations

import pytest

from code_diver.agent.json_response_parser import JsonResponseParser


pytestmark = pytest.mark.unit


def test_json_response_parser_accepts_plain_json_object() -> None:
    parsed = JsonResponseParser().parse('{"results": [{"path": "src/app.py"}]}')

    assert parsed == {"results": [{"path": "src/app.py"}]}


def test_json_response_parser_extracts_object_with_prefix_and_suffix() -> None:
    parsed = JsonResponseParser().parse(
        'I will answer with JSON.\n{"tool_calls": [{"name": "code_diver_tree"}]}\nDone.'
    )

    assert parsed == {"tool_calls": [{"name": "code_diver_tree"}]}


def test_json_response_parser_ignores_trailing_json_object_after_actionable_object() -> None:
    parsed = JsonResponseParser().parse(
        '{"index_items": [{"path": "src/app.py"}]}\n{"debug": "extra object"}'
    )

    assert parsed == {"index_items": [{"path": "src/app.py"}]}


def test_json_response_parser_prefers_actionable_object() -> None:
    parsed = JsonResponseParser().parse(
        '{"debug": "thinking"}\n{"results": [{"path": "src/commands.py"}]}'
    )

    assert parsed == {"results": [{"path": "src/commands.py"}]}


def test_json_response_parser_rejects_non_object_json() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        JsonResponseParser().parse("[1, 2, 3]")
