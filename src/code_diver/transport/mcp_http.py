"""Standard MCP Streamable HTTP transport for Code Diver.

The 2025-06-18 Streamable HTTP transport is implemented directly on top of the
existing FastAPI application so that every MCP client session shares the single
``SearchRuntime`` owned by :mod:`code_diver.transport.http_server` — no
per-session child process and no second index load.

Endpoints
---------
``POST /mcp``    JSON-RPC request/notification; returns ``application/json`` or
                 ``text/event-stream`` depending on the caller's ``Accept``.
``GET /mcp``     server-to-client SSE stream for an established session.
``DELETE /mcp``  terminate a session.

Transport invariants
--------------------
* ``initialize`` creates a session and returns ``Mcp-Session-Id``.
* Every later request must carry that header or the server answers ``404``.
* Notifications are acknowledged with ``202`` and no body.
* ``MCP-Protocol-Version`` is validated for established sessions.
* Sessions are bound to the bearer-token subject that created them.
* Old clients that POST JSON without an SSE-capable ``Accept`` header keep
  working through the legacy alias at ``POST /mcp/rpc`` (and ``POST /``) — the
  same dispatcher and the same shared runtime serve both paths.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import shutil
import subprocess
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from .. import build_version
from ..inspection.grep_service import GrepService
from ..inspection.info_service import InfoService
from ..inspection.read_excerpt_service import ReadExcerptService
from ..inspection.symbols_service import SymbolsService
from ..inspection.tree_service import TreeService
from ..mcp.tasks import BackgroundTaskManager
from .oauth import (
    READ_SCOPE,
    WRITE_SCOPE,
    OAuthError,
    OAuthProvider,
    Principal,
)

logger = logging.getLogger("code_diver.transport.mcp_http")

SERVER_NAME = "code-diver"
# The checkout's git description (dirty state included), not a constant: this is what the
# server reports as ``serverInfo.version``. A hardcoded value here once read 0.4.5 long after
# the package shipped 0.6.5, so a benchmark row could name a release the tree had left.
SERVER_VERSION = build_version()

MCP_SESSION_HEADER = "mcp-session-id"
MCP_PROTOCOL_HEADER = "mcp-protocol-version"
MCP_LAST_EVENT_HEADER = "last-event-id"

JSON_CONTENT_TYPE = "application/json"
SSE_CONTENT_TYPE = "text/event-stream"

# Handshake-era revisions: 2024-11-05 (legacy HTTP+SSE), 2025-03-26 (first
# Streamable HTTP revision), 2025-06-18 (session + protocol header), 2025-11-25.
SUPPORTED_PROTOCOL_VERSIONS: tuple[str, ...] = (
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
    "2025-11-25",
)
LATEST_PROTOCOL_VERSION = "2025-06-18"
LEGACY_PROTOCOL_VERSION = "2024-11-05"

RPC_PARSE_ERROR = -32700
RPC_INVALID_REQUEST = -32600
RPC_METHOD_NOT_FOUND = -32601
RPC_INVALID_PARAMS = -32602
RPC_INTERNAL_ERROR = -32603
RPC_INSUFFICIENT_SCOPE = -32003

DEFAULT_MAX_REQUEST_BYTES = 4 * 1024 * 1024
DEFAULT_SESSION_IDLE_SECONDS = 1800
DEFAULT_MAX_SESSIONS = 256


class ToolError(Exception):
    """Raised by tool handlers for client-correctable failures."""

    def __init__(self, message: str, *, code: int = RPC_INVALID_PARAMS) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SessionLimits:
    """Resource limits for stateful MCP sessions."""

    max_sessions: int = DEFAULT_MAX_SESSIONS
    idle_timeout: float = DEFAULT_SESSION_IDLE_SECONDS
    ping_interval: float = 15.0
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> SessionLimits:
        source = os.environ if env is None else env

        def _int(key: str, default: int, minimum: int) -> int:
            raw = source.get(key)
            if not raw:
                return default
            try:
                value = int(raw)
            except ValueError as exc:
                raise ValueError(f"{key} must be an integer") from exc
            if value < minimum:
                raise ValueError(f"{key} must be >= {minimum}")
            return value

        return cls(
            max_sessions=_int("CODE_DIVER_MCP_MAX_SESSIONS", DEFAULT_MAX_SESSIONS, 1),
            idle_timeout=float(_int("CODE_DIVER_MCP_SESSION_IDLE", DEFAULT_SESSION_IDLE_SECONDS, 30)),
            ping_interval=float(_int("CODE_DIVER_MCP_SSE_PING", 15, 1)),
            max_request_bytes=_int("CODE_DIVER_MCP_MAX_BODY", DEFAULT_MAX_REQUEST_BYTES, 1024),
        )


@dataclass
class MCPSession:
    """State for one Streamable HTTP session."""

    session_id: str
    protocol_version: str
    subject: str
    client_id: str
    scopes: frozenset[str]
    created_at: float
    last_seen: float
    initialized: bool = False
    events: asyncio.Queue[dict[str, Any]] = field(default_factory=lambda: asyncio.Queue(maxsize=128))

    def touch(self) -> None:
        self.last_seen = time.time()


class SessionRegistry:
    """In-process session table shared by every HTTP client of one app."""

    def __init__(self, limits: SessionLimits | None = None) -> None:
        self.limits = limits or SessionLimits()
        self._sessions: dict[str, MCPSession] = {}
        self._lock = threading.Lock()
        self.created_total = 0
        self.deleted_total = 0
        self.expired_total = 0

    def create(self, *, protocol_version: str, subject: str, client_id: str, scopes: frozenset[str]) -> MCPSession:
        self.sweep()
        with self._lock:
            if len(self._sessions) >= self.limits.max_sessions:
                raise ToolError("Too many active MCP sessions", code=RPC_INTERNAL_ERROR)
            session_id = secrets.token_urlsafe(32)
            now = time.time()
            session = MCPSession(
                session_id=session_id,
                protocol_version=protocol_version,
                subject=subject,
                client_id=client_id,
                scopes=scopes,
                created_at=now,
                last_seen=now,
                initialized=True,
            )
            self._sessions[session_id] = session
            self.created_total += 1
        logger.info(
            "mcp: new session %s subject=%s client=%s protocol=%s",
            session_id[:8],
            subject,
            client_id or "-",
            protocol_version,
        )
        return session

    def get(self, session_id: str | None) -> MCPSession | None:
        if not session_id:
            return None
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            return None
        if time.time() - session.last_seen > self.limits.idle_timeout:
            self.delete(session_id)
            with self._lock:
                self.expired_total += 1
            return None
        session.touch()
        return session

    def delete(self, session_id: str) -> bool:
        with self._lock:
            removed = self._sessions.pop(session_id, None)
            if removed is not None:
                self.deleted_total += 1
        return removed is not None

    def sweep(self) -> None:
        cutoff = time.time() - self.limits.idle_timeout
        with self._lock:
            stale = [sid for sid, session in self._sessions.items() if session.last_seen < cutoff]
            for session_id in stale:
                self._sessions.pop(session_id, None)
                self.expired_total += 1

    def stats(self) -> dict[str, Any]:
        with self._lock:
            active = len(self._sessions)
            subjects = {session.subject for session in self._sessions.values()}
        return {
            "active": active,
            "created_total": self.created_total,
            "deleted_total": self.deleted_total,
            "expired_total": self.expired_total,
            "subjects": sorted(subjects),
            "max_sessions": self.limits.max_sessions,
            "idle_timeout_seconds": self.limits.idle_timeout,
        }

    def close_all(self) -> None:
        with self._lock:
            self._sessions.clear()


@dataclass(frozen=True)
class ToolSpec:
    """A single MCP tool with its JSON schema and required scopes."""

    name: str
    description: str
    input_schema: dict[str, Any]
    required_scopes: tuple[str, ...]
    handler: Callable[[RemoteToolService, dict[str, Any]], str]

    def to_mcp(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": {
                "readOnlyHint": WRITE_SCOPE not in self.required_scopes,
                "destructiveHint": False,
                "idempotentHint": WRITE_SCOPE not in self.required_scopes,
                "openWorldHint": False,
            },
        }


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


class RemoteToolService:
    """Shared tool implementation behind every HTTP transport.

    One instance exists per FastAPI app; it owns the background task manager
    and delegates index access to the app's single ``SearchRuntime`` provider.
    """

    def __init__(
        self,
        get_runtime: Callable[[], tuple[Any, Any]],
        *,
        config_path: str | Path = "code-diver.yml",
        task_manager: BackgroundTaskManager | None = None,
        index_runner: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self._get_runtime = get_runtime
        self.config_path = str(Path(config_path).expanduser().resolve())
        self.tasks = task_manager or BackgroundTaskManager(max_workers=2)
        self._index_runner = index_runner
        self.call_count = 0
        self._counts: dict[str, int] = {}
        self._counts_lock = threading.Lock()
        self._tools = self._build_tools()

    # --- tool registry -----------------------------------------------------
    def _build_tools(self) -> dict[str, ToolSpec]:
        tools = [
            ToolSpec(
                name="code_diver_search",
                description="Search repository code using neural and hybrid retrieval.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "limit": {"type": "integer", "default": 10},
                    },
                    "required": ["query"],
                },
                required_scopes=(READ_SCOPE,),
                handler=_tool_search,
            ),
            ToolSpec(
                name="code_diver_grep",
                description="Search literal text or regex patterns across the codebase.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "path": {"type": "string"},
                        "limit": {"type": "integer", "default": 50},
                        "regex": {"type": "boolean", "default": False},
                    },
                    "required": ["pattern"],
                },
                required_scopes=(READ_SCOPE,),
                handler=_tool_grep,
            ),
            ToolSpec(
                name="code_diver_read",
                description="Read a bounded excerpt of lines from a project file.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "file": {"type": "string"},
                        "start_line": {"type": "integer", "default": 1},
                        "lines": {"type": "integer", "default": 100},
                    },
                    "required": ["file"],
                },
                required_scopes=(READ_SCOPE,),
                handler=_tool_read,
            ),
            ToolSpec(
                name="code_diver_symbols",
                description="List AST parsed source symbols (classes, methods, functions) for a file or repo.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "limit": {"type": "integer", "default": 100},
                    },
                },
                required_scopes=(READ_SCOPE,),
                handler=_tool_symbols,
            ),
            ToolSpec(
                name="code_diver_tree",
                description="Print a gitignore-aware directory tree of the repository.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "depth": {"type": "integer", "default": 3},
                        "limit": {"type": "integer", "default": 100},
                    },
                },
                required_scopes=(READ_SCOPE,),
                handler=_tool_tree,
            ),
            ToolSpec(
                name="code_diver_info",
                description="Get Code Diver index, vector store, graph, and model footprint statistics.",
                input_schema={"type": "object", "properties": {}},
                required_scopes=(READ_SCOPE,),
                handler=_tool_info,
            ),
            ToolSpec(
                name="code_diver_submit_agent_search",
                description=(
                    "Submit a background search task to run asynchronously. Returns a task handle with "
                    "task_id immediately; poll code_diver_task_status until completed."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "default": 10},
                        "include_symbols": {"type": "boolean", "default": True},
                    },
                    "required": ["query"],
                },
                required_scopes=(READ_SCOPE,),
                handler=_tool_submit_agent_search,
            ),
            ToolSpec(
                name="code_diver_task_status",
                description="Check status of a background task ('working'|'completed'|'failed'|'cancelled').",
                input_schema={
                    "type": "object",
                    "properties": {"task_id": {"type": "string"}},
                    "required": ["task_id"],
                },
                required_scopes=(READ_SCOPE,),
                handler=_tool_task_status,
            ),
            ToolSpec(
                name="code_diver_task_result",
                description="Fetch result payload of a completed background task.",
                input_schema={
                    "type": "object",
                    "properties": {"task_id": {"type": "string"}},
                    "required": ["task_id"],
                },
                required_scopes=(READ_SCOPE,),
                handler=_tool_task_result,
            ),
            ToolSpec(
                name="code_diver_task_cancel",
                description="Cancel a running background task.",
                input_schema={
                    "type": "object",
                    "properties": {"task_id": {"type": "string"}},
                    "required": ["task_id"],
                },
                required_scopes=(READ_SCOPE,),
                handler=_tool_task_cancel,
            ),
            ToolSpec(
                name="code_diver_tasks_list",
                description="List recent background tasks tracked by Code Diver.",
                input_schema={
                    "type": "object",
                    "properties": {"limit": {"type": "integer", "default": 20}},
                },
                required_scopes=(READ_SCOPE,),
                handler=_tool_tasks_list,
            ),
            ToolSpec(
                name="code_diver_index_trigger",
                description=(
                    "Re-index the repository in the background. Requires the code:write scope. "
                    "Runs the canonical `code-diver index` command on the server."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "repo_path": {"type": "string"},
                        "clear_existing": {"type": "boolean", "default": False},
                        "build_graph": {"type": "boolean", "default": True},
                    },
                },
                required_scopes=(WRITE_SCOPE,),
                handler=_tool_index_trigger,
            ),
            ToolSpec(
                name="code_diver_index_ingest",
                description=(
                    "Write client files into the server-side ingest directory before indexing. "
                    "Requires the code:write scope; paths are confined to the repository root."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "files": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                                "required": ["path", "content"],
                            },
                        }
                    },
                    "required": ["files"],
                },
                required_scopes=(WRITE_SCOPE,),
                handler=_tool_index_ingest,
            ),
        ]
        return {tool.name: tool for tool in tools}

    def all_tools(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def tool(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def list_tools(self, scopes: frozenset[str] | None) -> list[dict[str, Any]]:
        visible = []
        for tool in self._tools.values():
            if scopes is None or set(tool.required_scopes).issubset(scopes):
                visible.append(tool.to_mcp())
        return visible

    def call(self, name: str, arguments: Mapping[str, Any], scopes: frozenset[str] | None) -> dict[str, Any]:
        """Execute a tool and return an MCP ``CallToolResult`` payload."""
        spec = self._tools.get(name)
        if spec is None:
            raise ToolError(f"Tool {name!r} not found", code=RPC_METHOD_NOT_FOUND)
        if scopes is not None and not set(spec.required_scopes).issubset(scopes):
            raise OAuthError(
                "insufficient_scope",
                f"Tool {name!r} requires scope {' '.join(spec.required_scopes)}",
                status_code=403,
            )
        args = dict(arguments or {})
        with self._counts_lock:
            self.call_count += 1
            self._counts[name] = self._counts.get(name, 0) + 1
        try:
            text = spec.handler(self, args)
        except ToolError as exc:
            return {
                "content": [{"type": "text", "text": f"Error: {exc}"}],
                "isError": True,
            }
        except Exception as exc:
            logger.exception("mcp: tool %s failed", name)
            return {
                "content": [{"type": "text", "text": f"Error: {exc}"}],
                "isError": True,
            }
        return {"content": [{"type": "text", "text": text}], "isError": False}

    # --- runtime / metrics -------------------------------------------------
    def runtime(self) -> tuple[Any, Any]:
        return self._get_runtime()

    def stats(self) -> dict[str, Any]:
        with self._counts_lock:
            counts = dict(self._counts)
            total = self.call_count
        return {"tool_calls_total": total, "tool_calls_by_name": counts}

    # --- write helpers -----------------------------------------------------
    def resolve_index_target(self, request: Mapping[str, Any]) -> tuple[Path, Path]:
        """Validate a requested index path synchronously (before queueing work)."""
        config, _ = self.runtime()
        root = Path(config.root).resolve()
        target = Path(request.get("repo_path") or root).expanduser().resolve()
        if target != root and root not in target.parents:
            raise ToolError("repo_path must stay inside the configured repository root")
        if not target.exists():
            raise ToolError(f"repo_path does not exist: {target}")
        return target, root

    def run_index(self, request: dict[str, Any]) -> dict[str, Any]:
        if self._index_runner is not None:
            return self._index_runner(request)
        target, root = self.resolve_index_target(request)
        binary = os.environ.get("CODE_DIVER_BIN") or shutil.which("code-diver")
        if not binary:
            raise ToolError("code-diver executable not found; set CODE_DIVER_BIN")
        command = [binary, "--config", self.config_path, "index", "--quiet"]
        if request.get("clear_existing"):
            command.insert(-1, "--override-repo")
        if str(target) != str(root):
            command.append(str(target))
        timeout = int(os.environ.get("CODE_DIVER_INDEX_TIMEOUT", "3600"))
        started = time.time()
        logger.info("mcp: index trigger %s", command)
        completed = subprocess.run(
            command,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "status": "completed" if completed.returncode == 0 else "failed",
            "returncode": completed.returncode,
            "repo_path": str(target),
            "duration_seconds": round(time.time() - started, 2),
            "stdout_tail": completed.stdout[-2000:],
            "stderr_tail": completed.stderr[-2000:],
        }


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def _tool_search(service: RemoteToolService, args: dict[str, Any]) -> str:
    query = str(args.get("query") or "").strip()
    if not query:
        raise ToolError("query is required")
    limit = int(args.get("limit", 10))
    _, runtime = service.runtime()
    results = runtime.base_strategy.search(query=query, limit=limit)
    items = [
        {
            "path": result.item.path,
            "score": round(float(result.score), 4),
            "start_line": result.item.start_line,
            "end_line": result.item.end_line,
            "title": result.item.title,
            "content_preview": (
                result.item.content[:300] + "..." if len(result.item.content) > 300 else result.item.content
            ),
        }
        for result in results
    ]
    return _json(items)


def _tool_grep(service: RemoteToolService, args: dict[str, Any]) -> str:
    pattern = str(args.get("pattern") or "")
    if not pattern:
        raise ToolError("pattern is required")
    config, _ = service.runtime()
    matches = GrepService(config.root).search(
        pattern=pattern,
        path=args.get("path"),
        limit=int(args.get("limit", 50)),
        regex=bool(args.get("regex", False)),
    )
    return _json([{"path": match.path, "line": match.line, "text": match.text} for match in matches])


def _tool_read(service: RemoteToolService, args: dict[str, Any]) -> str:
    file_path = str(args.get("file") or "")
    if not file_path:
        raise ToolError("file is required")
    config, _ = service.runtime()
    return ReadExcerptService(config.root).render(
        path=file_path,
        start_line=int(args.get("start_line", 1)),
        lines=int(args.get("lines", 100)),
    )


def _tool_symbols(service: RemoteToolService, args: dict[str, Any]) -> str:
    config, _ = service.runtime()
    payload = SymbolsService(config.root).structured(
        path=args.get("path"), limit=int(args.get("limit", 100))
    )
    return _json(payload.get("symbols", []))


def _tool_tree(service: RemoteToolService, args: dict[str, Any]) -> str:
    config, _ = service.runtime()
    return TreeService(config.root).render(
        path=args.get("path"),
        max_depth=int(args.get("depth", 3)),
        limit=int(args.get("limit", 100)),
    )


def _tool_info(service: RemoteToolService, args: dict[str, Any]) -> str:
    config, _ = service.runtime()
    return _json(InfoService(config).get_info().to_dict())


def _tool_submit_agent_search(service: RemoteToolService, args: dict[str, Any]) -> str:
    query = str(args.get("query") or "").strip()
    if not query:
        raise ToolError("query is required")
    limit = int(args.get("limit", 10))
    include_symbols = bool(args.get("include_symbols", True))

    def _execute() -> dict[str, Any]:
        config, runtime = service.runtime()
        results = runtime.base_strategy.search(query=query, limit=limit)
        items = []
        for result in results:
            item: dict[str, Any] = {
                "path": result.item.path,
                "score": round(float(result.score), 4),
                "start_line": result.item.start_line,
                "end_line": result.item.end_line,
                "title": result.item.title,
                "content_preview": (
                    result.item.content[:400] + "..."
                    if len(result.item.content) > 400
                    else result.item.content
                ),
            }
            if include_symbols:
                try:
                    symbols = SymbolsService(config.root).list_symbols(path=result.item.path, limit=20)
                    item["file_symbols"] = [symbol.name for symbol in symbols]
                except Exception:
                    item["file_symbols"] = []
            items.append(item)
        return {"query": query, "total_results": len(items), "items": items}

    info = service.tasks.submit_task(name=f"agent_search: {query[:60]}", fn=_execute, poll_interval_ms=500)
    return _json(info)


def _tool_task_status(service: RemoteToolService, args: dict[str, Any]) -> str:
    return _json(service.tasks.get_status(_task_id(args)))


def _tool_task_result(service: RemoteToolService, args: dict[str, Any]) -> str:
    return _json(service.tasks.get_result(_task_id(args)))


def _tool_task_cancel(service: RemoteToolService, args: dict[str, Any]) -> str:
    return _json(service.tasks.cancel_task(_task_id(args)))


def _tool_tasks_list(service: RemoteToolService, args: dict[str, Any]) -> str:
    return _json(service.tasks.list_tasks(limit=int(args.get("limit", 20))))


def _task_id(args: dict[str, Any]) -> str:
    task_id = str(args.get("task_id") or "").strip()
    if not task_id:
        raise ToolError("task_id is required")
    return task_id


def _tool_index_trigger(service: RemoteToolService, args: dict[str, Any]) -> str:
    request = {
        "repo_path": args.get("repo_path"),
        "clear_existing": bool(args.get("clear_existing", False)),
        "build_graph": bool(args.get("build_graph", True)),
    }
    # Fail fast on scope/path errors instead of accepting a job that can never run.
    service.resolve_index_target(request)
    info = service.tasks.submit_task(
        name=f"index_trigger: {request['repo_path'] or 'default'}",
        fn=lambda: service.run_index(request),
        poll_interval_ms=2000,
    )
    return _json(info)


def _tool_index_ingest(service: RemoteToolService, args: dict[str, Any]) -> str:
    files = args.get("files")
    if not isinstance(files, list) or not files:
        raise ToolError("files must be a non-empty array")
    if len(files) > int(os.environ.get("CODE_DIVER_INGEST_MAX_FILES", "500")):
        raise ToolError("too many files in one ingest call")
    config, _ = service.runtime()
    root = Path(config.root).resolve()
    ingest_dir = root / ".code_diver_remote_ingest"
    ingest_dir.mkdir(parents=True, exist_ok=True)
    base = ingest_dir.resolve()
    total_bytes = 0
    written = 0
    for entry in files:
        if not isinstance(entry, dict):
            raise ToolError("each file entry must be an object")
        raw_path = str(entry.get("path") or "")
        content = entry.get("content")
        if not isinstance(content, str):
            raise ToolError("file content must be a string")
        candidate = (base / raw_path).resolve()
        if candidate != base and base not in candidate.parents:
            raise ToolError(f"path escapes the ingest directory: {raw_path!r}")
        if candidate == base:
            raise ToolError("file path must name a file")
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text(content, encoding="utf-8")
        written += 1
        total_bytes += len(content.encode("utf-8"))
    return _json(
        {
            "status": "ok",
            "files_received": written,
            "total_bytes": total_bytes,
            "directory": str(ingest_dir),
        }
    )


# ---------------------------------------------------------------------------
# JSON-RPC dispatch
# ---------------------------------------------------------------------------


def rpc_error(request_id: Any, code: int, message: str, data: Any | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def rpc_result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def negotiate_protocol_version(requested: str | None) -> str:
    if requested and requested in SUPPORTED_PROTOCOL_VERSIONS:
        return requested
    return LATEST_PROTOCOL_VERSION


def initialize_result(protocol_version: str) -> dict[str, Any]:
    return {
        "protocolVersion": negotiate_protocol_version(protocol_version),
        "capabilities": {
            "tools": {"listChanged": False},
            "resources": {"listChanged": False, "subscribe": False},
            "prompts": {"listChanged": False},
        },
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        "instructions": (
            "Code Diver exposes read-only repository search and inspection tools. "
            "Indexing tools require the code:write OAuth scope."
        ),
    }


def dispatch_rpc(
    service: RemoteToolService,
    message: Mapping[str, Any],
    *,
    scopes: frozenset[str] | None,
    protocol_version: str = LATEST_PROTOCOL_VERSION,
) -> dict[str, Any] | None:
    """Dispatch one JSON-RPC message; returns None for notifications."""
    method = message.get("method")
    request_id = message.get("id")
    if not isinstance(method, str) or not method:
        return rpc_error(request_id, RPC_INVALID_REQUEST, "Missing JSON-RPC method")
    is_notification = "id" not in message
    if is_notification:
        # notifications/initialized, notifications/cancelled, logging/setLevel …
        logger.debug("mcp: notification %s", method)
        return None
    params = message.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return rpc_error(request_id, RPC_INVALID_PARAMS, "params must be an object")
    try:
        if method == "initialize":
            return rpc_result(request_id, initialize_result(params.get("protocolVersion") or protocol_version))
        if method == "ping":
            return rpc_result(request_id, {})
        if method == "tools/list":
            return rpc_result(request_id, {"tools": service.list_tools(scopes)})
        if method == "tools/call":
            name = params.get("name")
            if not isinstance(name, str) or not name:
                return rpc_error(request_id, RPC_INVALID_PARAMS, "tools/call requires a tool name")
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                return rpc_error(request_id, RPC_INVALID_PARAMS, "arguments must be an object")
            if scopes is not None:
                spec = service.tool(name)
                if spec is not None and not set(spec.required_scopes).issubset(scopes):
                    return rpc_error(
                        request_id,
                        RPC_INSUFFICIENT_SCOPE,
                        f"Tool {name!r} requires scope {' '.join(spec.required_scopes)}",
                        {"required_scope": " ".join(spec.required_scopes)},
                    )
            result = service.call(name, arguments, scopes)
            return rpc_result(request_id, result)
        if method == "resources/list":
            return rpc_result(request_id, {"resources": []})
        if method == "resources/templates/list":
            return rpc_result(request_id, {"resourceTemplates": []})
        if method == "prompts/list":
            return rpc_result(request_id, {"prompts": []})
        if method == "logging/setLevel":
            return rpc_result(request_id, {})
        if method == "completion/complete":
            return rpc_result(request_id, {"completion": {"values": [], "hasMore": False}})
    except OAuthError as exc:
        return rpc_error(
            request_id,
            RPC_INSUFFICIENT_SCOPE if exc.error == "insufficient_scope" else RPC_INVALID_REQUEST,
            exc.description or exc.error,
            {"error": exc.error},
        )
    except ToolError as exc:
        return rpc_error(request_id, exc.code, str(exc))
    return rpc_error(request_id, RPC_METHOD_NOT_FOUND, f"Method {method!r} not found")


# ---------------------------------------------------------------------------
# HTTP transport
# ---------------------------------------------------------------------------


class JsonRpcRequestModel(BaseModel):
    """Legacy pydantic model retained for the compatibility alias."""

    jsonrpc: str = "2.0"
    id: Any = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


def _accepts(accept: str, content_type: str) -> bool:
    return content_type in accept or "*/*" in accept or not accept


def _sse_response(payload: Mapping[str, Any], *, session_id: str | None = None) -> StreamingResponse:
    body = f"event: message\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def generator():
        yield body

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    if session_id:
        headers[MCP_SESSION_HEADER] = session_id
    return StreamingResponse(generator(), media_type=SSE_CONTENT_TYPE, headers=headers)


def _json_response(payload: Mapping[str, Any], *, status: int = 200, session_id: str | None = None) -> JSONResponse:
    headers = {"Cache-Control": "no-store"}
    if session_id:
        headers[MCP_SESSION_HEADER] = session_id
    return JSONResponse(payload, status_code=status, headers=headers)


def _principal(request: Request, provider: OAuthProvider | None) -> Principal | None:
    return getattr(request.state, "principal", None) if provider is not None else None


def _scopes(request: Request, provider: OAuthProvider | None) -> frozenset[str] | None:
    principal = _principal(request, provider)
    return None if principal is None else principal.scopes


def _subject(request: Request, provider: OAuthProvider | None) -> tuple[str, str]:
    principal = _principal(request, provider)
    if principal is None:
        return "anonymous", ""
    return principal.subject, principal.client_id


def _origin_allowed(origin: str | None, allowed: list[str] | None) -> bool:
    """Reject cross-origin browser requests unless explicitly allow-listed."""
    if not origin or not allowed or "*" in allowed:
        return True
    normalized = origin.rstrip("/")
    return any(normalized == candidate.rstrip("/") for candidate in allowed)


async def _read_limited_body(request: Request, limit: int) -> bytes | None:
    """Read a request body without buffering more than ``limit`` bytes."""
    declared = request.headers.get("content-length")
    if declared:
        try:
            if int(declared) > limit:
                return None
        except ValueError:
            return None
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            return None
    return bytes(body)


def register_mcp_routes(
    app: FastAPI,
    service: RemoteToolService,
    registry: SessionRegistry,
    provider: OAuthProvider | None,
    *,
    legacy_paths: Iterable[str] = ("/mcp/rpc", "/"),
    allowed_origins: list[str] | None = None,
) -> None:
    """Register standard Streamable HTTP routes and legacy aliases."""

    limits = registry.limits

    async def handle_legacy(request: Request, body: bytes | None = None) -> Response:
        if provider is not None and request.url.path == "/":
            return JSONResponse(
                {"error": "not_found", "error_description": "Legacy root MCP endpoint is disabled while OAuth is enabled"},
                status_code=404,
            )
        if body is None:
            body = await _read_limited_body(request, limits.max_request_bytes)
            if body is None:
                return _json_response(rpc_error(None, RPC_INVALID_REQUEST, "Request body too large"), status=413)
        try:
            payload = json.loads(body or b"null")
        except json.JSONDecodeError:
            return _json_response(rpc_error(None, RPC_PARSE_ERROR, "Parse error"), status=400)
        if not isinstance(payload, dict):
            return _json_response(
                rpc_error(None, RPC_INVALID_REQUEST, "Batch requests are not supported"), status=400
            )
        response = dispatch_rpc(
            service,
            payload,
            scopes=_scopes(request, provider),
            protocol_version=LEGACY_PROTOCOL_VERSION,
        )
        if response is None:
            return Response(status_code=202)
        return _json_response(response)

    @app.post("/mcp")
    async def mcp_post(request: Request) -> Response:
        if not _origin_allowed(request.headers.get("origin"), allowed_origins):
            return _json_response(rpc_error(None, RPC_INVALID_REQUEST, "Origin not allowed"), status=403)
        accept = request.headers.get("accept", "")
        session_header = request.headers.get(MCP_SESSION_HEADER)
        content_type = request.headers.get("content-type", "")
        if content_type and "application/json" not in content_type:
            return _json_response(
                rpc_error(None, RPC_INVALID_REQUEST, "Content-Type must be application/json"), status=415
            )
        if accept and not (
            _accepts(accept, JSON_CONTENT_TYPE) or _accepts(accept, SSE_CONTENT_TYPE)
        ):
            return _json_response(
                rpc_error(None, RPC_INVALID_REQUEST, "Accept must include application/json or text/event-stream"),
                status=406,
            )
        body = await _read_limited_body(request, limits.max_request_bytes)
        if body is None:
            return _json_response(rpc_error(None, RPC_INVALID_REQUEST, "Request body too large"), status=413)
        # Compatibility path: pre-spec clients POST bare JSON-RPC without an
        # SSE-capable Accept header and without sessions.
        if SSE_CONTENT_TYPE not in accept and session_header is None:
            return await handle_legacy(request, body)
        try:
            payload = json.loads(body or b"null")
        except json.JSONDecodeError:
            return _json_response(rpc_error(None, RPC_PARSE_ERROR, "Parse error"), status=400)
        if not isinstance(payload, dict):
            return _json_response(
                rpc_error(None, RPC_INVALID_REQUEST, "Batch requests are not supported"), status=400
            )
        method = payload.get("method")
        is_initialize = method == "initialize"
        wants_sse = SSE_CONTENT_TYPE in accept and JSON_CONTENT_TYPE not in accept

        requested_version = request.headers.get(MCP_PROTOCOL_HEADER)
        session: MCPSession | None = None
        if session_header and not is_initialize:
            session = registry.get(session_header)
            if session is None:
                return _json_response(rpc_error(None, RPC_INVALID_REQUEST, "Session not found"), status=404)
            subject, _ = _subject(request, provider)
            if session.subject != subject:
                logger.warning("mcp: session %s presented by a different subject", session_header[:8])
                return _json_response(rpc_error(None, RPC_INVALID_REQUEST, "Session not found"), status=404)
            if requested_version and requested_version not in SUPPORTED_PROTOCOL_VERSIONS:
                return _json_response(
                    rpc_error(
                        None,
                        RPC_INVALID_REQUEST,
                        f"Unsupported MCP-Protocol-Version {requested_version!r}",
                        {"supported": list(SUPPORTED_PROTOCOL_VERSIONS)},
                    ),
                    status=400,
                )
        elif not is_initialize:
            if method == "server/discover":
                # Modern MCP clients probe `server/discover` first; a method
                # error tells them to fall back to the initialize handshake.
                return _json_response(
                    rpc_error(payload.get("id"), RPC_METHOD_NOT_FOUND, "Method 'server/discover' not found")
                )
            if "id" in payload:
                return _json_response(
                    rpc_error(
                        payload.get("id"),
                        RPC_INVALID_REQUEST,
                        f"Missing {MCP_SESSION_HEADER} header; send initialize first",
                    ),
                    status=400,
                )
            return Response(status_code=202)

        scopes = _scopes(request, provider)
        body_version = None
        if is_initialize and isinstance(payload.get("params"), dict):
            body_version = payload["params"].get("protocolVersion")
        protocol_version = negotiate_protocol_version(body_version or requested_version)
        if is_initialize:
            subject, client_id = _subject(request, provider)
            try:
                session = registry.create(
                    protocol_version=protocol_version,
                    subject=subject,
                    client_id=client_id,
                    scopes=scopes or frozenset(),
                )
            except ToolError as exc:
                return _json_response(rpc_error(payload.get("id"), RPC_INTERNAL_ERROR, str(exc)), status=503)
            logger.info("mcp: initialize from subject=%s", subject)
            response_payload = dispatch_rpc(
                service, payload, scopes=scopes, protocol_version=protocol_version
            )
            if response_payload is None:
                return Response(status_code=202, headers={MCP_SESSION_HEADER: session.session_id})
            if wants_sse:
                return _sse_response(response_payload, session_id=session.session_id)
            return _json_response(response_payload, session_id=session.session_id)

        assert session is not None
        try:
            response_payload = dispatch_rpc(
                service,
                payload,
                scopes=scopes,
                protocol_version=session.protocol_version,
            )
        except Exception:
            logger.exception("mcp: dispatch failed")
            response_payload = rpc_error(payload.get("id"), RPC_INTERNAL_ERROR, "Internal error")
        if response_payload is None:
            return Response(status_code=202, headers={MCP_SESSION_HEADER: session.session_id})
        if wants_sse:
            return _sse_response(response_payload, session_id=session.session_id)
        return _json_response(response_payload, session_id=session.session_id)

    @app.get("/mcp")
    async def mcp_get(request: Request) -> Response:
        if not _origin_allowed(request.headers.get("origin"), allowed_origins):
            return _json_response(rpc_error(None, RPC_INVALID_REQUEST, "Origin not allowed"), status=403)
        accept = request.headers.get("accept", "")
        if accept and not _accepts(accept, SSE_CONTENT_TYPE):
            return _json_response(
                rpc_error(None, RPC_INVALID_REQUEST, "Accept must include text/event-stream"), status=406
            )
        session_id = request.headers.get(MCP_SESSION_HEADER)
        session = registry.get(session_id)
        if session is None:
            return _json_response(rpc_error(None, RPC_INVALID_REQUEST, "Session not found"), status=404)
        subject, _ = _subject(request, provider)
        if session.subject != subject:
            return _json_response(rpc_error(None, RPC_INVALID_REQUEST, "Session not found"), status=404)

        async def events():
            while True:
                if registry.get(session_id) is None:
                    break
                try:
                    event = await asyncio.wait_for(
                        session.events.get(), timeout=limits.ping_interval
                    )
                except TimeoutError:
                    # EventSourceResponse emits its own keepalive comments; the
                    # timeout only re-checks whether the session still exists.
                    continue
                yield {"event": "message", "data": json.dumps(event, ensure_ascii=False)}

        return EventSourceResponse(
            events(),
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                MCP_SESSION_HEADER: session.session_id,
            },
            ping=limits.ping_interval,
        )

    @app.delete("/mcp")
    async def mcp_delete(request: Request) -> Response:
        if not _origin_allowed(request.headers.get("origin"), allowed_origins):
            return _json_response(rpc_error(None, RPC_INVALID_REQUEST, "Origin not allowed"), status=403)
        session_id = request.headers.get(MCP_SESSION_HEADER)
        session = registry.get(session_id)
        if session is None:
            return _json_response(rpc_error(None, RPC_INVALID_REQUEST, "Session not found"), status=404)
        subject, _ = _subject(request, provider)
        if session.subject != subject:
            return _json_response(rpc_error(None, RPC_INVALID_REQUEST, "Session not found"), status=404)
        registry.delete(session.session_id)
        logger.info("mcp: session %s terminated by client", session.session_id[:8])
        return Response(status_code=204, headers={MCP_SESSION_HEADER: session.session_id})

    for path in legacy_paths:
        if path == "/mcp":
            continue
        app.add_api_route(path, handle_legacy, methods=["POST"], include_in_schema=False)


def runtime_fingerprint(runtime: Any | None) -> dict[str, Any]:
    """Stable diagnostics describing the shared runtime (used by /api/v1/runtime/stats).

    Deliberately does not touch ``runtime.base_strategy``: reporting stats must
    never trigger the lazy strategy/vector-store construction it reports on.
    """
    if runtime is None:
        return {"loaded": False}
    strategy = getattr(runtime, "_base_strategy", None)
    vector_store = getattr(runtime, "_vector_store", None)
    return {
        "loaded": True,
        "runtime_id": f"0x{id(runtime):x}",
        "runtime_type": type(runtime).__name__,
        "strategy": type(strategy).__name__ if strategy is not None else None,
        "vector_store": type(vector_store).__name__ if vector_store is not None else None,
    }


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
