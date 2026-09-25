"""Client wrapper for interacting with remote Code Diver instances (HTTP or gRPC)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Generator

import httpx2
import grpc

from .grpc_gen import code_diver_pb2, code_diver_pb2_grpc


class RemoteCodeDiverClient:
    """Unified client for remote Code Diver operations (Search, Grep, Tree, Remote Indexing)."""

    def __init__(
        self,
        http_url: str | None = "http://127.0.0.1:8080",
        grpc_addr: str | None = None,
    ) -> None:
        self.http_url = http_url.rstrip("/") if http_url else None
        self.grpc_addr = grpc_addr
        self._grpc_channel: grpc.Channel | None = None
        self._grpc_stub: code_diver_pb2_grpc.CodeDiverServiceStub | None = None

    def _get_grpc_stub(self) -> code_diver_pb2_grpc.CodeDiverServiceStub:
        if self._grpc_stub is None:
            if not self.grpc_addr:
                raise ValueError("gRPC address not specified")
            self._grpc_channel = grpc.insecure_channel(self.grpc_addr)
            self._grpc_stub = code_diver_pb2_grpc.CodeDiverServiceStub(self._grpc_channel)
        return self._grpc_stub

    def close(self) -> None:
        if self._grpc_channel:
            self._grpc_channel.close()

    # --- HTTP Operations ---
    def trigger_remote_index_http(
        self, repo_path: str | None = None, clear_existing: bool = False
    ) -> dict[str, Any]:
        if not self.http_url:
            raise ValueError("HTTP URL not configured")
        with httpx2.Client() as client:
            resp = client.post(
                f"{self.http_url}/api/v1/index/trigger",
                json={"repo_path": repo_path, "clear_existing": clear_existing},
            )
            resp.raise_for_status()
            return resp.json()

    def ingest_files_http(self, files: list[dict[str, str]]) -> dict[str, Any]:
        if not self.http_url:
            raise ValueError("HTTP URL not configured")
        with httpx2.Client() as client:
            resp = client.post(
                f"{self.http_url}/api/v1/index/ingest",
                json={"files": files},
            )
            resp.raise_for_status()
            return resp.json()

    # --- gRPC Operations ---
    def trigger_index_grpc(
        self,
        repo_path: str = "",
        clear_existing: bool = False,
        build_graph: bool = True,
    ) -> Generator[code_diver_pb2.IndexProgressUpdate, None, None]:
        stub = self._get_grpc_stub()
        req = code_diver_pb2.IndexRequest(
            repo_path=repo_path,
            clear_existing=clear_existing,
            build_graph=build_graph,
        )
        for update in stub.TriggerIndex(req):
            yield update

    def ingest_files_grpc(
        self,
        files: list[tuple[str, bytes]],
    ) -> code_diver_pb2.IngestSummary:
        stub = self._get_grpc_stub()

        def request_generator():
            for path, content in files:
                yield code_diver_pb2.IngestFileChunk(
                    path=path,
                    content=content,
                    is_last_chunk=True,
                )

        return stub.IngestFiles(request_generator())
