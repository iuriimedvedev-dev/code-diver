from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_diver.config import AppConfig
from code_diver.config.generation_config import GenerationConfig
from code_diver.providers.vertex_batch_jsonl_builder import VertexBatchJsonlBuilder
from code_diver.providers.vertex_batch_test_options import VertexBatchTestOptions
from code_diver.providers.vertex_batch_test_service import VertexBatchTestService


pytestmark = pytest.mark.unit


class FakeUploader:
    def __init__(self) -> None:
        self.uploads: list[tuple[Path, str]] = []

    def upload_file(self, local_path: Path, gcs_uri: str) -> None:
        self.uploads.append((local_path, gcs_uri))


class FakeBatches:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create(self, *, model: str, src: str, config: dict[str, object]):
        self.calls.append({"model": model, "src": src, "config": config})
        return type("FakeJob", (), {"name": "batch-jobs/test", "state": "JOB_STATE_PENDING"})()


class FakeBatchClient:
    def __init__(self, batches: FakeBatches) -> None:
        self.batches = batches


def test_vertex_batch_jsonl_builder_writes_gemini_batch_request(tmp_path: Path) -> None:
    output = tmp_path / "batch.jsonl"

    count = VertexBatchJsonlBuilder().write(output, ["Return JSON"], max_output_tokens=32, temperature=0.0)

    assert count == 1
    line = json.loads(output.read_text(encoding="utf-8"))
    assert line == {
        "request": {
            "contents": [{"role": "user", "parts": [{"text": "Return JSON"}]}],
            "generationConfig": {
                "temperature": 0.0,
                "maxOutputTokens": 32,
                "responseMimeType": "application/json",
            },
        }
    }


def test_vertex_batch_test_service_dry_run_writes_local_jsonl(tmp_path: Path) -> None:
    config = AppConfig(root=tmp_path)
    service = VertexBatchTestService()

    result = service.run(config, VertexBatchTestOptions())

    assert result.status == "dry_run"
    assert result.ok is True
    assert result.model == "gemini-3.1-flash-lite"
    assert result.local_input.exists()
    assert result.request_count == 1


def test_vertex_batch_test_service_submit_uploads_and_creates_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "global")
    uploader = FakeUploader()
    batches = FakeBatches()
    config = AppConfig(
        root=tmp_path,
        generation=GenerationConfig(provider="vertex", model="gemini-test"),
    )
    service = VertexBatchTestService(
        uploader=uploader,
        batch_client_factory=lambda _project, _location: FakeBatchClient(batches),
    )

    result = service.run(config, VertexBatchTestOptions(submit=True, gcs_uri="gs://bucket/code-diver-smoke"))

    assert result.status == "ok"
    assert result.model == "gemini-test"
    assert result.job_name == "batch-jobs/test"
    assert result.gcs_input_uri is not None
    assert result.gcs_input_uri.startswith("gs://bucket/code-diver-smoke/vertex-batch-smoke-")
    assert uploader.uploads == [(result.local_input, result.gcs_input_uri)]
    assert batches.calls[0]["model"] == "gemini-test"
    assert batches.calls[0]["src"] == result.gcs_input_uri
    assert batches.calls[0]["config"]["dest"] == result.gcs_output_uri


def test_vertex_batch_test_service_submit_requires_gcs_prefix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    service = VertexBatchTestService()

    result = service.run(AppConfig(root=tmp_path), VertexBatchTestOptions(submit=True))

    assert result.status == "failed"
    assert "CODE_DIVER_VERTEX_BATCH_GCS_URI" in result.details
