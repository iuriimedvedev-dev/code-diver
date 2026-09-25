"""Agent Client Protocol (ACP) Server implementation for Code Diver.

Connects editors (like Zed) with Code Diver's deep code retrieval and
exploration pipeline via JSON-RPC 2.0 over standard I/O (stdio).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import sys
import threading
import traceback
from typing import Any, Callable
import uuid

from ..config import ConfigLoader
from ..inspection.grep_service import GrepService
from ..inspection.info_service import InfoService
from ..inspection.read_excerpt_service import ReadExcerptService
from ..inspection.symbols_service import SymbolsService
from ..inspection.tree_service import TreeService
from ..runtime.search_runtime import SearchRuntime

logger = logging.getLogger("code_diver.acp")


class AcpServer:
    """ACP v1 Agent Server running over JSON-RPC 2.0 stdio."""

    def __init__(self, config_path: Path | str = "code-diver.yml") -> None:
        self.config_path = Path(config_path).expanduser()
        self._config: Any = None
        self._runtime: SearchRuntime | None = None
        self._sessions: dict[str, dict[str, Any]] = {}
        self._active_turns: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._running = False

    def get_runtime(self) -> tuple[Any, SearchRuntime]:
        with self._lock:
            if self._runtime is None:
                resolved = self.config_path if self.config_path.exists() else Path("code-diver.yml")
                self._config = ConfigLoader().load(resolved)
                self._runtime = SearchRuntime(self._config)
            return self._config, self._runtime

    def send_response(self, req_id: Any, result: Any = None, error: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id}
        if error is not None:
            payload["error"] = error
        else:
            payload["result"] = result if result is not None else {}
        self._write_message(payload)

    def send_notification(self, method: str, params: dict[str, Any]) -> None:
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        self._write_message(payload)

    def _write_message(self, payload: dict[str, Any]) -> None:
        line = json.dumps(payload, ensure_ascii=False)
        sys.stdout.write(line + "\n")
        sys.stdout.flush()

    def handle_initialize(self, req_id: Any, params: dict[str, Any]) -> None:
        """Handle ACP initialize method."""
        client_version = params.get("protocolVersion", 1)
        # ACP v1 protocol
        negotiated_version = 1 if client_version >= 1 else client_version

        result = {
            "protocolVersion": negotiated_version,
            "agentCapabilities": {
                "loadSession": False,
                "promptCapabilities": {
                    "image": False,
                    "audio": False,
                    "embeddedContext": True,
                },
                "mcpCapabilities": {
                    "http": False,
                    "sse": False,
                },
            },
            "agentInfo": {
                "name": "code-diver",
                "title": "Code Diver Exploration Agent",
                "version": "0.4.2",
            },
            "authMethods": [],
        }
        self.send_response(req_id, result)

    def handle_session_new(self, req_id: Any, params: dict[str, Any]) -> None:
        """Handle session/new request."""
        cwd = params.get("cwd", str(Path.cwd()))
        mcp_servers = params.get("mcpServers", [])
        session_id = f"sess_{uuid.uuid4().hex[:12]}"

        with self._lock:
            self._sessions[session_id] = {
                "cwd": cwd,
                "mcpServers": mcp_servers,
                "history": [],
            }

        self.send_response(req_id, {"sessionId": session_id})

    def handle_session_prompt(self, req_id: Any, params: dict[str, Any]) -> None:
        """Handle session/prompt request."""
        session_id = params.get("sessionId")
        if not session_id or session_id not in self._sessions:
            self.send_response(
                req_id,
                error={"code": -32602, "message": f"Session '{session_id}' not found."},
            )
            return

        prompt_blocks = params.get("prompt", [])
        cancel_event = threading.Event()
        with self._lock:
            self._active_turns[session_id] = cancel_event

        thread = threading.Thread(
            target=self._execute_prompt_turn,
            args=(req_id, session_id, prompt_blocks, cancel_event),
            daemon=True,
        )
        thread.start()

    def handle_session_cancel(self, params: dict[str, Any]) -> None:
        """Handle session/cancel notification."""
        session_id = params.get("sessionId")
        if session_id and session_id in self._active_turns:
            self._active_turns[session_id].set()

    def _execute_prompt_turn(
        self,
        req_id: Any,
        session_id: str,
        prompt_blocks: list[dict[str, Any]],
        cancel_event: threading.Event,
    ) -> None:
        try:
            # Extract query text from blocks
            query_texts = []
            for b in prompt_blocks:
                b_type = b.get("type")
                if b_type == "text":
                    query_texts.append(b.get("text", ""))
                elif b_type == "resource":
                    res = b.get("resource", {})
                    t = res.get("text")
                    if t:
                        query_texts.append(t)

            query = " ".join(t.strip() for t in query_texts if t.strip())
            if not query:
                self.send_response(req_id, {"stopReason": "end_turn"})
                return

            # Emit initial plan update
            self.send_notification(
                "session/update",
                {
                    "sessionId": session_id,
                    "update": {
                        "sessionUpdate": "plan",
                        "entries": [
                            {
                                "content": f"Search and analyze code for: {query[:60]}",
                                "priority": "high",
                                "status": "in_progress",
                            }
                        ],
                    },
                },
            )

            if cancel_event.is_set():
                self.send_response(req_id, {"stopReason": "cancelled"})
                return

            # Tool call: search
            tool_call_id = f"call_{uuid.uuid4().hex[:8]}"
            self.send_notification(
                "session/update",
                {
                    "sessionId": session_id,
                    "update": {
                        "sessionUpdate": "tool_call",
                        "toolCallId": tool_call_id,
                        "name": "code_diver_search",
                        "title": f"Retrieving relevant code chunks for '{query[:40]}...'",
                        "kind": "search",
                        "status": "in_progress",
                    },
                },
            )

            config, runtime = self.get_runtime()
            results = runtime.base_strategy.search(query=query, limit=10)

            if cancel_event.is_set():
                self.send_notification(
                    "session/update",
                    {
                        "sessionId": session_id,
                        "update": {
                            "sessionUpdate": "tool_call_update",
                            "toolCallId": tool_call_id,
                            "status": "failed",
                        },
                    },
                )
                self.send_response(req_id, {"stopReason": "cancelled"})
                return

            formatted_locations = []
            for r in results:
                formatted_locations.append(
                    {
                        "path": str(Path(config.root) / r.item.path),
                        "line": r.item.start_line,
                    }
                )

            search_summary = f"Found {len(results)} relevant code chunks across {len(set(r.item.path for r in results))} files."

            self.send_notification(
                "session/update",
                {
                    "sessionId": session_id,
                    "update": {
                        "sessionUpdate": "tool_call_update",
                        "toolCallId": tool_call_id,
                        "status": "completed",
                        "locations": formatted_locations,
                        "content": [
                            {
                                "type": "content",
                                "content": {
                                    "type": "text",
                                    "text": search_summary,
                                },
                            }
                        ],
                    },
                },
            )

            # Stream Agent response message
            message_id = f"msg_{uuid.uuid4().hex[:8]}"
            header_chunk = f"### Code Diver Retrieval Results\n\nI found {len(results)} relevant code locations for your query:\n\n"
            self.send_notification(
                "session/update",
                {
                    "sessionId": session_id,
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "messageId": message_id,
                        "content": {"type": "text", "text": header_chunk},
                    },
                },
            )

            for i, r in enumerate(results, 1):
                if cancel_event.is_set():
                    self.send_response(req_id, {"stopReason": "cancelled"})
                    return

                item_chunk = (
                    f"**{i}. `{r.item.path}` (lines {r.item.start_line}-{r.item.end_line})** — score: `{r.score:.3f}`\n"
                    f"*{r.item.title}*\n"
                    f"```\n{r.item.content[:250].strip()}\n```\n\n"
                )
                self.send_notification(
                    "session/update",
                    {
                        "sessionId": session_id,
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "messageId": message_id,
                            "content": {"type": "text", "text": item_chunk},
                        },
                    },
                )

            # Update plan to completed
            self.send_notification(
                "session/update",
                {
                    "sessionId": session_id,
                    "update": {
                        "sessionUpdate": "plan",
                        "entries": [
                            {
                                "content": f"Search and analyze code for: {query[:60]}",
                                "priority": "high",
                                "status": "completed",
                            }
                        ],
                    },
                },
            )

            self.send_response(req_id, {"stopReason": "end_turn"})
        except Exception as e:
            logger.error("Error executing prompt turn: %s", traceback.format_exc())
            self.send_response(
                req_id,
                error={"code": -32603, "message": f"Internal agent error: {e}"},
            )
        finally:
            with self._lock:
                self._active_turns.pop(session_id, None)

    def process_message(self, raw_line: str) -> None:
        """Process incoming JSON-RPC line."""
        line = raw_line.strip()
        if not line:
            return

        try:
            msg = json.loads(line)
        except Exception as e:
            self.send_response(
                None,
                error={"code": -32700, "message": f"Parse error: {e}"},
            )
            return

        method = msg.get("method")
        req_id = msg.get("id")
        params = msg.get("params", {})

        if method == "initialize":
            self.handle_initialize(req_id, params)
        elif method == "session/new":
            self.handle_session_new(req_id, params)
        elif method == "session/prompt":
            self.handle_session_prompt(req_id, params)
        elif method == "session/cancel":
            self.handle_session_cancel(params)
        elif method == "session/close":
            session_id = params.get("sessionId")
            with self._lock:
                self._sessions.pop(session_id, None)
            if req_id is not None:
                self.send_response(req_id, {})
        else:
            if req_id is not None:
                self.send_response(
                    req_id,
                    error={"code": -32601, "message": f"Method '{method}' not found"},
                )

    def run_stdio(self) -> None:
        """Run the ACP server loop over standard input."""
        self._running = True
        try:
            for line in sys.stdin:
                if not self._running:
                    break
                self.process_message(line)
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            self._running = False
