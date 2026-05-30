from __future__ import annotations

import json

import pytest

from code_diver.agent.direct_search_prompt_builder import DirectSearchPromptBuilder


pytestmark = pytest.mark.unit


def test_search_prompt_example_uses_available_vector_tool() -> None:
    prompt = DirectSearchPromptBuilder().build(
        hypothesis_name="vector_only",
        query="where is auth?",
        tool_manifest=json.dumps([{"name": "code_diver_search"}]),
        history=[],
        limit=10,
    )

    assert '"name": "code_diver_search"' in prompt
    assert '"name": "code_diver_rg"' not in prompt


def test_search_prompt_example_uses_available_rg_tool() -> None:
    prompt = DirectSearchPromptBuilder().build(
        hypothesis_name="rg_only",
        query="where is auth?",
        tool_manifest=json.dumps([{"name": "code_diver_rg"}]),
        history=[],
        limit=10,
    )

    assert '"name": "code_diver_rg"' in prompt
    assert '"name": "code_diver_search"' not in prompt
