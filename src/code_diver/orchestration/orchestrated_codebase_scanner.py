from __future__ import annotations

from pathlib import Path

from ..config import AppConfig
from ..domain import CodeItem
from ..generation import GenerationProvider
from ..services import CodebaseScanner
from ..tracing import TraceLogger
from .index_plan_orchestrator import IndexPlanOrchestrator
from .index_plan_sanitizer import IndexPlanSanitizer


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
        sanitizer = IndexPlanSanitizer()
        safe_additions, rejected_additions = sanitizer.safe_include_additions(
            root,
            plan.include,
            self.base_scanner.exclude,
            max_added_files=max(self.config.indexing.ai.max_files, 200),
        )
        safe_excludes, rejected_excludes = sanitizer.safe_exclude_additions(
            root,
            plan.exclude,
            self.config.scanner.exclude,
            max_excluded_files=max(self.config.indexing.ai.max_files, 200),
        )
        include = self._merge_patterns(self.config.scanner.include, safe_additions)
        exclude = [*self.config.scanner.exclude, *safe_excludes]
        chunk_lines = plan.chunk_lines or self.config.scanner.chunk_lines
        symbol_chunks = plan.symbol_chunks if plan.symbol_chunks is not None else self.config.scanner.symbol_chunks
        if rejected_additions:
            self.trace_logger.write("index_plan_rejected_include", {"include": rejected_additions})
        if rejected_excludes:
            self.trace_logger.write("index_plan_rejected_exclude", {"exclude": rejected_excludes})
        self.trace_logger.write(
            "index_scanner_config_selected",
            {
                "include": include,
                "exclude": exclude,
                "max_file_bytes": self.config.scanner.max_file_bytes,
                "chunk_lines": chunk_lines,
                "structural_chunks": self.config.scanner.structural_chunks,
                "symbol_chunks": symbol_chunks,
            },
        )
        scanner = CodebaseScanner(
            include=include,
            exclude=exclude,
            max_file_bytes=self.config.scanner.max_file_bytes,
            chunk_lines=chunk_lines,
            structural_chunks=self.config.scanner.structural_chunks,
            symbol_chunks=symbol_chunks,
            file_summary_chunks=self.config.scanner.file_summary_chunks,
        )
        return scanner.scan(root)

    def _merge_patterns(self, base: list[str], additions: list[str]) -> list[str]:
        merged: list[str] = []
        for pattern in [*base, *additions]:
            if pattern not in merged:
                merged.append(pattern)
        return merged
