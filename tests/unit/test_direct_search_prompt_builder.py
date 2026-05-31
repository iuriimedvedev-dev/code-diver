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
    assert "universal hybrid code-search orchestrator" in prompt
    assert "tool_calls in parallel" in prompt


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


def test_search_prompt_describes_hybrid_tool_routing_policy() -> None:
    prompt = DirectSearchPromptBuilder().build(
        hypothesis_name="hybrid",
        query="where is command creation handled?",
        tool_manifest=json.dumps([{"name": "code_diver_search"}, {"name": "code_diver_symbols"}]),
        history=[],
        limit=10,
    )

    assert "Hybrid tool policy" in prompt
    assert "Semantic or informal" in prompt
    assert "Class/function/method/command/handler/service/model/schema" in prompt
    assert "multiple signals or by direct read evidence" in prompt


def test_search_prompt_compacts_old_history_but_keeps_recent_observation() -> None:
    history = [
        {"round": 1, "assistant": {"reason": "old search", "tool_calls": [{"name": "code_diver_search"}]}},
        {"round": 1, "tool_results": [{"name": "code_diver_search", "content": {"candidates": ["old"]}}]},
        {"round": 2, "assistant": {"reason": "new search", "tool_calls": [{"name": "code_diver_search"}]}},
        {"round": 2, "tool_results": [{"name": "code_diver_search", "content": {"candidates": ["new"]}}]},
    ]

    prompt = DirectSearchPromptBuilder().build(
        hypothesis_name="vector_only",
        query="where is auth?",
        tool_manifest=json.dumps([{"name": "code_diver_search"}]),
        history=history,
        limit=10,
    )

    assert "previousRounds" in prompt
    assert "old search" in prompt
    assert '"candidates": ["old"]' not in prompt
    assert "new" in prompt
