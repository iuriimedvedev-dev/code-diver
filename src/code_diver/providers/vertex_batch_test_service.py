from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from ..config import AppConfig
from ..settings import Defaults, EnvironmentVariable
from .gcs_object_uploader import GcsObjectUploader
from .vertex_batch_jsonl_builder import VertexBatchJsonlBuilder
from .vertex_batch_test_options import VertexBatchTestOptions
from .vertex_batch_test_result import VertexBatchTestResult


class VertexBatchTestService:
    def __init__(
        self,
        builder: VertexBatchJsonlBuilder | None = None,
        uploader: GcsObjectUploader | None = None,
        batch_client_factory: Callable[[str | None, str], Any] | None = None,
    ):
        self.builder = builder or VertexBatchJsonlBuilder()
        self.uploader = uploader or GcsObjectUploader()
        self.batch_client_factory = batch_client_factory or self._batch_client

    def run(self, config: AppConfig, options: VertexBatchTestOptions) -> VertexBatchTestResult:
        started = perf_counter()
        model = options.model or self._model(config)
        location = self._location(config)
        project = self._project(config)
        local_input = self._local_input_path(config, options)
        request_count = self.builder.write(
            local_input,
            prompts=[options.prompt],
            max_output_tokens=options.max_output_tokens,
            temperature=config.generation.temperature,
        )

        gcs_prefix = self._gcs_prefix(options)
        if not options.submit:
            return VertexBatchTestResult(
                status="dry_run",
                model=model,
                project=project,
                location=location,
                local_input=local_input,
                request_count=request_count,
                latency_ms=self._elapsed_ms(started),
                details=(
                    "Wrote Vertex Gemini Batch JSONL locally. Pass --submit with "
                    f"{EnvironmentVariable.CODE_DIVER_VERTEX_BATCH_GCS_URI.value}=gs://bucket/prefix "
                    "or --gcs-uri to upload and create a Vertex Batch job."
                ),
            )
        if not gcs_prefix:
            return VertexBatchTestResult(
                status="failed",
                model=model,
                project=project,
                location=location,
                local_input=local_input,
                request_count=request_count,
                latency_ms=self._elapsed_ms(started),
                details=(
                    f"Missing {EnvironmentVariable.CODE_DIVER_VERTEX_BATCH_GCS_URI.value}. "
                    "Vertex Batch submit needs a writable GCS prefix."
                ),
            )
        if not project:
            return VertexBatchTestResult(
                status="failed",
                model=model,
                project=project,
                location=location,
                local_input=local_input,
                request_count=request_count,
                latency_ms=self._elapsed_ms(started),
                details=(
                    f"Missing {EnvironmentVariable.GOOGLE_CLOUD_PROJECT.value}. "
                    "Set it in .env or configure ADC quota project."
                ),
            )

        input_uri = self._join_gcs(gcs_prefix, local_input.name)
        output_uri = self._join_gcs(gcs_prefix, f"{local_input.stem}-output")
        try:
            self.uploader.upload_file(local_input, input_uri)
            job = self._submit(project, location, model, input_uri, output_uri)
            return VertexBatchTestResult(
                status="ok",
                model=model,
                project=project,
                location=location,
                local_input=local_input,
                request_count=request_count,
                latency_ms=self._elapsed_ms(started),
                gcs_input_uri=input_uri,
                gcs_output_uri=output_uri,
                job_name=getattr(job, "name", None),
                job_state=self._job_state(job),
                details="Submitted Vertex Batch job. Poll Vertex AI or GCS output for final predictions.",
            )
        except Exception as exc:
            return VertexBatchTestResult(
                status="failed",
                model=model,
                project=project,
                location=location,
                local_input=local_input,
                request_count=request_count,
                latency_ms=self._elapsed_ms(started),
                gcs_input_uri=input_uri,
                gcs_output_uri=output_uri,
                details=str(exc),
            )

    def _submit(self, project: str, location: str, model: str, input_uri: str, output_uri: str) -> Any:
        client = self.batch_client_factory(project, location)
        return client.batches.create(
            model=model,
            src=input_uri,
            config={
                "display_name": f"code-diver-batch-smoke-{self._timestamp()}",
                "dest": output_uri,
            },
        )

    def _batch_client(self, project: str | None, location: str) -> Any:
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise RuntimeError("Install the Vertex/Gemini extra with `uv sync --extra gemini` before using Vertex Batch.") from exc
        return genai.Client(vertexai=True, project=project, location=location)

    def _model(self, config: AppConfig) -> str:
        if config.generation.provider == Defaults.VERTEX_PROVIDER and config.generation.model:
            return config.generation.model
        return Defaults.VERTEX_BATCH_MODEL

    def _location(self, config: AppConfig) -> str:
        return (
            config.generation.location
            or os.environ.get(EnvironmentVariable.GOOGLE_CLOUD_LOCATION.value)
            or Defaults.VERTEX_LOCATION
        )

    def _project(self, config: AppConfig) -> str | None:
        return (
            config.generation.project
            or os.environ.get(EnvironmentVariable.GOOGLE_CLOUD_PROJECT.value)
            or self._adc_project()
        )

    def _adc_project(self) -> str | None:
        try:
            import google.auth
        except ImportError:  # pragma: no cover - depends on optional Google stack
            return None
        try:
            credentials, project_id = google.auth.default(scopes=[GcsObjectUploader.CLOUD_PLATFORM_SCOPE])
        except Exception:
            return None
        quota_project_id = getattr(credentials, "quota_project_id", None)
        return project_id or quota_project_id

    def _local_input_path(self, config: AppConfig, options: VertexBatchTestOptions) -> Path:
        directory = options.local_dir or (config.root / Defaults.VERTEX_BATCH_LOCAL_DIR)
        return directory / f"vertex-batch-smoke-{self._timestamp()}.jsonl"

    def _gcs_prefix(self, options: VertexBatchTestOptions) -> str | None:
        return options.gcs_uri or os.environ.get(EnvironmentVariable.CODE_DIVER_VERTEX_BATCH_GCS_URI.value)

    def _join_gcs(self, prefix: str, name: str) -> str:
        return f"{prefix.rstrip('/')}/{name}"

    def _job_state(self, job: Any) -> str | None:
        state = getattr(job, "state", None)
        if state is None:
            return None
        value = getattr(state, "value", None)
        return str(value or state)

    def _timestamp(self) -> str:
        return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")

    def _elapsed_ms(self, started: float) -> int:
        return int((perf_counter() - started) * 1000)
