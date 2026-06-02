from __future__ import annotations

import json
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


@dataclass(slots=True)
class TraceMonitor:
    trace_path: Path
    refresh_seconds: float = 0.5
    max_events: int = 200
    _offset: int = 0
    _events: deque[dict[str, Any]] = field(default_factory=deque, init=False)
    _counts: Counter[str] = field(default_factory=Counter, init=False)
    _file_identity: tuple[int, int] | None = field(default=None, init=False)
    _file_mtime_ns: int | None = field(default=None, init=False)

    def run(self) -> None:
        with Live(self._render(), refresh_per_second=max(1, int(1 / max(self.refresh_seconds, 0.1)))) as live:
            while True:
                self._read_new_events()
                live.update(self._render())
                time.sleep(self.refresh_seconds)

    def _read_new_events(self) -> None:
        if not self.trace_path.exists():
            return
        try:
            stat = self.trace_path.stat()
        except OSError:
            return
        current_identity = (stat.st_dev, stat.st_ino)
        if self._file_identity is None:
            self._file_identity = current_identity
            self._file_mtime_ns = stat.st_mtime_ns
        elif (
            current_identity != self._file_identity
            or stat.st_size < self._offset
            or (stat.st_size <= self._offset and stat.st_mtime_ns != self._file_mtime_ns)
        ):
            self._reset_reader(current_identity)
        with self.trace_path.open("r", encoding="utf-8") as stream:
            stream.seek(self._offset)
            for line in stream:
                record = self._parse(line)
                if record is None:
                    continue
                self._events.append(record)
                self._counts[str(record.get("event", "unknown"))] += 1
                while len(self._events) > self.max_events:
                    self._events.popleft()
            self._offset = stream.tell()
            self._file_mtime_ns = stat.st_mtime_ns

    def _reset_reader(self, file_identity: tuple[int, int]) -> None:
        self._file_identity = file_identity
        self._file_mtime_ns = None
        self._offset = 0
        self._events.clear()
        self._counts.clear()

    def _parse(self, line: str) -> dict[str, Any] | None:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            return None
        return record if isinstance(record, dict) else None

    def _render(self):
        header = Text()
        header.append("code-diver monitor", style="bold bright_cyan")
        header.append("  ")
        header.append(str(self.trace_path), style="bright_magenta")

        counts = Table.grid(expand=True)
        counts.add_column(ratio=1)
        counts.add_column(ratio=1)
        counts.add_column(ratio=1)
        counts.add_row(
            self._metric("events", sum(self._counts.values()), "bright_green"),
            self._metric("kinds", len(self._counts), "bright_blue"),
            self._metric("shown", len(self._events), "bright_magenta"),
        )
        if not self.trace_path.exists():
            waiting = Text("waiting for trace file", style="bold yellow")
            waiting.append(" ")
            waiting.append(str(self.trace_path), style="bright_magenta")
            return Group(
                Panel(Group(header, counts), border_style="bright_blue"),
                Panel(waiting, title="live trace", border_style="yellow"),
            )

        event_table = Table(expand=True, show_header=True, header_style="bold bright_cyan")
        event_table.add_column("time", width=18, overflow="fold")
        event_table.add_column("event", width=32, overflow="fold")
        event_table.add_column("summary", overflow="fold")
        for record in list(self._events)[-24:]:
            event = str(record.get("event", "unknown"))
            event_table.add_row(
                self._short_time(str(record.get("timestamp", ""))),
                Text(event, style=self._event_style(event)),
                self._payload_summary(record.get("payload")),
            )

        top = Table(expand=True, show_header=True, header_style="bold bright_cyan")
        top.add_column("event")
        top.add_column("count", justify="right")
        for event, count in self._counts.most_common(10):
            top.add_row(Text(event, style=self._event_style(event)), str(count))

        return Group(
            Panel(Group(header, counts), border_style="bright_blue"),
            Panel(event_table, title="live trace", border_style="bright_magenta"),
            Panel(top, title="event counts", border_style="bright_green"),
        )

    def _metric(self, label: str, value: int, style: str) -> Text:
        text = Text()
        text.append(label, style="dim")
        text.append(" ")
        text.append(str(value), style=f"bold {style}")
        return text

    def _short_time(self, timestamp: str) -> str:
        if "T" in timestamp:
            return timestamp.split("T", 1)[1].split(".", 1)[0]
        return timestamp[-18:]

    def _payload_summary(self, payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""
        preferred = [
            "query",
            "root",
            "indexed_items",
            "vectors",
            "provider",
            "model",
            "embedding_batch_size",
            "embedding_workers",
            "route",
            "strategy",
            "tool",
            "path",
            "error",
        ]
        parts: list[str] = []
        for key in preferred:
            if key not in payload:
                continue
            value = str(payload[key]).replace("\n", " ")
            if len(value) > 90:
                value = value[:87].rstrip() + "..."
            parts.append(f"{key}={value}")
        if parts:
            return " | ".join(parts)
        compact = json.dumps(payload, ensure_ascii=False, default=str)
        return compact[:180].rstrip() + ("..." if len(compact) > 180 else "")

    def _event_style(self, event: str) -> str:
        if "error" in event or "failed" in event:
            return "bold red"
        if "rank" in event or "search" in event:
            return "bright_magenta"
        if "tool" in event:
            return "bright_yellow"
        if "index" in event or "vector" in event:
            return "bright_green"
        return "bright_blue"
