"""gRPC Service implementation for Code Diver."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import grpc

from ..config import ConfigLoader
from ..inspection.grep_service import GrepService
from ..inspection.info_service import InfoService
from ..inspection.read_excerpt_service import ReadExcerptService
from ..inspection.symbols_service import SymbolsService
from ..inspection.tree_service import TreeService
from ..runtime.search_runtime import SearchRuntime
from .grpc_gen import code_diver_pb2, code_diver_pb2_grpc


class CodeDiverGrpcServicer(code_diver_pb2_grpc.CodeDiverServiceServicer):
    """gRPC Servicer exposing Code Diver search, info, and inspection endpoints."""

    def __init__(self, config_path: Path | str = "code-diver.yml") -> None:
        self.config_path = Path(config_path).expanduser()
        self._config: Any = None
        self._runtime: SearchRuntime | None = None

    def _get_runtime(self) -> tuple[Any, SearchRuntime]:
        if self._runtime is None:
            resolved = self.config_path if self.config_path.exists() else Path("code-diver.yml")
            self._config = ConfigLoader().load(resolved)
            self._runtime = SearchRuntime(self._config)
        return self._config, self._runtime

    def Search(
        self,
        request: code_diver_pb2.SearchRequest,
        context: grpc.ServicerContext,
    ) -> code_diver_pb2.SearchResponse:
        _, runtime = self._get_runtime()
        limit = request.limit if request.limit > 0 else 10
        results = runtime.base_strategy.search(query=request.query, limit=limit)

        items = []
        for r in results:
            items.append(
                code_diver_pb2.SearchItem(
                    path=r.item.path,
                    score=float(r.score),
                    start_line=r.item.start_line or 0,
                    end_line=r.item.end_line or 0,
                    title=r.item.title or "",
                    content=r.item.content or "",
                )
            )
        return code_diver_pb2.SearchResponse(items=items)

    def Info(
        self,
        request: code_diver_pb2.InfoRequest,
        context: grpc.ServicerContext,
    ) -> code_diver_pb2.InfoResponse:
        config, _ = self._get_runtime()
        info_data = InfoService(config).get_info().to_dict()
        return code_diver_pb2.InfoResponse(json_payload=json.dumps(info_data))

    def ReadExcerpt(
        self,
        request: code_diver_pb2.ReadExcerptRequest,
        context: grpc.ServicerContext,
    ) -> code_diver_pb2.ReadExcerptResponse:
        config, _ = self._get_runtime()
        start = request.start_line if request.start_line > 0 else 1
        lines = request.lines if request.lines > 0 else 100
        content = ReadExcerptService(config.root).render(path=request.file, start_line=start, lines=lines)
        return code_diver_pb2.ReadExcerptResponse(content=content)

    def Grep(
        self,
        request: code_diver_pb2.GrepRequest,
        context: grpc.ServicerContext,
    ) -> code_diver_pb2.GrepResponse:
        config, _ = self._get_runtime()
        limit = request.limit if request.limit > 0 else 50
        matches = GrepService(config.root).search(
            pattern=request.pattern,
            path=request.path if request.path else None,
            limit=limit,
            regex=request.regex,
        )
        return code_diver_pb2.GrepResponse(
            matches=[
                code_diver_pb2.GrepMatch(path=m.path, line=m.line, text=m.text)
                for m in matches
            ]
        )

    def Symbols(
        self,
        request: code_diver_pb2.SymbolsRequest,
        context: grpc.ServicerContext,
    ) -> code_diver_pb2.SymbolsResponse:
        config, _ = self._get_runtime()
        limit = request.limit if request.limit > 0 else 100
        structured = SymbolsService(config.root).structured(
            path=request.path if request.path else None,
            limit=limit,
        )
        return code_diver_pb2.SymbolsResponse(
            symbols=[
                code_diver_pb2.CodeSymbol(
                    name=s["name"],
                    kind=s["kind"],
                    path=s["path"],
                    start_line=s["startLine"],
                    end_line=s["endLine"],
                )
                for s in structured.get("symbols", [])
            ]
        )

    def Tree(
        self,
        request: code_diver_pb2.TreeRequest,
        context: grpc.ServicerContext,
    ) -> code_diver_pb2.TreeResponse:
        config, _ = self._get_runtime()
        depth = request.depth if request.depth > 0 else 3
        limit = request.limit if request.limit > 0 else 100
        rendered = TreeService(config.root).render(
            path=request.path if request.path else None,
            max_depth=depth,
            limit=limit,
        )
        return code_diver_pb2.TreeResponse(tree=rendered)

    def TriggerIndex(
        self,
        request: code_diver_pb2.IndexRequest,
        context: grpc.ServicerContext,
    ) -> Any:
        config, _ = self._get_runtime()
        repo_root = Path(request.repo_path).expanduser() if request.repo_path else config.root
        
        yield code_diver_pb2.IndexProgressUpdate(
            stage="init",
            current=0,
            total=100,
            message=f"Starting remote indexing for {repo_root}",
            done=False,
        )

        try:
            from ..cli import (
                make_codebase_scanner,
                make_embedding_provider,
                make_indexing_service,
                make_plugin_manager,
                make_vector_store,
                close_vector_store,
            )

            vector_store = make_vector_store(config)
            try:
                if request.clear_existing and vector_store.exists():
                    vector_store.clear()
                    yield code_diver_pb2.IndexProgressUpdate(
                        stage="cleanup",
                        current=10,
                        total=100,
                        message="Cleared existing vector collections",
                        done=False,
                    )

                yield code_diver_pb2.IndexProgressUpdate(
                    stage="scanning",
                    current=30,
                    total=100,
                    message="Scanning codebase files and building chunks...",
                    done=False,
                )

                provider = make_embedding_provider(config, vector_store.metadata())
                indexing_service = make_indexing_service(config, progress=False)
                items = indexing_service.build(repo_root, provider, config.plugins)

                yield code_diver_pb2.IndexProgressUpdate(
                    stage="completed",
                    current=100,
                    total=100,
                    message=f"Successfully indexed {len(items)} items",
                    done=True,
                )
            finally:
                close_vector_store(vector_store)
        except Exception as exc:
            yield code_diver_pb2.IndexProgressUpdate(
                stage="error",
                current=0,
                total=100,
                message=str(exc),
                done=True,
                error=str(exc),
            )

    def IngestFiles(
        self,
        request_iterator: Any,
        context: grpc.ServicerContext,
    ) -> code_diver_pb2.IngestSummary:
        config, _ = self._get_runtime()
        files_count = 0
        total_bytes = 0

        # Receive streamed files into workspace
        ingest_dir = config.root / ".code_diver_remote_ingest"
        ingest_dir.mkdir(parents=True, exist_ok=True)

        for chunk in request_iterator:
            target_path = ingest_dir / chunk.path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with open(target_path, "ab" if target_path.exists() else "wb") as f:
                f.write(chunk.content)
            total_bytes += len(chunk.content)
            if chunk.is_last_chunk:
                files_count += 1

        return code_diver_pb2.IngestSummary(
            files_received=files_count,
            total_bytes=total_bytes,
            status="ok",
            message=f"Received {files_count} files ({total_bytes} bytes) into {ingest_dir}",
        )
