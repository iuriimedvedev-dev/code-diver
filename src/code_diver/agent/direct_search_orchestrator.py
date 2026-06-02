from __future__ import annotations

import json
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
from .parallel_tool_executor import ParallelToolExecutor
from .tool_call import ToolCall
from .tool_observation_compressor import ToolObservationCompressor
from .tool_result import ToolResult


class DirectSearchOrchestrator:
    MAX_ROUNDS = 5
    MAX_PARALLEL_TOOLS = 6
    MAX_READ_CALLS = 10

    def __init__(
        self,
        *,
        root: Path,
        generation_provider: GenerationProvider,
        allowed_tools: list[str],
        log_path: Path,
        include_prompts: bool = True,
        search_handler: Callable[[str, int], str] | None = None,
        rerank_handler: Callable[[str, list[dict[str, Any]], int, dict[str, Any]], dict[str, Any]] | None = None,
        ephemeral_search_handler: Callable[[str, list[str], int, dict[str, Any]], dict[str, Any]] | None = None,
        exclude: list[str] | None = None,
        max_file_bytes: int = 1_000_000,
    ):
        self.root = root
        self.generation_provider = generation_provider
        self.allowed_tools = allowed_tools
        self.search_handler = search_handler
        self.rerank_handler = rerank_handler
        self.ephemeral_search_handler = ephemeral_search_handler
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
            rerank_handler=self.rerank_handler,
            ephemeral_search_handler=self.ephemeral_search_handler,
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
        fallback_paths: list[str] = []
        try:
            read_calls_used = 0
            tool_names_used: set[str] = set()
            candidate_tool_calls = 0
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
                    if self._should_continue_for_adaptive_evidence(
                        hypothesis_name,
                        candidate_tool_calls,
                        tool_names_used,
                    ):
                        history.append(
                            {
                                "round": round_index,
                                "runtime_feedback": {
                                    "reason": "adaptive_evidence_required",
                                    "instruction": (
                                        "Do at least one more targeted candidate-producing pass with a different "
                                        "tool or rewritten query, then rerank or verify before final results."
                                    ),
                                    "candidateToolCalls": candidate_tool_calls,
                                    "toolsUsed": sorted(tool_names_used),
                                },
                            }
                        )
                        self.logger.write(
                            "adaptive_evidence_required",
                            {
                                "case_id": case_id,
                                "candidate_tool_calls": candidate_tool_calls,
                                "tools_used": sorted(tool_names_used),
                            },
                        )
                        continue
                    if self._should_force_ephemeral(hypothesis_name, tool_names_used):
                        tool_results, read_calls_used = self._execute_tools(
                            executor,
                            [ToolCall("code_diver_ephemeral_search", {"query": query, "limit": limit})],
                            result,
                            case_id,
                            read_calls_used,
                        )
                        tool_names_used.update(item.name for item in tool_results)
                        candidate_tool_calls += self._candidate_tool_count(tool_results)
                        fallback_paths = self._fallback_paths(tool_results) or fallback_paths
                        history.append(
                            {
                                "round": round_index,
                                "tool_results": [
                                    {
                                        "name": item.name,
                                        "ok": item.ok,
                                        "content": self.observation_compressor.compress(item.content),
                                    }
                                    for item in tool_results
                                ],
                                "runtime_feedback": {"reason": "forced_ephemeral_before_final"},
                            }
                        )
                        continue
                    if self._should_force_rerank(hypothesis_name, tool_names_used):
                        tool_results, read_calls_used = self._execute_tools(
                            executor,
                            [ToolCall("code_diver_rerank", {"query": query, "limit": limit})],
                            result,
                            case_id,
                            read_calls_used,
                        )
                        tool_names_used.update(item.name for item in tool_results)
                        fallback_paths = self._fallback_paths(tool_results) or fallback_paths
                        history.append(
                            {
                                "round": round_index,
                                "tool_results": [
                                    {
                                        "name": item.name,
                                        "ok": item.ok,
                                        "content": self.observation_compressor.compress(item.content),
                                    }
                                    for item in tool_results
                                ],
                            }
                        )
                        continue
                    result.retrieved = self._with_fallback_paths(
                        self._parse_results(parsed["results"], limit),
                        fallback_paths,
                        limit,
                    )
                    self.logger.write(
                        "search_case_completed",
                        {"case_id": case_id, "retrieved": result.retrieved, "usage": result.usage_json()},
                    )
                    return result
                calls = self._parse_tool_calls(parsed)
                if not calls:
                    result.error = "agent_returned_no_tool_calls_or_results"
                    if fallback_paths:
                        return self._complete_with_fallback_error(
                            result,
                            case_id,
                            fallback_paths,
                            limit,
                            result.error,
                            "agent_protocol_error_last_candidates",
                        )
                    return result
                if self._should_force_ephemeral(hypothesis_name, tool_names_used) and not any(
                    call.name == "code_diver_ephemeral_search" for call in calls
                ):
                    tool_results, read_calls_used = self._execute_tools(
                        executor,
                        [ToolCall("code_diver_ephemeral_search", {"query": query, "limit": limit})],
                        result,
                        case_id,
                        read_calls_used,
                    )
                    tool_names_used.update(item.name for item in tool_results)
                    candidate_tool_calls += self._candidate_tool_count(tool_results)
                    fallback_paths = self._fallback_paths(tool_results) or fallback_paths
                    history.append(
                        {
                            "round": round_index,
                            "tool_results": [
                                {
                                    "name": item.name,
                                    "ok": item.ok,
                                    "content": self.observation_compressor.compress(item.content),
                                }
                                for item in tool_results
                            ],
                            "runtime_feedback": {"reason": "forced_ephemeral_before_requested_tools"},
                        }
                    )
                    continue
                tool_results, read_calls_used = self._execute_tools(
                    executor,
                    calls,
                    result,
                    case_id,
                    read_calls_used,
                )
                tool_names_used.update(item.name for item in tool_results)
                candidate_tool_calls += self._candidate_tool_count(tool_results)
                fallback_paths = self._fallback_paths(tool_results) or fallback_paths
                history.append(
                    {
                        "round": round_index,
                        "tool_results": [
                            {"name": item.name, "ok": item.ok, "content": self.observation_compressor.compress(item.content)}
                            for item in tool_results
                        ],
                    }
                )
            if fallback_paths:
                result.retrieved = fallback_paths[:limit]
                self.logger.write(
                    "search_case_completed",
                    {
                        "case_id": case_id,
                        "retrieved": result.retrieved,
                        "usage": result.usage_json(),
                        "fallback": "max_rounds_last_candidates",
                    },
                )
                return result
            result.error = "max_rounds_exceeded"
            self.logger.write("search_case_failed", {"case_id": case_id, "error": result.error})
            return result
        except Exception as exc:
            result.error = str(exc)
            if fallback_paths:
                return self._complete_with_fallback_error(
                    result,
                    case_id,
                    fallback_paths,
                    limit,
                    result.error,
                    "exception_last_candidates",
                )
            self.logger.write("search_case_failed", {"case_id": case_id, "error": result.error})
            return result

    def _should_force_rerank(self, hypothesis_name: str, tool_names_used: set[str]) -> bool:
        if "rerank" not in hypothesis_name and not self._adaptive_hypothesis(hypothesis_name):
            return False
        if "code_diver_rerank" not in self.allowed_tools:
            return False
        if "code_diver_rerank" in tool_names_used:
            return False
        candidate_tools = {
            "code_diver_search",
            "code_diver_grep",
            "code_diver_rg",
            "code_diver_symbols",
            "code_diver_outline",
            "code_diver_ephemeral_search",
            "code_diver_inspect",
        }
        return bool(candidate_tools & tool_names_used)

    def _should_force_ephemeral(self, hypothesis_name: str, tool_names_used: set[str]) -> bool:
        if "ephemeral" not in hypothesis_name.lower():
            return False
        if "code_diver_ephemeral_search" not in self.allowed_tools:
            return False
        if "code_diver_ephemeral_search" in tool_names_used:
            return False
        candidate_tools = {
            "code_diver_search",
            "code_diver_grep",
            "code_diver_rg",
            "code_diver_symbols",
            "code_diver_outline",
            "code_diver_inspect",
        }
        return bool(candidate_tools & tool_names_used)

    def _adaptive_hypothesis(self, hypothesis_name: str) -> bool:
        lowered = hypothesis_name.lower()
        return "adaptive" in lowered or "agentic" in lowered or "deep" in lowered

    def _should_continue_for_adaptive_evidence(
        self,
        hypothesis_name: str,
        candidate_tool_calls: int,
        tool_names_used: set[str],
    ) -> bool:
        if not self._adaptive_hypothesis(hypothesis_name):
            return False
        if candidate_tool_calls < 2:
            return True
        if "code_diver_rerank" in self.allowed_tools and "code_diver_rerank" not in tool_names_used:
            return True
        return False

    def _candidate_tool_count(self, tool_results: list[ToolResult]) -> int:
        return sum(1 for result in tool_results if self._paths_from_tool_result(result))

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
        read_calls_used: int,
    ) -> tuple[list[ToolResult], int]:
        executable: list[tuple[int, ToolCall]] = []
        results_by_index: dict[int, ToolResult] = {}
        for index, call in enumerate(calls):
            self.logger.write("tool_call", {"case_id": case_id, "name": call.name, "arguments": call.arguments})
            requested_reads = self._requested_read_count(call)
            if requested_reads:
                if read_calls_used + requested_reads > self.MAX_READ_CALLS:
                    results_by_index[index] = self._read_budget_exceeded_result(call.name)
                    continue
                read_calls_used += requested_reads
            executable.append((index, call))
        executed_results = ParallelToolExecutor(self.MAX_PARALLEL_TOOLS).execute(
            [call for _, call in executable],
            executor.execute,
        )
        for (index, _), result in zip(executable, executed_results):
            results_by_index[index] = result
        results = [results_by_index[index] for index in range(len(calls))]
        usage.tool_calls += len(results)
        for result in results:
            self._merge_tool_usage(usage, result)
            self.logger.write(
                "tool_result",
                {"case_id": case_id, "name": result.name, "ok": result.ok, "content": result.content},
            )
        return results, read_calls_used

    def _merge_tool_usage(self, usage: DirectSearchResult, result: ToolResult) -> None:
        try:
            payload = json.loads(result.content)
        except json.JSONDecodeError:
            return
        metrics = payload.get("metrics") or {}
        if not isinstance(metrics, dict):
            return
        model_calls = int(metrics.get("modelCalls") or metrics.get("model_calls") or 0)
        input_tokens = int(metrics.get("inputTokens") or metrics.get("input_tokens") or 0)
        output_tokens = int(metrics.get("outputTokens") or metrics.get("output_tokens") or 0)
        total_tokens = int(metrics.get("totalTokens") or metrics.get("total_tokens") or input_tokens + output_tokens)
        estimated_cost = float(metrics.get("estimatedCost") or metrics.get("estimated_cost") or 0.0)
        usage.model_calls += model_calls
        usage.input_tokens += input_tokens
        usage.output_tokens += output_tokens
        usage.total_tokens += total_tokens
        usage.estimated_cost += estimated_cost
        for model in metrics.get("models") or [metrics.get("model")]:
            if model and model not in usage.models:
                usage.models.append(str(model))

    def _requested_read_count(self, call: ToolCall) -> int:
        if call.name == "code_diver_read":
            return 1
        if call.name != "code_diver_inspect":
            return 0
        reads = call.arguments.get("reads") or []
        return len(reads) if isinstance(reads, list) else 0

    def _read_budget_exceeded_result(self, tool_name: str) -> ToolResult:
        return ToolResult(
            tool_name,
            json.dumps(
                {
                    "tool": tool_name,
                    "ok": False,
                    "error": f"read_budget_exceeded: max {self.MAX_READ_CALLS} code_diver_read calls per case",
                    "metrics": {"maxReadCalls": self.MAX_READ_CALLS},
                }
            ),
            ok=False,
        )

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

    def _fallback_paths(self, tool_results: list[ToolResult]) -> list[str]:
        for result in tool_results:
            paths = self._paths_from_tool_result(result, preferred_tool="code_diver_rerank")
            if paths:
                return paths
        for result in tool_results:
            paths = self._paths_from_tool_result(result)
            if paths:
                return paths
        return []

    def _paths_from_tool_result(self, result: ToolResult, preferred_tool: str | None = None) -> list[str]:
        try:
            payload = json.loads(result.content)
        except json.JSONDecodeError:
            return []
        if preferred_tool and payload.get("tool") != preferred_tool:
            return []
        candidates = ((payload.get("result") or {}).get("candidates") or []) if isinstance(payload, dict) else []
        if not isinstance(candidates, list):
            return []
        paths: list[str] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            path = str(candidate.get("path") or "").strip()
            if path and path not in paths:
                paths.append(path)
        return paths

    def _with_fallback_paths(self, paths: list[str], fallback_paths: list[str], limit: int) -> list[str]:
        merged = list(paths)
        for path in fallback_paths:
            if path not in merged:
                merged.append(path)
            if len(merged) >= limit:
                break
        return merged[:limit]

    def _complete_with_fallback_error(
        self,
        result: DirectSearchResult,
        case_id: str,
        fallback_paths: list[str],
        limit: int,
        error: str,
        fallback_reason: str,
    ) -> DirectSearchResult:
        result.retrieved = fallback_paths[:limit]
        result.error = error
        self.logger.write(
            "search_case_completed",
            {
                "case_id": case_id,
                "retrieved": result.retrieved,
                "usage": result.usage_json(),
                "fallback": fallback_reason,
                "error": error,
            },
        )
        return result

    def _estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)
