from __future__ import annotations

import logging
import math
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from ..domain import CodeItem
from ..plugins import PluginManager
from ..providers import EmbeddingProvider
from ..store import VectorStore
from ..tracing import TraceLogger
from .code_item_scanner import CodeItemScanner
from .embedding_text_preparer import EmbeddingTextPreparer
from .index_composition_analyzer import IndexCompositionAnalyzer
from .indexing_options import IndexingOptions
from .parallel_embedding_service import ParallelEmbeddingService

logger = logging.getLogger(__name__)


class IndexingService:
    def __init__(
        self,
        scanner: CodeItemScanner,
        plugin_manager: PluginManager,
        vector_store: VectorStore,
        options: IndexingOptions | None = None,
        trace_logger: TraceLogger | None = None,
    ):
        self.scanner = scanner
        self.plugin_manager = plugin_manager
        self.vector_store = vector_store
        self.options = options or IndexingOptions()
        self.trace_logger = trace_logger or TraceLogger.disabled()
        self._progress: Progress | None = None
        self._scan_task: Any = None
        self._embedding_task: Any = None
        self._save_task: Any = None

    def build(
        self,
        root: Path,
        provider: EmbeddingProvider,
        plugin_config: dict | None = None,
    ) -> list[CodeItem]:
        if self.options.progress:
            with self._new_progress() as progress:
                self._progress = progress
                try:
                    return self._build(root, provider, plugin_config)
                finally:
                    self._progress = None
                    self._scan_task = None
                    self._embedding_task = None
                    self._save_task = None
        return self._build(root, provider, plugin_config)

    def _build(
        self,
        root: Path,
        provider: EmbeddingProvider,
        plugin_config: dict | None = None,
    ) -> list[CodeItem]:
        self._start_scan_progress(root)
        restore_scan_progress = self._attach_scan_progress()
        scanned_items = self.scanner.scan(root)
        restore_scan_progress()
        self._finish_scan_progress(len(scanned_items))
        plugin_items = self.plugin_manager.collect_items(root, plugin_config or {})
        items = self.plugin_manager.transform_items(
            self._dedupe_items([*scanned_items, *plugin_items])
        )
        composition = IndexCompositionAnalyzer().analyze(items)
        self._progress_message(
            "prepared retrieval records: "
            f"items={len(items)} files={composition['unique_paths']} "
            f"scanner={len(scanned_items)} plugin={len(plugin_items)} "
            f"kinds={self._format_counts(composition['items_by_kind'])}"
        )
        self.trace_logger.write(
            "index_items_prepared",
            {
                "root": root,
                "scanner_items": len(scanned_items),
                "plugin_items": len(plugin_items),
                **composition,
                "embedding_batch_size": self.options.embedding_batch_size,
                "embedding_workers": self.options.embedding_workers,
                "embedding_max_input_chars": self.options.embedding_max_input_chars,
                "embedding_max_input_tokens": self.options.embedding_max_input_tokens,
                "embedding_token_safety_margin": self.options.embedding_token_safety_margin,
            },
        )
        preparer = EmbeddingTextPreparer(
            self.options.embedding_max_input_chars,
            max_input_tokens=self.options.embedding_max_input_tokens,
            token_safety_margin=self.options.embedding_token_safety_margin,
        )
        self._progress_message(
            "embedding retrieval texts: "
            f"items={len(items)} provider={provider.name} model={provider.model} "
            f"batch_size={self.options.embedding_batch_size} workers={self.options.embedding_workers} "
            f"max_chars={self.options.embedding_max_input_chars or 'provider-default'}"
        )
        dimensions = self._embed_and_save(root, provider, items, preparer)
        self.trace_logger.write(
            "index_vectors_saved",
            {
                "root": root,
                "provider": provider.name,
                "model": provider.model,
                "dimensions": dimensions,
                "vectors": len(items),
            },
        )
        return items

    def _new_progress(self) -> Progress:
        return Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=Console(stderr=True),
            transient=False,
        )

    def _embed_and_save(
        self,
        root: Path,
        provider: EmbeddingProvider,
        items: list[CodeItem],
        preparer: EmbeddingTextPreparer,
    ) -> int:
        replace_batches = getattr(self.vector_store, "replace_batches", None)
        if callable(replace_batches):
            return self._embed_and_replace_batches(
                root, provider, items, preparer, replace_batches
            )
        return self._embed_and_save_once(root, provider, items, preparer)

    def _embed_and_save_once(
        self,
        root: Path,
        provider: EmbeddingProvider,
        items: list[CodeItem],
        preparer: EmbeddingTextPreparer,
    ) -> int:
        texts = [preparer.prepare(item) for item in items]
        total_batches = self._embedding_batch_count(len(texts))
        self._start_embedding_progress(total_batches, len(texts))
        vectors = ParallelEmbeddingService(
            provider,
            batch_size=self.options.embedding_batch_size,
            workers=self.options.embedding_workers,
            on_batch_complete=self._progress_callback(len(texts)),
        ).embed_documents(texts)
        dimensions = provider.dimensions or (len(vectors[0]) if vectors else 0)
        if not provider.dimensions and dimensions:
            provider.dimensions = dimensions
        self._start_save_progress()
        self.vector_store.save(
            root=root,
            provider=provider.name,
            model=provider.model,
            dimensions=dimensions,
            items=items,
            vectors=vectors,
        )
        self._finish_save_progress()
        return dimensions

    def _embed_and_replace_batches(
        self,
        root: Path,
        provider: EmbeddingProvider,
        items: list[CodeItem],
        preparer: EmbeddingTextPreparer,
        replace_batches,
    ) -> int:
        block_size = max(
            self.options.embedding_batch_size * self.options.embedding_workers * 8, 1
        )
        total_batches = self._embedding_batch_count(len(items))
        self._start_embedding_progress(total_batches, len(items))
        progress = self._streaming_progress_callback(len(items), total_batches)
        dimensions = provider.dimensions or 0

        def vector_batches() -> Iterable[tuple[list[CodeItem], list[list[float]]]]:
            nonlocal dimensions
            for item_batch in self._item_batches(items, block_size):
                texts = [preparer.prepare(item) for item in item_batch]
                vectors = ParallelEmbeddingService(
                    provider,
                    batch_size=self.options.embedding_batch_size,
                    workers=self.options.embedding_workers,
                    on_batch_complete=progress,
                ).embed_documents(texts)
                if not dimensions and vectors:
                    dimensions = len(vectors[0])
                    provider.dimensions = dimensions
                yield item_batch, vectors

        self._start_save_progress()
        try:
            replace_batches(
                root=root,
                provider=provider.name,
                model=provider.model,
                dimensions=lambda: dimensions,
                batches=vector_batches(),
            )
        finally:
            self._finish_save_progress()
        return dimensions

    def _embedding_batch_count(self, total_items: int) -> int:
        return max(
            math.ceil(total_items / max(self.options.embedding_batch_size, 1)), 1
        )

    def _start_embedding_progress(self, total_batches: int, total_items: int) -> None:
        if not self.options.progress:
            return
        if self._progress is not None:
            if self._embedding_task is None:
                self._embedding_task = self._progress.add_task(
                    "embedded batches", total=total_batches
                )
            self._progress.update(
                self._embedding_task, completed=0, total=total_batches
            )
            return
        print(
            f"embedded batches: 0/{total_batches} (0%, items={total_items})",
            file=sys.stderr,
        )

    def _progress_callback(self, total_items: int):
        if not self.options.progress:
            return None
        last_reported = -1

        def callback(completed_batches: int, total_batches: int) -> None:
            nonlocal last_reported
            if total_batches <= 0:
                return
            if self._progress is not None:
                if self._embedding_task is None:
                    self._embedding_task = self._progress.add_task(
                        "embedded batches", total=total_batches
                    )
                self._progress.update(self._embedding_task, completed=completed_batches)
                return
            percent = int((completed_batches / total_batches) * 100)
            should_report = (
                completed_batches == total_batches or percent >= last_reported + 5
            )
            if not should_report:
                return
            last_reported = percent
            print(
                f"embedded batches: {completed_batches}/{total_batches} "
                f"({percent}%, items={total_items})",
                file=sys.stderr,
            )

        return callback

    def _streaming_progress_callback(self, total_items: int, total_batches: int):
        if not self.options.progress:
            return None
        completed = 0
        last_reported = -1

        def callback(_: int, __: int) -> None:
            nonlocal completed, last_reported
            completed += 1
            if self._progress is not None:
                if self._embedding_task is None:
                    self._embedding_task = self._progress.add_task(
                        "embedded batches", total=total_batches
                    )
                self._progress.update(self._embedding_task, completed=completed)
                return
            percent = int((completed / total_batches) * 100)
            should_report = completed == total_batches or percent >= last_reported + 5
            if not should_report:
                return
            last_reported = percent
            print(
                f"embedded batches: {completed}/{total_batches} "
                f"({percent}%, items={total_items})",
                file=sys.stderr,
            )

        return callback

    def _start_scan_progress(self, root: Path) -> None:
        if self._progress is None:
            return
        discovery_task = self._progress.add_task("discovering files", total=None)
        total = self._candidate_file_count(root)
        self._progress.update(
            discovery_task, completed=1, total=1, description="discovered files"
        )
        self._scan_task = self._progress.add_task(
            "scanning files", total=total if total > 0 else None
        )

    def _attach_scan_progress(self):
        if self._progress is None or self._scan_task is None:
            return lambda: None
        if not hasattr(self.scanner, "progress_callback"):
            return lambda: None
        previous = self.scanner.progress_callback

        def callback(processed_files: int, items_found: int) -> None:
            if self._progress is None or self._scan_task is None:
                return
            self._progress.update(
                self._scan_task,
                completed=processed_files,
                description=f"scanning files ({items_found} items)",
            )

        self.scanner.progress_callback = callback

        def restore() -> None:
            self.scanner.progress_callback = previous

        return restore

    def _finish_scan_progress(self, item_count: int) -> None:
        if self._progress is None or self._scan_task is None:
            return
        task = self._progress.tasks[self._scan_task]
        completed = task.total if task.total is not None else task.completed
        self._progress.update(
            self._scan_task,
            completed=completed,
            description=f"scanned files ({item_count} items)",
        )

    def _candidate_file_count(self, root: Path) -> int:
        counter = getattr(self.scanner, "count_candidate_files", None)
        if not callable(counter):
            return 0
        try:
            return int(counter(root))
        except Exception:
            logger.debug(
                "failed to count candidate files for indexing progress", exc_info=True
            )
            return 0

    def _start_save_progress(self) -> None:
        if self._progress is None:
            return
        self._save_task = self._progress.add_task(
            "streaming vectors to store", total=None
        )

    def _finish_save_progress(self) -> None:
        if self._progress is None or self._save_task is None:
            return
        self._progress.update(
            self._save_task, completed=1, total=1, description="saved index"
        )

    def _progress_message(self, message: str) -> None:
        if self._progress is not None:
            self._progress.console.print(f"[dim]\\[code-diver] {message}[/dim]")
            return
        if self.options.progress:
            print(f"[code-diver] {message}", file=sys.stderr)

    def _format_counts(self, counts: dict[str, int]) -> str:
        if not counts:
            return "none"
        return ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))

    def _item_batches(self, items: list[CodeItem], size: int):
        for offset in range(0, len(items), size):
            yield items[offset : offset + size]

    def _dedupe_items(self, items: list[CodeItem]) -> list[CodeItem]:
        seen: set[str] = set()
        deduped: list[CodeItem] = []
        for item in items:
            if item.id in seen:
                continue
            seen.add(item.id)
            deduped.append(item)
        return deduped
