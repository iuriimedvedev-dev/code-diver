"""End-to-end tests for Code Diver remote server and unified client."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time

import httpx2
import pytest

from code_diver.transport.client import RemoteCodeDiverClient


@pytest.fixture(scope="module")
def remote_server():
    """Start `code-diver serve` process on dynamic/test ports."""
    http_port = 18080
    grpc_port = 55051
    cmd = [
        sys.executable,
        "-c",
        f"from code_diver.cli import main; main(['serve', '--http-port', '{http_port}', '--grpc-port', '{grpc_port}', 'code-diver.yml'])",
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Poll /health until server responds
    deadline = time.time() + 15
    healthy = False
    while time.time() < deadline:
        try:
            with httpx2.Client() as client:
                res = client.get(f"http://127.0.0.1:{http_port}/health", timeout=1.0)
                if res.status_code == 200:
                    healthy = True
                    break
        except Exception:
            time.sleep(0.5)

    if not healthy:
        proc.kill()
        out, err = proc.communicate()
        raise RuntimeError(f"Server failed to start:\nstdout: {out}\nstderr: {err}")

    yield {"http_url": f"http://127.0.0.1:{http_port}", "grpc_addr": f"127.0.0.1:{grpc_port}"}

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_e2e_http_health_and_info(remote_server):
    url = remote_server["http_url"]
    with httpx2.Client(timeout=30.0) as client:
        health = client.get(f"{url}/health").json()
        assert health["status"] == "ok"
        assert health["version"] == "0.4.2"

        info = client.get(f"{url}/api/v1/info").json()
        assert isinstance(info, dict)


def test_e2e_remote_client_http_operations(remote_server):
    client = RemoteCodeDiverClient(http_url=remote_server["http_url"])
    try:
        # Ingest files
        res = client.ingest_files_http(
            [
                {"path": "e2e_remote_test.py", "content": "class RemoteE2E: pass\n"}
            ]
        )
        assert res["status"] == "ok"
        assert res["files_received"] == 1

        # Trigger remote index
        trig = client.trigger_remote_index_http(clear_existing=False)
        assert trig["status"] == "triggered"
        assert "task_id" in trig
    finally:
        client.close()


def test_e2e_remote_client_grpc_operations(remote_server):
    client = RemoteCodeDiverClient(
        http_url=remote_server["http_url"],
        grpc_addr=remote_server["grpc_addr"],
    )
    try:
        # Ingest via gRPC
        summary = client.ingest_files_grpc(
            [("e2e_grpc_file.py", b"def grpc_hello(): pass\n")]
        )
        assert summary.status == "ok"
        assert summary.files_received == 1

        # Trigger index streaming
        updates = list(client.trigger_index_grpc(clear_existing=False))
        assert len(updates) > 0
        stages = [u.stage for u in updates]
        assert "init" in stages
    finally:
        client.close()
