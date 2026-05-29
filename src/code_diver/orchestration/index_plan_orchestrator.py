from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..config import AppConfig
from ..generation import GenerationProvider
from ..services import CodebaseScanner
from ..tracing import TraceLogger
from .json_response import JsonResponse
from .repository_inventory import RepositoryInventory


@dataclass(slots=True)
class IndexPlan:
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    chunk_lines: int | None = None


class IndexPlanOrchestrator:
    def __init__(self, generation_provider: GenerationProvider, trace_logger: TraceLogger | None = None):
        self.generation_provider = generation_provider
        self.trace_logger = trace_logger or TraceLogger.disabled()

    def plan(self, root: Path, config: AppConfig, scanner: CodebaseScanner) -> IndexPlan:
        prompt = self._prompt(root, config, scanner)
        self.trace_logger.write(
            "index_plan_prompt",
            {
                "root": root,
                "provider": self.generation_provider.name,
                "model": self.generation_provider.model,
                "mode": config.indexing.mode,
                **self.trace_logger.prompt_payload(prompt),
            },
        )
        try:
            response = self.generation_provider.generate_json(prompt)
            self.trace_logger.write(
                "index_plan_response",
                {
                    "provider": self.generation_provider.name,
                    "model": self.generation_provider.model,
                    "response_chars": len(response),
                    "response": response,
                },
            )
            payload = JsonResponse().parse_object(response)
        except Exception as exc:
            self.trace_logger.write(
                "index_plan_error",
                {
                    "provider": self.generation_provider.name,
                    "model": self.generation_provider.model,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            return IndexPlan()
        plan = IndexPlan(
            include=self._strings(payload.get("include")),
            exclude=self._strings(payload.get("exclude")),
            chunk_lines=self._optional_int(payload.get("chunk_lines")),
        )
        self.trace_logger.write(
            "index_plan_selected",
            {
                "include": plan.include,
                "exclude": plan.exclude,
                "chunk_lines": plan.chunk_lines,
            },
        )
        return plan

    def _prompt(self, root: Path, config: AppConfig, scanner: CodebaseScanner) -> str:
        inventory = RepositoryInventory(
            scanner,
            config.indexing.ai.tree_depth,
            config.indexing.ai.tree_limit,
        ).render(root)
        return f"""
You orchestrate codebase indexing. You do not read source code contents.
Use only repository structure, file names, extensions, and aggregate inventory below.
Return JSON only:
{{
  "include": ["glob patterns to index, empty means keep current config"],
  "exclude": ["glob patterns to exclude in addition to current config"],
  "chunk_lines": 120
}}
Goals:
- Preserve broad coverage for an arbitrary repository and language stack.
- Exclude caches, generated output, vendored dependencies, binary assets, and logs.
- Keep enough source, docs, tests, config, and manifests for retrieval.

Current include: {config.scanner.include}
Current exclude: {config.scanner.exclude}
Current chunk_lines: {config.scanner.chunk_lines}

{inventory}
""".strip()

    def _strings(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item).strip()]

    def _optional_int(self, value: object) -> int | None:
        if value is None or value == "":
            return None
        return int(value)
