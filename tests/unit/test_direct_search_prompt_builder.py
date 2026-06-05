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


def test_search_prompt_example_prefers_outline_before_read() -> None:
    prompt = DirectSearchPromptBuilder().build(
        hypothesis_name="bounded_read",
        query="where is user update?",
        tool_manifest=json.dumps([{"name": "code_diver_outline"}, {"name": "code_diver_read"}]),
        history=[],
        limit=5,
    )

    assert '"name": "code_diver_outline"' in prompt
    assert '"symbolLimit": 100' in prompt


def test_search_prompt_describes_ephemeral_search_when_available() -> None:
    prompt = DirectSearchPromptBuilder().build(
        hypothesis_name="h2_ephemeral",
        query="where is user update?",
        tool_manifest=json.dumps([{"name": "code_diver_ephemeral_search"}, {"name": "code_diver_read"}]),
        history=[],
        limit=5,
    )

    assert "code_diver_ephemeral_search is a localized deep vector search tool" in prompt
    assert "not as first-pass discovery" in prompt
    assert "ephemeral_search" in prompt
    assert '"files": ["src/example.py"]' in prompt


def test_search_prompt_describes_hybrid_tool_routing_policy() -> None:
    prompt = DirectSearchPromptBuilder().build(
        hypothesis_name="hybrid",
        query="where is command creation handled?",
        tool_manifest=json.dumps(
            [
                {"name": "code_diver_search"},
                {"name": "code_diver_outline"},
                {"name": "code_diver_symbols"},
                {"name": "code_diver_read"},
                {"name": "code_diver_grep"},
                {"name": "code_diver_rg"},
            ]
        ),
        history=[],
        limit=10,
    )

    assert "Hybrid tool policy" in prompt
    assert "Semantic or informal" in prompt
    assert "Class/function/method/command/handler/service/model/schema" in prompt
    assert "multiple allowed signals or by direct evidence from the available tools" in prompt
    assert "Never call code_diver_symbols without path" in prompt
    assert "prefer code_diver_outline before code_diver_read" in prompt
    assert "code_diver_read has a hard budget of 10 calls per case" in prompt
    assert "Verify cheaply with code_diver_grep, code_diver_rg, code_diver_outline, code_diver_symbols" in prompt
    assert "code_diver_grep is literal substring search only" in prompt
    assert "use code_diver_rg" in prompt


def test_search_prompt_describes_agentic_h3_multiquery_policy() -> None:
    prompt = DirectSearchPromptBuilder().build(
        hypothesis_name="ai_h3_agentic_gemini_flash_lite",
        query="where is command creation handled?",
        tool_manifest=json.dumps(
            [
                {"name": "code_diver_h3_search"},
                {"name": "code_diver_outline"},
                {"name": "code_diver_rg"},
                {"name": "code_diver_rerank"},
            ]
        ),
        history=[],
        limit=10,
    )

    assert "code_diver_h3_search as the strongest first-pass candidate tool" in prompt
    assert "Choose precise code-like queries yourself" in prompt
    assert "You may call it multiple times with different queries" in prompt
    assert "Think of 2-4 precise code-search queries" in prompt
    assert "tool_calls in parallel" in prompt


def test_search_prompt_only_mentions_available_tools() -> None:
    prompt = DirectSearchPromptBuilder().build(
        hypothesis_name="ephemeral_rerank_only",
        query="where is user update?",
        tool_manifest=json.dumps(
            [
                {"name": "code_diver_search"},
                {"name": "code_diver_ephemeral_search"},
                {"name": "code_diver_rerank"},
            ]
        ),
        history=[],
        limit=10,
    )

    assert "Never call a tool that is not listed" in prompt
    assert "code_diver_ephemeral_search is a localized deep vector search tool" in prompt
    assert "code_diver_read has a hard budget" not in prompt
    assert "code_diver_read is for verification" not in prompt
    assert "code_diver_grep" not in prompt
    assert "code_diver_symbols" not in prompt


def test_search_prompt_describes_rerank_tool_when_available() -> None:
    prompt = DirectSearchPromptBuilder().build(
        hypothesis_name="hybrid_rerank_tool",
        query="where is command creation handled?",
        tool_manifest=json.dumps([{"name": "code_diver_search"}, {"name": "code_diver_rerank"}]),
        history=[],
        limit=10,
    )

    assert "code_diver_rerank is an AI ranking tool" in prompt
    assert "MUST call code_diver_rerank" in prompt
    assert "call code_diver_rerank before final results" in prompt
    assert "Do not call it in the same parallel batch" in prompt


def test_search_prompt_describes_adaptive_multi_pass_policy() -> None:
    prompt = DirectSearchPromptBuilder().build(
        hypothesis_name="adaptive_agentic_search",
        query="where is command creation handled?",
        tool_manifest=json.dumps([{"name": "code_diver_search"}, {"name": "code_diver_rg"}]),
        history=[],
        limit=10,
    )

    assert "iterative search loop" in prompt
    assert "different targeted probe or rewritten-query pass" in prompt


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
