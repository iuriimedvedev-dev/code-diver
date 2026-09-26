"""Knotgate MCPService gRPC servicer implementation for Code Diver."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any

import grpc

from ..config import ConfigLoader
from ..inspection.grep_service import GrepService
from ..inspection.info_service import InfoService
from ..inspection.read_excerpt_service import ReadExcerptService
from ..inspection.symbols_service import SymbolsService
from ..inspection.tree_service import TreeService
from ..runtime.search_runtime import SearchRuntime
from .grpc_gen import common_pb2, mcp_service_pb2, mcp_service_pb2_grpc


class KnotgateMcpServiceServicer(mcp_service_pb2_grpc.MCPServiceServicer):
    """Implementation of mcp.service.v1.MCPService for knotgate integration."""

    def __init__(self, config_path: Path | str = "code-diver.yml") -> None:
        self.config_path = Path(config_path).expanduser()
        self._config: Any = None
        self._runtime: SearchRuntime | None = None
        self._start_time = time.time()
        self._total_calls = 0
        self._successful_calls = 0
        self._failed_calls = 0

    def _get_runtime(self) -> tuple[Any, SearchRuntime]:
        if self._runtime is None:
            resolved = self.config_path if self.config_path.exists() else Path("code-diver.yml")
            self._config = ConfigLoader().load(resolved)
            self._runtime = SearchRuntime(self._config)
        return self._config, self._runtime

    def ListTools(
        self,
        request: mcp_service_pb2.ListToolsRequest,
        context: grpc.ServicerContext,
    ) -> mcp_service_pb2.ListToolsResponse:
        tools = [
            common_pb2.Tool(
                name="code_diver_search",
                description="Search repository code using neural and hybrid retrieval.",
                title="Search Code",
                input_schema=common_pb2.ToolInputSchema(
                    type="object",
                    properties={
                        "query": common_pb2.SchemaProperty(type="string", description="Natural language search query"),
                        "limit": common_pb2.SchemaProperty(type="integer", description="Max items to return (default: 10)"),
                    },
                    required=["query"],
                ),
            ),
            common_pb2.Tool(
                name="code_diver_grep",
                description="Search literal text or regex patterns across the codebase.",
                title="Grep Codebase",
                input_schema=common_pb2.ToolInputSchema(
                    type="object",
                    properties={
                        "pattern": common_pb2.SchemaProperty(type="string", description="Search pattern"),
                        "path": common_pb2.SchemaProperty(type="string", description="Subdirectory or file path"),
                        "limit": common_pb2.SchemaProperty(type="integer", description="Max matches (default: 50)"),
                        "regex": common_pb2.SchemaProperty(type="boolean", description="Whether pattern is a regex"),
                    },
                    required=["pattern"],
                ),
            ),
            common_pb2.Tool(
                name="code_diver_read",
                description="Read a bounded excerpt of lines from a project file.",
                title="Read File Excerpt",
                input_schema=common_pb2.ToolInputSchema(
                    type="object",
                    properties={
                        "file": common_pb2.SchemaProperty(type="string", description="Relative file path"),
                        "start_line": common_pb2.SchemaProperty(type="integer", description="Line to start reading from"),
                        "lines": common_pb2.SchemaProperty(type="integer", description="Number of lines to read"),
                    },
                    required=["file"],
                ),
            ),
            common_pb2.Tool(
                name="code_diver_symbols",
                description="List AST parsed source symbols (classes, methods, functions) for a file or repo.",
                title="Extract Symbols",
                input_schema=common_pb2.ToolInputSchema(
                    type="object",
                    properties={
                        "path": common_pb2.SchemaProperty(type="string", description="Optional file or directory path"),
                        "limit": common_pb2.SchemaProperty(type="integer", description="Max symbols (default: 100)"),
                    },
                ),
            ),
            common_pb2.Tool(
                name="code_diver_tree",
                description="Print a gitignore-aware directory tree of the repository.",
                title="Directory Tree",
                input_schema=common_pb2.ToolInputSchema(
                    type="object",
                    properties={
                        "path": common_pb2.SchemaProperty(type="string", description="Root subdirectory to tree"),
                        "depth": common_pb2.SchemaProperty(type="integer", description="Max traversal depth"),
                        "limit": common_pb2.SchemaProperty(type="integer", description="Max lines in tree"),
                    },
                ),
            ),
            common_pb2.Tool(
                name="code_diver_info",
                description="Get Code Diver index, vector store, graph, and model footprint statistics.",
                title="Codebase Info",
                input_schema=common_pb2.ToolInputSchema(
                    type="object",
                    properties={},
                ),
            ),
        ]

        if request.filter_names:
            patterns = set(request.filter_names)
            tools = [t for t in tools if t.name in patterns]

        return mcp_service_pb2.ListToolsResponse(
            response=common_pb2.Response(success=True, message=f"Loaded {len(tools)} tools"),
            tools=tools,
        )

    def CallTool(
        self,
        request: mcp_service_pb2.CallToolRequest,
        context: grpc.ServicerContext,
    ) -> mcp_service_pb2.CallToolResponse:
        start_t = time.time()
        self._total_calls += 1
        config, runtime = self._get_runtime()
        tool_name = request.tool_name
        args = dict(request.arguments)

        try:
            if tool_name == "code_diver_search":
                query = args.get("query", "")
                limit = int(args.get("limit", 10))
                results = runtime.base_strategy.search(query=query, limit=limit)
                out = [
                    {
                        "path": r.item.path,
                        "score": round(float(r.score), 4),
                        "start_line": r.item.start_line,
                        "end_line": r.item.end_line,
                        "title": r.item.title,
                        "content_preview": (
                            r.item.content[:300] + "..." if len(r.item.content) > 300 else r.item.content
                        ),
                    }
                    for r in results
                ]
                text_content = json.dumps(out, indent=2)

            elif tool_name == "code_diver_grep":
                pattern = args.get("pattern", "")
                path = args.get("path") or None
                limit = int(args.get("limit", 50))
                regex = args.get("regex", "false").lower() == "true"
                matches = GrepService(config.root).search(pattern=pattern, path=path, limit=limit, regex=regex)
                out = [{"path": m.path, "line": m.line, "text": m.text} for m in matches]
                text_content = json.dumps(out, indent=2)

            elif tool_name == "code_diver_read":
                file_p = args.get("file", "")
                start_l = int(args.get("start_line", 1))
                lines = int(args.get("lines", 100))
                text_content = ReadExcerptService(config.root).render(path=file_p, start_line=start_l, lines=lines)

            elif tool_name == "code_diver_symbols":
                path = args.get("path") or None
                limit = int(args.get("limit", 100))
                structured = SymbolsService(config.root).structured(path=path, limit=limit)
                text_content = json.dumps(structured.get("symbols", []), indent=2)

            elif tool_name == "code_diver_tree":
                path = args.get("path") or None
                depth = int(args.get("depth", 3))
                limit = int(args.get("limit", 100))
                text_content = TreeService(config.root).render(path=path, max_depth=depth, limit=limit)

            elif tool_name == "code_diver_info":
                text_content = json.dumps(InfoService(config).get_info().to_dict(), indent=2)

            else:
                self._failed_calls += 1
                return mcp_service_pb2.CallToolResponse(
                    response=common_pb2.Response(success=False, error=f"Unknown tool: {tool_name}"),
                    result=common_pb2.ToolResult(
                        content=[common_pb2.ToolContent(type="text", text=f"Unknown tool: {tool_name}")],
                        is_error=True,
                    ),
                    execution_time_ms=int((time.time() - start_t) * 1000),
                )

            self._successful_calls += 1
            exec_time = int((time.time() - start_t) * 1000)
            return mcp_service_pb2.CallToolResponse(
                response=common_pb2.Response(success=True),
                result=common_pb2.ToolResult(
                    content=[common_pb2.ToolContent(type="text", text=text_content)],
                    is_error=False,
                ),
                execution_time_ms=exec_time,
            )

        except Exception as exc:
            self._failed_calls += 1
            exec_time = int((time.time() - start_t) * 1000)
            return mcp_service_pb2.CallToolResponse(
                response=common_pb2.Response(success=False, error=str(exc)),
                result=common_pb2.ToolResult(
                    content=[common_pb2.ToolContent(type="text", text=f"Error executing {tool_name}: {exc}")],
                    is_error=True,
                ),
                execution_time_ms=exec_time,
            )

    def GetHealth(
        self,
        request: mcp_service_pb2.GetHealthRequest,
        context: grpc.ServicerContext,
    ) -> mcp_service_pb2.GetHealthResponse:
        uptime = int(time.time() - self._start_time)
        metrics = None
        if request.include_metrics:
            metrics = mcp_service_pb2.ServiceMetrics(
                total_calls=self._total_calls,
                successful_calls=self._successful_calls,
                failed_calls=self._failed_calls,
                uptime_seconds=uptime,
                active_sessions=1,
            )

        return mcp_service_pb2.GetHealthResponse(
            response=common_pb2.Response(success=True),
            health=common_pb2.HealthInfo(
                status="healthy",
                server="code-diver",
                version="0.4.2",
            ),
            metrics=metrics,
        )

    def GetCapabilities(
        self,
        request: mcp_service_pb2.GetCapabilitiesRequest,
        context: grpc.ServicerContext,
    ) -> mcp_service_pb2.GetCapabilitiesResponse:
        return mcp_service_pb2.GetCapabilitiesResponse(
            response=common_pb2.Response(success=True),
            capabilities=mcp_service_pb2.ServiceCapabilities(
                service_name="code-diver",
                service_version="0.4.2",
                supported_features=["search", "grep", "read", "symbols", "tree", "info", "indexing"],
                supports_streaming=True,
                supports_sessions=True,
                requires_authentication=False,
                max_concurrent_calls=16,
                default_timeout_ms=30000,
            ),
        )
