from __future__ import annotations

from time import perf_counter
from time import sleep

import pytest

from code_diver.agent.parallel_tool_executor import ParallelToolExecutor
from code_diver.agent.tool_call import ToolCall
from code_diver.agent.tool_result import ToolResult


pytestmark = pytest.mark.unit


def test_parallel_tool_executor_runs_independent_calls_concurrently() -> None:
    calls = [ToolCall("slow", {"index": index}) for index in range(3)]

    def execute(call: ToolCall) -> ToolResult:
        sleep(0.12)
        return ToolResult(call.name, str(call.arguments["index"]))

    started = perf_counter()
    results = ParallelToolExecutor(max_parallel=3).execute(calls, execute)
    elapsed = perf_counter() - started

    assert [result.content for result in results] == ["0", "1", "2"]
    assert elapsed < 0.25


def test_parallel_tool_executor_preserves_partial_results_when_one_call_fails() -> None:
    calls = [ToolCall("ok", {}), ToolCall("bad", {}), ToolCall("later", {})]

    def execute(call: ToolCall) -> ToolResult:
        if call.name == "bad":
            raise RuntimeError("tool exploded")
        return ToolResult(call.name, call.name)

    results = ParallelToolExecutor(max_parallel=3).execute(calls, execute)

    assert [(result.name, result.ok, result.content) for result in results] == [
        ("ok", True, "ok"),
        ("bad", False, "tool exploded"),
        ("later", True, "later"),
    ]
