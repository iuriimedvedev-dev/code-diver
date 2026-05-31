from __future__ import annotations

import asyncio
from collections.abc import Callable

from .tool_call import ToolCall
from .tool_result import ToolResult


class ParallelToolExecutor:
    def __init__(self, max_parallel: int):
        self.max_parallel = max_parallel

    def execute(self, calls: list[ToolCall], execute_one: Callable[[ToolCall], ToolResult]) -> list[ToolResult]:
        return asyncio.run(self.execute_async(calls, execute_one))

    async def execute_async(
        self,
        calls: list[ToolCall],
        execute_one: Callable[[ToolCall], ToolResult],
    ) -> list[ToolResult]:
        if not calls:
            return []
        semaphore = asyncio.Semaphore(max(1, min(len(calls), self.max_parallel)))

        async def run(call: ToolCall) -> ToolResult:
            async with semaphore:
                return await asyncio.to_thread(execute_one, call)

        return await asyncio.gather(*(run(call) for call in calls))
