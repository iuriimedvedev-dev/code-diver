"""MCP Server for Code Diver search, inspection and retrieval."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from ..config import ConfigLoader
from ..inspection.grep_service import GrepService
from ..inspection.info_service import InfoService
from ..inspection.read_excerpt_service import ReadExcerptService
from ..inspection.rg_service import RgService
from ..inspection.symbols_service import SymbolsService
from ..inspection.tree_service import TreeService
from ..runtime.search_runtime import SearchRuntime
from .tasks import BackgroundTaskManager


def create_mcp_server(config_path: Path | str = "code-diver.yml") -> MCPServer:
    """Create and configure the Code Diver MCP server."""
    server = MCPServer("code-diver")
    cfg_path = Path(config_path).expanduser()
    task_manager = BackgroundTaskManager(max_workers=4)

    _config = None
    _runtime = None

    def get_runtime() -> tuple[Any, SearchRuntime]:
        nonlocal _config, _runtime
        if _runtime is None:
            resolved_cfg = cfg_path if cfg_path.exists() else Path("code-diver.yml")
            _config = ConfigLoader().load(resolved_cfg)
            _runtime = SearchRuntime(_config)
        return _config, _runtime

    @server.tool(
        name="code_diver_search",
        description="Search repository code using neural and hybrid retrieval.",
    )
    def search(query: str, limit: int = 10) -> str:
        """Search code items by semantic query."""
        _, runtime = get_runtime()
        results = runtime.base_strategy.search(query=query, limit=limit)
        items = []
        for r in results:
            items.append(
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
            )
        return json.dumps(items, ensure_ascii=False, indent=2)

    @server.tool(
        name="code_diver_info",
        description="Get Code Diver index, vector store, graph, and model footprint statistics.",
    )
    def info() -> str:
        """Get repository index and model metadata."""
        config, _ = get_runtime()
        data = InfoService(config).get_info().to_dict()
        return json.dumps(data, ensure_ascii=False, indent=2)

    @server.tool(
        name="code_diver_read",
        description="Read a bounded excerpt of lines from a project file.",
    )
    def read_file(file: str, start_line: int = 1, lines: int = 100) -> str:
        """Read file excerpt."""
        config, _ = get_runtime()
        return ReadExcerptService(config.root).read(file=file, start_line=start_line, lines=lines)

    @server.tool(
        name="code_diver_grep",
        description="Search literal text or regex patterns across the codebase.",
    )
    def grep(pattern: str, path: str | None = None, limit: int = 50, regex: bool = False) -> str:
        """Grep codebase."""
        config, _ = get_runtime()
        matches = GrepService(config.root).search(pattern=pattern, path=path, limit=limit, regex=regex)
        return json.dumps(
            [{"path": m.path, "line": m.line, "text": m.text} for m in matches],
            ensure_ascii=False,
            indent=2,
        )

    @server.tool(
        name="code_diver_symbols",
        description="List AST parsed source symbols (classes, methods, functions) for a file or repo.",
    )
    def symbols(path: str | None = None, limit: int = 100) -> str:
        """List symbols."""
        config, _ = get_runtime()
        syms = SymbolsService(config.root).list_symbols(path=path, limit=limit)
        return json.dumps(
            [
                {
                    "name": s.name,
                    "kind": s.kind,
                    "path": s.path,
                    "start_line": s.start_line,
                    "end_line": s.end_line,
                }
                for s in syms
            ],
            ensure_ascii=False,
            indent=2,
        )

    @server.tool(
        name="code_diver_tree",
        description="Print a gitignore-aware directory tree of the repository.",
    )
    def tree(path: str | None = None, depth: int = 3, limit: int = 100) -> str:
        """Print tree."""
        config, _ = get_runtime()
        return TreeService(config.root).render(path=path, max_depth=depth, limit=limit)

    # -------------------------------------------------------------------------
    # Asynchronous MCP Agent Search & Task Management
    # -------------------------------------------------------------------------

    @server.tool(
        name="code_diver_submit_agent_search",
        description=(
            "Submit a background search or deep exploration task to run asynchronously. "
            "Returns a task handle with task_id immediately. "
            "Poll code_diver_task_status until completed, then fetch code_diver_task_result."
        ),
    )
    def submit_agent_search(
        query: str,
        limit: int = 10,
        mode: str = "hybrid",
        include_symbols: bool = True,
    ) -> str:
        """Submit background search task."""
        def _execute() -> dict[str, Any]:
            config, runtime = get_runtime()
            results = runtime.base_strategy.search(query=query, limit=limit)
            items = []
            for r in results:
                item_dict: dict[str, Any] = {
                    "path": r.item.path,
                    "score": round(float(r.score), 4),
                    "start_line": r.item.start_line,
                    "end_line": r.item.end_line,
                    "title": r.item.title,
                    "content_preview": (
                        r.item.content[:400] + "..." if len(r.item.content) > 400 else r.item.content
                    ),
                }
                if include_symbols:
                    try:
                        syms = SymbolsService(config.root).list_symbols(path=r.item.path, limit=20)
                        item_dict["file_symbols"] = [s.name for s in syms]
                    except Exception:
                        item_dict["file_symbols"] = []
                items.append(item_dict)
            return {
                "query": query,
                "mode": mode,
                "total_results": len(items),
                "items": items,
            }

        task_info = task_manager.submit_task(
            name=f"agent_search: {query[:60]}",
            fn=_execute,
            poll_interval_ms=500,
        )
        return json.dumps(task_info, ensure_ascii=False, indent=2)

    @server.tool(
        name="code_diver_task_status",
        description="Check status of a background task. Status: 'working' | 'completed' | 'failed' | 'cancelled'.",
    )
    def task_status(task_id: str) -> str:
        """Get status of an asynchronous task."""
        st = task_manager.get_status(task_id)
        return json.dumps(st, ensure_ascii=False, indent=2)

    @server.tool(
        name="code_diver_task_result",
        description="Fetch result payload of a completed background task.",
    )
    def task_result(task_id: str) -> str:
        """Get result of an asynchronous task."""
        res = task_manager.get_result(task_id)
        return json.dumps(res, ensure_ascii=False, indent=2)

    @server.tool(
        name="code_diver_task_cancel",
        description="Cancel a running background task.",
    )
    def task_cancel(task_id: str) -> str:
        """Cancel an asynchronous task."""
        res = task_manager.cancel_task(task_id)
        return json.dumps(res, ensure_ascii=False, indent=2)

    @server.tool(
        name="code_diver_tasks_list",
        description="List recent background tasks tracked by Code Diver.",
    )
    def tasks_list(limit: int = 20) -> str:
        """List background tasks."""
        tasks = task_manager.list_tasks(limit=limit)
        return json.dumps(tasks, ensure_ascii=False, indent=2)

    return server


def main() -> None:
    """CLI entrypoint for running the MCP server over stdio."""
    import sys

    config_path = sys.argv[1] if len(sys.argv) > 1 else "code-diver.yml"
    server = create_mcp_server(config_path)
    server.run("stdio")


if __name__ == "__main__":
    main()
