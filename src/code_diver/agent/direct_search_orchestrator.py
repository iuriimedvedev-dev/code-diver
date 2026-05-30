from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from ..generation import GenerationProvider, GenerationResult
from .direct_agent_logger import DirectAgentLogger
from .direct_search_prompt_builder import DirectSearchPromptBuilder
from .direct_search_result import DirectSearchResult
from .direct_tool_executor import DirectToolExecutor
from .json_response_parser import JsonResponseParser
from .model_cost_estimator import ModelCostEstimator
from .tool_call import ToolCall
from .tool_observation_compressor import ToolObservationCompressor
from .tool_result import ToolResult


class DirectSearchOrchestrator:
    MAX_ROUNDS = 5
    MAX_PARALLEL_TOOLS = 6

    def __init__(
        self,
        *,
        root: Path,
        generation_provider: GenerationProvider,
        allowed_tools: list[str],
        log_path: Path,
        include_prompts: bool = True,
        search_handler: Callable[[str, int], str] | None = None,
        exclude: list[str] | None = None,
        max_file_bytes: int = 1_000_000,
    ):
        self.root = root
        self.generation_provider = generation_provider
        self.allowed_tools = allowed_tools
        self.search_handler = search_handler
        self.exclude = exclude or []
        self.max_file_bytes = max_file_bytes
        self.logger = DirectAgentLogger(log_path, include_prompts=include_prompts)
        self.prompt_builder = DirectSearchPromptBuilder()
        self.response_parser = JsonResponseParser()
        self.observation_compressor = ToolObservationCompressor()
        self.cost_estimator = ModelCostEstimator()

    def search(self, *, hypothesis_name: str, case_id: str, query: str, limit: int) -> DirectSearchResult:
        executor = DirectToolExecutor(
            self.root,
            self.allowed_tools,
            search_handler=self.search_handler,
            exclude=self.exclude,
            max_file_bytes=self.max_file_bytes,
        )
        history: list[dict[str, Any]] = []
        result = DirectSearchResult()
        self.logger.write(
            "search_case_started",
            {
                "hypothesis": hypothesis_name,
                "case_id": case_id,
                "query": query,
                "allowed_tools": self.allowed_tools,
            },
        )
        try:
            for round_index in range(1, self.MAX_ROUNDS + 1):
                prompt = self.prompt_builder.build(
                    hypothesis_name=hypothesis_name,
                    query=query,
                    tool_manifest=executor.manifest(),
                    history=history,
                    limit=limit,
                )
                response = self._generate(prompt, result)
                self._log_model_turn(case_id, round_index, prompt, response)
                parsed = self.response_parser.parse(response.text)
                history.append({"round": round_index, "assistant": parsed})
                if "results" in parsed:
                    result.retrieved = self._parse_results(parsed["results"], limit)
                    self.logger.write(
                        "search_case_completed",
                        {"case_id": case_id, "retrieved": result.retrieved, "usage": result.usage_json()},
                    )
                    return result
                calls = self._parse_tool_calls(parsed)
                if not calls:
                    result.error = "agent_returned_no_tool_calls_or_results"
                    return result
                tool_results = self._execute_tools(executor, calls, result, case_id)
                history.append(
                    {
                        "round": round_index,
                        "tool_results": [
                            {"name": item.name, "ok": item.ok, "content": self.observation_compressor.compress(item.content)}
                            for item in tool_results
                        ],
                    }
                )
            result.error = "max_rounds_exceeded"
            self.logger.write("search_case_failed", {"case_id": case_id, "error": result.error})
            return result
        except Exception as exc:
            result.error = str(exc)
            self.logger.write("search_case_failed", {"case_id": case_id, "error": result.error})
            return result

    def _generate(self, prompt: str, usage: DirectSearchResult) -> GenerationResult:
        started = perf_counter()
        generate_result = getattr(self.generation_provider, "generate_json_result", None)
        if callable(generate_result):
            result = generate_result(prompt)
        else:
            text = self.generation_provider.generate_json(prompt)
            result = GenerationResult(
                text=text,
                model=self.generation_provider.model,
                input_tokens=self._estimate_tokens(prompt),
                output_tokens=self._estimate_tokens(text),
            )
            result.total_tokens = result.input_tokens + result.output_tokens
        if not result.input_tokens and not result.output_tokens:
            result.input_tokens = self._estimate_tokens(prompt)
            result.output_tokens = self._estimate_tokens(result.text)
            result.total_tokens = result.input_tokens + result.output_tokens
        usage.model_calls += 1
        usage.input_tokens += result.input_tokens
        usage.output_tokens += result.output_tokens
        usage.total_tokens += result.total_tokens or result.input_tokens + result.output_tokens
        usage.estimated_cost += self.cost_estimator.estimate(result.model, result.input_tokens, result.output_tokens)
        if result.model not in usage.models:
            usage.models.append(result.model)
        self.logger.write(
            "model_usage",
            {
                "model": result.model,
                "duration_ms": (perf_counter() - started) * 1000,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "total_tokens": result.total_tokens,
            },
        )
        return result

    def _log_model_turn(self, case_id: str, round_index: int, prompt: str, response: GenerationResult) -> None:
        payload: dict[str, Any] = {
            "case_id": case_id,
            "round": round_index,
            "model": response.model,
            "response": response.text,
        }
        if self.logger.include_prompts:
            payload["prompt"] = prompt
        self.logger.write("model_response", payload)

    def _parse_tool_calls(self, payload: dict[str, Any]) -> list[ToolCall]:
        values = payload.get("tool_calls") or []
        if not isinstance(values, list):
            raise ValueError("tool_calls must be a list.")
        calls: list[ToolCall] = []
        for value in values[: self.MAX_PARALLEL_TOOLS]:
            if not isinstance(value, dict):
                continue
            name = str(value.get("name") or "").strip()
            arguments = value.get("arguments") or value.get("args") or {}
            if name:
                calls.append(ToolCall(name=name, arguments=arguments if isinstance(arguments, dict) else {}))
        return calls

    def _execute_tools(
        self,
        executor: DirectToolExecutor,
        calls: list[ToolCall],
        usage: DirectSearchResult,
        case_id: str,
    ) -> list[ToolResult]:
        for call in calls:
            self.logger.write("tool_call", {"case_id": case_id, "name": call.name, "arguments": call.arguments})
        with ThreadPoolExecutor(max_workers=min(len(calls), self.MAX_PARALLEL_TOOLS)) as pool:
            results = list(pool.map(executor.execute, calls))
        usage.tool_calls += len(results)
        for result in results:
            self.logger.write(
                "tool_result",
                {"case_id": case_id, "name": result.name, "ok": result.ok, "content": result.content},
            )
        return results

    def _parse_results(self, values: Any, limit: int) -> list[str]:
        if not isinstance(values, list):
            raise ValueError("results must be a list.")
        paths: list[str] = []
        for value in values[:limit]:
            if isinstance(value, str):
                path = value.strip()
            elif isinstance(value, dict):
                path = str(value.get("path") or value.get("id") or "").strip()
            else:
                path = ""
            if path and path not in paths:
                paths.append(path)
        return paths

    def _estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)
