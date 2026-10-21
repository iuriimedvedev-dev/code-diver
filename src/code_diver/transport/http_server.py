"""HTTP and SSE Remote Transport Server for Code Diver.

Provides:
- Standard MCP Streamable HTTP (`POST`/`GET`/`DELETE /mcp`) with sessions
- Legacy MCP JSON-RPC compatibility alias (`/mcp/rpc`, `/`)
- Native ACP over HTTP/SSE (`/acp/v1/rpc`, `/acp/v1/events`)
- Direct REST Search & Inspection APIs (`/api/v1/search`, `/api/v1/info`, `/api/v1/grep`, etc.)
- Optional OAuth 2.1 protection and diagnostics (`/health`, `/api/v1/runtime/stats`)

All transports share one lazily created :class:`SearchRuntime` per process.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
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
from .mcp_http import (
    RemoteToolService,
    SessionLimits,
    SessionRegistry,
    register_mcp_routes,
    runtime_fingerprint,
)
from .oauth import (
    OAuthError,
    OAuthProvider,
    OAuthSettings,
    bearer_token,
    protected_path_scope,
)

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


def create_remote_app(
    config_path: Path | str = "code-diver.yml",
    *,
    oauth: OAuthProvider | Literal[False] | None = None,
    runtime_factory: Callable[[Path], tuple[Any, SearchRuntime]] | None = None,
    session_limits: SessionLimits | None = None,
    index_runner: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    """Build the FastAPI application with MCP, REST, and ACP transports.

    Args:
        config_path: Path to the repository ``code-diver.yml``.
        oauth: ``None`` resolves OAuth from the environment, ``False`` forces it
            off, and an :class:`OAuthProvider` instance enables it (tests).
        runtime_factory: Optional override used by tests to count runtime loads.
        session_limits: MCP session limits (defaults to environment values).
        index_runner: Optional override for the write-scope index tool.
        cors_origins: Explicit CORS origins (defaults to env/issuer).
    """
    app = FastAPI(
        title="Code Diver Remote Engine",
        version="0.4.5",
        description="Unified Remote API: HTTP, SSE, MCP, and ACP for code retrieval & exploration",
    )

    cfg_path = Path(config_path).expanduser()
    _config: Any = None
    _runtime: SearchRuntime | None = None
    _sessions: dict[str, dict[str, Any]] = {}
    _sse_queues: dict[str, asyncio.Queue] = {}
    started_at = datetime.now(UTC).isoformat()
    runtime_state: dict[str, Any] = {"loads": 0, "created_at": None}

    if oauth is None:
        oauth_settings = OAuthSettings.from_env()
        oauth_provider: OAuthProvider | None = (
            OAuthProvider(oauth_settings) if oauth_settings.enabled else None
        )
    elif oauth is False:
        oauth_provider = None
    elif isinstance(oauth, OAuthProvider):
        oauth_provider = oauth
    else:  # pragma: no cover - defensive
        raise TypeError("oauth must be None, False, or an OAuthProvider")

    sessions = SessionRegistry(session_limits or SessionLimits.from_env())

    configured_origins = (
        cors_origins if cors_origins is not None else os.environ.get("CODE_DIVER_CORS_ORIGINS")
    )
    if configured_origins is None:
        origins = [oauth_provider.settings.issuer] if oauth_provider is not None else ["*"]
    elif isinstance(configured_origins, str):
        origins = [origin.strip() for origin in configured_origins.split(",") if origin.strip()]
    else:
        origins = list(configured_origins)
    origins = origins or ["*"]

    def get_runtime() -> tuple[Any, SearchRuntime]:
        nonlocal _config, _runtime
        if _runtime is None:
            resolved = cfg_path if cfg_path.exists() else Path("code-diver.yml")
            if runtime_factory is not None:
                _config, _runtime = runtime_factory(resolved)
            else:
                _config = ConfigLoader().load(resolved)
                _runtime = SearchRuntime(_config)
            runtime_state["loads"] += 1
            runtime_state["created_at"] = datetime.now(UTC).isoformat()
            logger.info(
                "runtime: loaded %s for %s (load #%s)",
                type(_runtime).__name__,
                resolved,
                runtime_state["loads"],
            )
        return _config, _runtime

    # --- Health ---
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": "0.4.5"}

    # --- REST Inspection & Search ---
    @app.post("/api/v1/search")
    async def api_search(req: SearchRequestModel) -> dict[str, Any]:
        _, runtime = get_runtime()
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

    # --- Remote Indexing Endpoints (write scope when OAuth is enabled) ---
    @app.post("/api/v1/index/trigger")
    async def api_index_trigger(req: RemoteIndexTriggerModel) -> dict[str, Any]:
        """Trigger background indexing on the remote host."""
        config, _ = get_runtime()
        result = service.call(
            "code_diver_index_trigger",
            {
                "repo_path": req.repo_path,
                "clear_existing": req.clear_existing,
                "build_graph": req.build_graph,
            },
            scopes=None,
        )
        if result.get("isError"):
            return {"status": "error", "message": result["content"][0]["text"]}
        task = json.loads(result["content"][0]["text"])
        return {
            "task_id": task.get("task_id"),
            "status": "triggered",
            "message": f"Indexing queued for {req.repo_path or str(config.root)}",
        }

    @app.post("/api/v1/index/ingest")
    async def api_index_ingest(req: RemoteIngestRequestModel) -> dict[str, Any]:
        """Ingest code files from a remote client into the server workspace."""
        result = service.call(
            "code_diver_index_ingest",
            {"files": [payload.model_dump() for payload in req.files]},
            scopes=None,
        )
        if result.get("isError"):
            raise HTTPException(status_code=400, detail=result["content"][0]["text"])
        return json.loads(result["content"][0]["text"])

    # --- Shared MCP tool service (standard Streamable HTTP + compatibility) ---
    service = RemoteToolService(
        get_runtime,
        config_path=cfg_path,
        index_runner=index_runner,
    )
    register_mcp_routes(app, service, sessions, oauth_provider, allowed_origins=origins)

    @app.get("/api/v1/runtime/stats")
    async def api_runtime_stats() -> dict[str, Any]:
        """Prove that every client shares one lazily-loaded SearchRuntime."""
        return {
            "pid": os.getpid(),
            "started_at": started_at,
            "runtime_loads": runtime_state["loads"],
            "runtime_created_at": runtime_state["created_at"],
            "runtime": runtime_fingerprint(_runtime),
            "mcp_sessions": sessions.stats(),
            "tools": service.stats(),
            "oauth": {
                "enabled": oauth_provider is not None,
                "issuer": oauth_provider.settings.issuer if oauth_provider else None,
            },
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
                        "version": "0.4.5",
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

                _, runtime = get_runtime()
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

    # --- OAuth 2.1 protection (disabled by default) ---
    if oauth_provider is not None:
        settings = oauth_provider.settings
        oauth_provider.register_routes(app)

        @app.middleware("http")
        async def oauth_guard(request: Request, call_next):  # type: ignore[no-untyped-def]
            required = protected_path_scope(request.url.path, protect_rest=settings.protect_rest)
            if required is None:
                return await call_next(request)
            token = bearer_token(request)
            if token is None:
                logger.info("oauth: rejected unauthenticated %s %s", request.method, request.url.path)
                return JSONResponse(
                    {"error": "invalid_token", "error_description": "Bearer token required"},
                    status_code=401,
                    headers={"WWW-Authenticate": oauth_provider.challenge()},
                )
            try:
                principal = oauth_provider.authenticate(token)
                oauth_provider.require(principal, required)
            except OAuthError as exc:
                logger.info("oauth: rejected token for %s: %s", request.url.path, exc.error)
                return JSONResponse(
                    {"error": exc.error, "error_description": exc.description},
                    status_code=exc.status_code,
                    headers={
                        "WWW-Authenticate": oauth_provider.challenge(
                            error=exc.error,
                            description=exc.description,
                            scope=required if exc.error == "insufficient_scope" else None,
                        )
                    },
                )
            request.state.principal = principal
            return await call_next(request)

    # CORS is registered last so it wraps the auth guard and decorates 401/403s.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Mcp-Session-Id", "Mcp-Protocol-Version"],
    )

    return app
