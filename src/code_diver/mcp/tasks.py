"""Background task manager for asynchronous MCP operations."""

from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
import time
from typing import Any, Callable
import uuid


@dataclass
class BackgroundTask:
    task_id: str
    name: str
    status: str  # "working", "completed", "failed", "cancelled"
    created_at: str
    updated_at: str
    poll_interval_ms: int = 1000
    status_message: str = "Task queued"
    result: Any | None = None
    error: str | None = None
    future: concurrent.futures.Future[Any] | None = None


class BackgroundTaskManager:
    """In-memory background job tracker for asynchronous MCP tools."""

    def __init__(self, max_workers: int = 4) -> None:
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self.tasks: dict[str, BackgroundTask] = {}
        self._lock = threading.Lock()

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def submit_task(
        self,
        name: str,
        fn: Callable[[], Any],
        poll_interval_ms: int = 1000,
    ) -> dict[str, Any]:
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        now = self._now_iso()

        task = BackgroundTask(
            task_id=task_id,
            name=name,
            status="working",
            created_at=now,
            updated_at=now,
            poll_interval_ms=poll_interval_ms,
            status_message="Task running",
        )

        def _runner() -> None:
            try:
                res = fn()
                with self._lock:
                    task.status = "completed"
                    task.status_message = "Task completed successfully"
                    task.result = res
                    task.updated_at = self._now_iso()
            except Exception as e:
                with self._lock:
                    task.status = "failed"
                    task.status_message = f"Task failed: {e}"
                    task.error = str(e)
                    task.updated_at = self._now_iso()

        with self._lock:
            fut = self.executor.submit(_runner)
            task.future = fut
            self.tasks[task_id] = task

        return {
            "task_id": task_id,
            "status": "working",
            "poll_interval_ms": poll_interval_ms,
            "created_at": now,
        }

    def get_status(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return {
                    "task_id": task_id,
                    "status": "not_found",
                    "error": f"Unknown task_id: {task_id}",
                }
            return {
                "task_id": task.task_id,
                "name": task.name,
                "status": task.status,
                "status_message": task.status_message,
                "created_at": task.created_at,
                "updated_at": task.updated_at,
            }

    def get_result(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return {
                    "task_id": task_id,
                    "status": "not_found",
                    "error": f"Unknown task_id: {task_id}",
                }
            if task.status == "working":
                return {
                    "task_id": task_id,
                    "status": "working",
                    "poll_interval_ms": task.poll_interval_ms,
                    "message": "Task is still running. Please poll again shortly.",
                }
            return {
                "task_id": task.task_id,
                "status": task.status,
                "result": task.result,
                "error": task.error,
                "completed_at": task.updated_at,
            }

    def cancel_task(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return {
                    "task_id": task_id,
                    "status": "not_found",
                    "error": f"Unknown task_id: {task_id}",
                }
            if task.status == "working":
                if task.future and not task.future.done():
                    task.future.cancel()
                task.status = "cancelled"
                task.status_message = "Task cancelled by client"
                task.updated_at = self._now_iso()
            return {
                "task_id": task.task_id,
                "status": task.status,
                "status_message": task.status_message,
            }

    def list_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            sorted_tasks = sorted(
                self.tasks.values(),
                key=lambda t: t.created_at,
                reverse=True,
            )
            return [
                {
                    "task_id": t.task_id,
                    "name": t.name,
                    "status": t.status,
                    "status_message": t.status_message,
                    "created_at": t.created_at,
                    "updated_at": t.updated_at,
                }
                for t in sorted_tasks[:limit]
            ]
