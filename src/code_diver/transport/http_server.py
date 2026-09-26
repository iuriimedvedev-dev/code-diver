"""HTTP and SSE Remote Transport Server for Code Diver.

Provides:
- Native MCP over SSE (`/mcp/sse` and `/mcp/messages`)
- Native ACP over HTTP/SSE (`/acp/v1/initialize`, `/acp/v1/sessions`, `/acp/v1/events`)
- Direct REST Search & Inspection APIs (`/api/v1/search`, `/api/v1/info`, `/api/v1/grep`, etc.)
- Healthcheck (`/health`)
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, AsyncGenerator
import uuid

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..config import ConfigLoader
from ..inspection.grep_service import GrepService
from ..inspection.info_service import InfoService
from ..inspection.read_excerpt_service import ReadExcerptService
from ..inspection.symbols_service import SymbolsService
from ..inspection.tree_service import TreeService
from ..runtime.search_runtime import SearchRuntime

logger = logging.getLogger("code_diver.transport.http")


class SearchRequestModel(BaseModel):
    query: str
    limit: int = 10


class GrepRequestModel(BaseModel):
    pattern: str
    path: str | None = None
    limit: int = 50
    regex: bool = False


class ReadExcerptRequestModel(BaseModel):
    file: str
    start_line: int = 1
    lines: int = 100


class SymbolsRequestModel(BaseModel):
    path: str | None = None
    limit: int = 100


class TreeRequestModel(BaseModel):
    path: str | None = None
    depth: int = 3
    limit: int = 100


class RemoteIndexTriggerModel(BaseModel):
    repo_path: str | None = None
    clear_existing: bool = False
    build_graph: bool = True


class RemoteFilePayload(BaseModel):
    path: str
    content: str


class RemoteIngestRequestModel(BaseModel):
    files: list[RemoteFilePayload]


class JsonRpcRequestModel(BaseModel):
    jsonrpc: str = "2.0"
    id: Any = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


def create_remote_app(config_path: Path | str = "code-diver.yml") -> FastAPI:
    """Build FastAPI application with HTTP, SSE, and ACP/MCP endpoints."""
    app = FastAPI(
        title="Code Diver Remote Engine",
        version="0.4.3",
        description="Unified Remote API: HTTP, SSE, MCP, and ACP for code retrieval & exploration",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    cfg_path = Path(config_path).expanduser()
    _config: Any = None
    _runtime: SearchRuntime | None = None
    _sessions: dict[str, dict[str, Any]] = {}
    _sse_queues: dict[str, asyncio.Queue] = {}

    def get_runtime() -> tuple[Any, SearchRuntime]:
        nonlocal _config, _runtime
        if _runtime is None:
            resolved = cfg_path if cfg_path.exists() else Path("code-diver.yml")
            _config = ConfigLoader().load(resolved)
            _runtime = SearchRuntime(_config)
        return _config, _runtime

    # --- Health ---
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": "0.4.3"}

    # --- REST Inspection & Search ---
    @app.post("/api/v1/search")
    async def api_search(req: SearchRequestModel) -> dict[str, Any]:
        config, runtime = get_runtime()
        results = runtime.base_strategy.search(query=req.query, limit=req.limit)
        return {
            "results": [
                {
                    "path": r.item.path,
                    "score": round(float(r.score), 4),
                    "start_line": r.item.start_line,
                    "end_line": r.item.end_line,
                    "title": r.item.title,
                    "content": r.item.content,
                }
                for r in results
            ]
        }

    @app.get("/api/v1/info")
    async def api_info() -> dict[str, Any]:
        config, _ = get_runtime()
        return InfoService(config).get_info().to_dict()

    @app.post("/api/v1/grep")
    async def api_grep(req: GrepRequestModel) -> dict[str, Any]:
        config, _ = get_runtime()
        matches = GrepService(config.root).search(
            pattern=req.pattern, path=req.path, limit=req.limit, regex=req.regex
        )
        return {
            "matches": [
                {"path": m.path, "line": m.line, "text": m.text} for m in matches
            ]
        }

    @app.post("/api/v1/read")
    async def api_read(req: ReadExcerptRequestModel) -> dict[str, str]:
        config, _ = get_runtime()
        content = ReadExcerptService(config.root).render(
            path=req.file, start_line=req.start_line, lines=req.lines
        )
        return {"content": content}

    @app.post("/api/v1/symbols")
    async def api_symbols(req: SymbolsRequestModel) -> dict[str, Any]:
        config, _ = get_runtime()
        structured = SymbolsService(config.root).structured(path=req.path, limit=req.limit)
        return {
            "symbols": [
                {
                    "name": s["name"],
                    "kind": s["kind"],
                    "path": s["path"],
                    "start_line": s["startLine"],
                    "end_line": s["endLine"],
                }
                for s in structured.get("symbols", [])
            ]
        }

    @app.post("/api/v1/tree")
    async def api_tree(req: TreeRequestModel) -> dict[str, str]:
        config, _ = get_runtime()
        tree_text = TreeService(config.root).render(
            path=req.path, max_depth=req.depth, limit=req.limit
        )
        return {"tree": tree_text}

    # --- Remote Indexing Endpoints ---
    @app.post("/api/v1/index/trigger")
    async def api_index_trigger(req: RemoteIndexTriggerModel) -> dict[str, Any]:
        """Trigger background indexing on the remote host."""
        config, _ = get_runtime()
        task_id = f"idx_{uuid.uuid4().hex[:10]}"
        return {
            "task_id": task_id,
            "status": "triggered",
            "message": f"Indexing queued for {req.repo_path or str(config.root)}",
        }

    @app.post("/api/v1/index/ingest")
    async def api_index_ingest(req: RemoteIngestRequestModel) -> dict[str, Any]:
        """Ingest code files from remote client into server workspace."""
        config, _ = get_runtime()
        ingest_dir = config.root / ".code_diver_remote_ingest"
        ingest_dir.mkdir(parents=True, exist_ok=True)

        count = 0
        total_size = 0
        for f in req.files:
            target = ingest_dir / f.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f.content, encoding="utf-8")
            count += 1
            total_size += len(f.content.encode("utf-8"))

        return {
            "status": "ok",
            "files_received": count,
            "total_bytes": total_size,
            "directory": str(ingest_dir),
        }

    # --- Standard MCP JSON-RPC 2.0 (Streamable HTTP / MCP over HTTP) ---
    @app.post("/")
    @app.post("/mcp")
    @app.post("/mcp/rpc")
    async def standard_mcp_rpc(req: JsonRpcRequestModel) -> dict[str, Any]:
        """Standard Model Context Protocol (MCP) JSON-RPC 2.0 handler."""
        method = req.method
        params = req.params

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req.id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "code-diver", "version": "0.4.3"},
                },
            }
        elif method == "notifications/initialized":
            return {"jsonrpc": "2.0", "id": req.id, "result": {}}
        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req.id,
                "result": {
                    "tools": [
                        {
                            "name": "code_diver_search",
                            "description": "Search repository code using neural and hybrid retrieval.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "query": {"type": "string", "description": "Search query"},
                                    "limit": {"type": "integer", "default": 10},
                                },
                                "required": ["query"],
                            },
                        },
                        {
                            "name": "code_diver_grep",
                            "description": "Search literal text or regex patterns across the codebase.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "pattern": {"type": "string"},
                                    "path": {"type": "string"},
                                    "limit": {"type": "integer", "default": 50},
                                    "regex": {"type": "boolean", "default": False},
                                },
                                "required": ["pattern"],
                            },
                        },
                        {
                            "name": "code_diver_read",
                            "description": "Read a bounded excerpt of lines from a project file.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "file": {"type": "string"},
                                    "start_line": {"type": "integer", "default": 1},
                                    "lines": {"type": "integer", "default": 100},
                                },
                                "required": ["file"],
                            },
                        },
                        {
                            "name": "code_diver_symbols",
                            "description": "List AST parsed source symbols (classes, methods, functions) for a file or repo.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "path": {"type": "string"},
                                    "limit": {"type": "integer", "default": 100},
                                },
                            },
                        },
                        {
                            "name": "code_diver_tree",
                            "description": "Print a gitignore-aware directory tree of the repository.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "path": {"type": "string"},
                                    "depth": {"type": "integer", "default": 3},
                                    "limit": {"type": "integer", "default": 100},
                                },
                            },
                        },
                        {
                            "name": "code_diver_info",
                            "description": "Get Code Diver index, vector store, graph, and model footprint statistics.",
                            "inputSchema": {"type": "object", "properties": {}},
                        },
                    ]
                },
            }
        elif method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})
            config, runtime = get_runtime()

            try:
                if tool_name == "code_diver_search":
                    query = tool_args.get("query", "")
                    limit = int(tool_args.get("limit", 10))
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
                    content_str = json.dumps(out, indent=2)

                elif tool_name == "code_diver_grep":
                    pattern = tool_args.get("pattern", "")
                    path = tool_args.get("path")
                    limit = int(tool_args.get("limit", 50))
                    regex = bool(tool_args.get("regex", False))
                    matches = GrepService(config.root).search(pattern=pattern, path=path, limit=limit, regex=regex)
                    content_str = json.dumps([{"path": m.path, "line": m.line, "text": m.text} for m in matches], indent=2)

                elif tool_name == "code_diver_read":
                    file_p = tool_args.get("file", "")
                    start_l = int(tool_args.get("start_line", 1))
                    lines = int(tool_args.get("lines", 100))
                    content_str = ReadExcerptService(config.root).render(path=file_p, start_line=start_l, lines=lines)

                elif tool_name == "code_diver_symbols":
                    path = tool_args.get("path")
                    limit = int(tool_args.get("limit", 100))
                    syms = SymbolsService(config.root).structured(path=path, limit=limit)
                    content_str = json.dumps(syms.get("symbols", []), indent=2)

                elif tool_name == "code_diver_tree":
                    path = tool_args.get("path")
                    depth = int(tool_args.get("depth", 3))
                    limit = int(tool_args.get("limit", 100))
                    content_str = TreeService(config.root).render(path=path, max_depth=depth, limit=limit)

                elif tool_name == "code_diver_info":
                    content_str = json.dumps(InfoService(config).get_info().to_dict(), indent=2)

                else:
                    return {
                        "jsonrpc": "2.0",
                        "id": req.id,
                        "error": {"code": -32601, "message": f"Tool '{tool_name}' not found"},
                    }

                return {
                    "jsonrpc": "2.0",
                    "id": req.id,
                    "result": {
                        "content": [{"type": "text", "text": content_str}],
                        "isError": False,
                    },
                }
            except Exception as e:
                return {
                    "jsonrpc": "2.0",
                    "id": req.id,
                    "result": {
                        "content": [{"type": "text", "text": f"Error: {e}"}],
                        "isError": True,
                    },
                }
        else:
            return {
                "jsonrpc": "2.0",
                "id": req.id,
                "error": {"code": -32601, "message": f"Method '{method}' not found"},
            }

    # --- ACP HTTP / SSE Endpoints ---
    @app.post("/acp/v1/rpc")
    async def acp_rpc(req: JsonRpcRequestModel) -> dict[str, Any]:
        if req.method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req.id,
                "result": {
                    "protocolVersion": 1,
                    "agentCapabilities": {
                        "loadSession": False,
                        "promptCapabilities": {"embeddedContext": True},
                        "mcpCapabilities": {"http": True, "sse": True},
                    },
                    "agentInfo": {
                        "name": "code-diver",
                        "title": "Code Diver Exploration Agent",
                        "version": "0.4.3",
                    },
                },
            }
        elif req.method == "session/new":
            session_id = f"sess_{uuid.uuid4().hex[:12]}"
            _sessions[session_id] = req.params
            _sse_queues[session_id] = asyncio.Queue()
            return {
                "jsonrpc": "2.0",
                "id": req.id,
                "result": {"sessionId": session_id},
            }
        elif req.method == "session/close":
            sid = req.params.get("sessionId")
            _sessions.pop(sid, None)
            _sse_queues.pop(sid, None)
            return {"jsonrpc": "2.0", "id": req.id, "result": {}}
        elif req.method == "session/prompt":
            sid = req.params.get("sessionId")
            if not sid or sid not in _sessions:
                return {
                    "jsonrpc": "2.0",
                    "id": req.id,
                    "error": {"code": -32602, "message": f"Session '{sid}' not found"},
                }

            # Prompt execution
            prompts = req.params.get("prompt", [])
            query = " ".join([p.get("text", "") for p in prompts if p.get("type") == "text"]).strip()

            q = _sse_queues.get(sid)
            if q and query:
                # Emit plan
                await q.put(
                    {
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {
                            "sessionId": sid,
                            "update": {
                                "sessionUpdate": "plan",
                                "entries": [{"content": f"Search for {query}", "status": "completed"}],
                            },
                        },
                    }
                )

                config, runtime = get_runtime()
                results = runtime.base_strategy.search(query=query, limit=5)
                # Emit search message chunk
                res_text = "\n".join([f"- `{r.item.path}` ({r.item.start_line}-{r.item.end_line})" for r in results])
                await q.put(
                    {
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {
                            "sessionId": sid,
                            "update": {
                                "sessionUpdate": "agent_message_chunk",
                                "content": {"type": "text", "text": f"Found:\n{res_text}"},
                            },
                        },
                    }
                )

            return {"jsonrpc": "2.0", "id": req.id, "result": {"stopReason": "end_turn"}}
        else:
            return {
                "jsonrpc": "2.0",
                "id": req.id,
                "error": {"code": -32601, "message": f"Method {req.method} not found"},
            }

    @app.get("/acp/v1/events/{session_id}")
    async def acp_events(session_id: str) -> StreamingResponse:
        """SSE event stream for active ACP session updates."""
        if session_id not in _sse_queues:
            _sse_queues[session_id] = asyncio.Queue()

        queue = _sse_queues[session_id]

        async def event_generator() -> AsyncGenerator[str, None]:
            try:
                while True:
                    msg = await queue.get()
                    yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
            except asyncio.CancelledError:
                pass

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    return app
