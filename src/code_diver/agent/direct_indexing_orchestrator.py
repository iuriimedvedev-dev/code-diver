from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from time import perf_counter
from typing import Any

from ..generation import GenerationProvider, GenerationResult
from ..providers import EmbeddingProvider
from ..services import (
    IndexingOptions,
    SelectedCodeItemBuilder,
    SelectedIndexingService,
    SelectedIndexPayloadParser,
)
from ..store import VectorStore
from .direct_agent_logger import DirectAgentLogger
from .direct_indexing_prompt_builder import DirectIndexingPromptBuilder
from .direct_indexing_result import DirectIndexingResult
from .direct_tool_executor import DirectToolExecutor
from .json_response_parser import JsonResponseParser
from .model_cost_estimator import ModelCostEstimator
from .parallel_tool_executor import ParallelToolExecutor
from .tool_call import ToolCall
from .tool_observation_compressor import ToolObservationCompressor
from .tool_result import ToolResult


class DirectIndexingOrchestrator:
    MAX_ROUNDS = 8
    MAX_ITEMS = 40
    MAX_PARALLEL_TOOLS = 8
    MAX_INSPECT_READS = 10

    def __init__(
        self,
        *,
        root: Path,
        generation_provider: GenerationProvider,
        embedding_provider: EmbeddingProvider,
        vector_store: VectorStore,
        allowed_tools: list[str],
        max_lines: int,
        indexing_options: IndexingOptions,
        log_path: Path,
        include_prompts: bool = True,
        exclude: list[str] | None = None,
        max_file_bytes: int = 1_000_000,
        graph_indexer: Callable[[list[Any]], None] | None = None,
    ):
        self.root = root
        self.generation_provider = generation_provider
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store
        self.allowed_tools = allowed_tools
        self.max_lines = max_lines
        self.indexing_options = indexing_options
        self.exclude = exclude or []
        self.max_file_bytes = max_file_bytes
        self.graph_indexer = graph_indexer
        self.logger = DirectAgentLogger(log_path, include_prompts=include_prompts)
        self.prompt_builder = DirectIndexingPromptBuilder()
        self.response_parser = JsonResponseParser()
        self.observation_compressor = ToolObservationCompressor()
        self.cost_estimator = ModelCostEstimator()

    def run(self, hypothesis_name: str, cases: list[Any]) -> DirectIndexingResult:
        discovery_tools = [tool for tool in self.allowed_tools if tool != "code_diver_index_selected"]
        executor = DirectToolExecutor(
            self.root,
            discovery_tools,
            exclude=self.exclude,
            max_file_bytes=self.max_file_bytes,
            max_inspect_reads=self.MAX_INSPECT_READS,
        )
        history: list[dict[str, Any]] = []
        usage = DirectIndexingResult(exit_code=0)
        self.logger.write(
            "run_started",
            {
                "hypothesis": hypothesis_name,
                "root": str(self.root),
                "allowed_tools": self.allowed_tools,
                "discovery_tools": discovery_tools,
                "max_rounds": self.MAX_ROUNDS,
                "max_items": self.MAX_ITEMS,
            },
        )

        try:
            for round_index in range(1, self.MAX_ROUNDS + 1):
                prompt = self.prompt_builder.build(
                    hypothesis_name=hypothesis_name,
                    queries=[case.query for case in cases],
                    tool_manifest=executor.manifest(),
                    history=history,
                    max_items=self.MAX_ITEMS,
                )
                response = self._generate(prompt, usage)
                self._log_model_turn(round_index, prompt, response)
                parsed = self.response_parser.parse(response.text)
                history.append({"round": round_index, "assistant": parsed})

                index_values = parsed.get("index_items") or parsed.get("items")
                if index_values:
                    if not self._has_tool_evidence(history):
                        history.append(
                            {
                                "round": round_index,
                                "runtime_feedback": {
                                    "reason": "indexing_evidence_required",
                                    "instruction": (
                                        "Use read-only discovery tools before selecting index_items. "
                                        "Gather tree/symbol/rg/grep/read evidence, then persist grounded ranges."
                                    ),
                                },
                            }
                        )
                        self.logger.write(
                            "indexing_evidence_required",
                            {"round": round_index, "requested_items": len(index_values) if isinstance(index_values, list) else 0},
                        )
                        continue
                    return self._persist_index(index_values, usage)

                tool_calls = self._parse_tool_calls(parsed)
                if not tool_calls:
                    return self._failed(usage, "agent_returned_no_tool_calls_or_index_items")
                tool_results = self._execute_tools(executor, tool_calls, usage)
                history.append(
                    {
                        "round": round_index,
                        "tool_results": [
                            {
                                "name": result.name,
                                "ok": result.ok,
                                "content": self.observation_compressor.compress(result.content),
                            }
                            for result in tool_results
                        ],
                    }
                )
            return self._failed(usage, "max_rounds_exceeded")
        except Exception as exc:
            self.logger.write("run_failed", {"error": str(exc)})
            return self._failed(usage, str(exc))

    def _generate(self, prompt: str, usage: DirectIndexingResult) -> GenerationResult:
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

    def _log_model_turn(self, round_index: int, prompt: str, response: GenerationResult) -> None:
        payload: dict[str, Any] = {
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
            if not name:
                continue
            if not isinstance(arguments, dict):
                raise ValueError(f"arguments for {name} must be an object.")
            calls.append(ToolCall(name=name, arguments=arguments))
        return calls

    def _execute_tools(
        self,
        executor: DirectToolExecutor,
        calls: list[ToolCall],
        usage: DirectIndexingResult,
    ) -> list[ToolResult]:
        for call in calls:
            self.logger.write("tool_call", {"name": call.name, "arguments": call.arguments})
        results = ParallelToolExecutor(self.MAX_PARALLEL_TOOLS).execute(calls, executor.execute)
        usage.tool_calls += len(results)
        for result in results:
            self.logger.write(
                "tool_result",
                {"name": result.name, "ok": result.ok, "content": result.content},
            )
        return results

    def _has_tool_evidence(self, history: list[dict[str, Any]]) -> bool:
        for entry in history:
            results = entry.get("tool_results")
            if isinstance(results, list) and any(isinstance(item, dict) and item.get("ok") for item in results):
                return True
        return False

    def _persist_index(self, values: Any, usage: DirectIndexingResult) -> DirectIndexingResult:
        if not isinstance(values, list):
            raise ValueError("index_items must be a list.")
        selected = SelectedIndexPayloadParser().parse(json.dumps({"items": values[: self.MAX_ITEMS]}))
        built = SelectedCodeItemBuilder(self.root, self.max_lines, self.exclude).build(selected)
        self.logger.write(
            "index_items_built",
            {
                "requested_items": len(selected),
                "prepared_items": len(built.items),
                "skipped": built.skipped,
            },
        )
        if not built.items:
            return self._failed(usage, "no_valid_index_items_selected")
        service = SelectedIndexingService(self.vector_store, self.indexing_options)
        items = service.build(self.root, self.embedding_provider, built.items)
        if self.graph_indexer:
            self.graph_indexer(items)
        usage.indexed_items = len(items)
        self.logger.write(
            "index_saved",
            {
                "indexed_items": len(items),
                "paths": sorted({item.path for item in items}),
                "provider": self.embedding_provider.name,
                "model": self.embedding_provider.model,
            },
        )
        return usage

    def _failed(self, usage: DirectIndexingResult, error: str) -> DirectIndexingResult:
        usage.exit_code = 1
        usage.error = error
        self.logger.write("run_failed", {"error": error, "usage": usage.to_usage_json()})
        return usage

    def _estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)
