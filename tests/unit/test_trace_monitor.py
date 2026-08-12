from __future__ import annotations

import json
import os

import pytest

from code_diver.ui.trace_monitor import TraceMonitor

pytestmark = pytest.mark.unit


def test_trace_monitor_resets_offset_when_trace_file_is_truncated(tmp_path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    first = {"timestamp": "2026-06-02T00:00:00+00:00", "event": "first", "payload": {"padding": "x" * 200}}
    second = {"timestamp": "2026-06-02T00:00:01+00:00", "event": "second", "payload": {}}
    trace_path.write_text(json.dumps(first) + "\n", encoding="utf-8")
    monitor = TraceMonitor(trace_path)

    monitor._read_new_events()
    assert [event["event"] for event in monitor._events] == ["first"]

    trace_path.write_text(json.dumps(second) + "\n", encoding="utf-8")
    monitor._read_new_events()

    assert [event["event"] for event in monitor._events] == ["second"]
    assert monitor._counts == {"second": 1}


def test_trace_monitor_resets_when_trace_file_is_replaced_with_larger_file(tmp_path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    first = {"timestamp": "2026-06-02T00:00:00+00:00", "event": "first", "payload": {"padding": "x" * 200}}
    second = {"timestamp": "2026-06-02T00:00:01+00:00", "event": "second", "payload": {"padding": "y" * 400}}
    trace_path.write_text(json.dumps(first) + "\n", encoding="utf-8")
    monitor = TraceMonitor(trace_path)

    monitor._read_new_events()
    replacement_path = tmp_path / "replacement.jsonl"
    replacement_path.write_text(json.dumps(second) + "\n", encoding="utf-8")
    os.replace(replacement_path, trace_path)
    monitor._read_new_events()

    assert [event["event"] for event in monitor._events] == ["second"]
    assert monitor._counts == {"second": 1}
