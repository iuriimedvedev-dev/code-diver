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


class JsonRpcRequestModel(BaseModel):
    jsonrpc: str = "2.0"
    id: Any = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


def create_remote_app(config_path: Path | str = "code-diver.yml") -> FastAPI:
    """Build FastAPI application with HTTP, SSE, and ACP/MCP endpoints."""
    app = FastAPI(
        title="Code Diver Remote Engine",
        version="0.4.2",
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
        return {"status": "ok", "version": "0.4.2"}

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
                        "version": "0.4.2",
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
