from __future__ import annotations

from pathlib import Path

from ..config import AppConfig
from ..domain import CodeItem
from ..generation import GenerationProvider
from ..services import CodebaseScanner
from ..tracing import TraceLogger
from .index_plan_orchestrator import IndexPlanOrchestrator


class OrchestratedCodebaseScanner:
    def __init__(
        self,
        base_scanner: CodebaseScanner,
        generation_provider: GenerationProvider,
        config: AppConfig,
        trace_logger: TraceLogger | None = None,
    ):
        self.base_scanner = base_scanner
        self.generation_provider = generation_provider
        self.config = config
        self.trace_logger = trace_logger or TraceLogger.disabled()

    def scan(self, root: Path) -> list[CodeItem]:
        plan = IndexPlanOrchestrator(self.generation_provider, self.trace_logger).plan(
            root, self.config, self.base_scanner
        )
        include = plan.include or self.config.scanner.include
        exclude = [*self.config.scanner.exclude, *plan.exclude]
        chunk_lines = plan.chunk_lines or self.config.scanner.chunk_lines
        self.trace_logger.write(
            "index_scanner_config_selected",
            {
                "include": include,
                "exclude": exclude,
                "max_file_bytes": self.config.scanner.max_file_bytes,
                "chunk_lines": chunk_lines,
            },
        )
        scanner = CodebaseScanner(
            include=include,
            exclude=exclude,
            max_file_bytes=self.config.scanner.max_file_bytes,
            chunk_lines=chunk_lines,
        )
        return scanner.scan(root)
