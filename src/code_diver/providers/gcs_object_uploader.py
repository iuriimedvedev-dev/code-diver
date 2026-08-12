from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


@dataclass(frozen=True, slots=True)
class GcsObjectRef:
    bucket: str
    name: str


class GcsObjectUploader:
    CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"

    def upload_file(self, local_path: Path, gcs_uri: str) -> None:
        try:
            import requests
        except ImportError as exc:  # pragma: no cover - depends on optional Google stack
            raise RuntimeError("Install the Vertex/Gemini extra with `uv sync --extra gemini` before using GCS upload.") from exc

        ref = self.parse_uri(gcs_uri)
        token = self._access_token()
        url = (
            f"https://storage.googleapis.com/upload/storage/v1/b/{quote(ref.bucket, safe='')}/o"
            f"?uploadType=media&name={quote(ref.name, safe='')}"
        )
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/jsonl",
            },
            data=local_path.read_bytes(),
            timeout=60,
        )
        if not response.ok:
            raise RuntimeError(f"GCS upload failed: HTTP {response.status_code} {response.text[:500]}")

    def parse_uri(self, gcs_uri: str) -> GcsObjectRef:
        if not gcs_uri.startswith("gs://"):
            raise ValueError(f"GCS URI must start with gs://, got {gcs_uri!r}")
        without_scheme = gcs_uri.removeprefix("gs://")
        bucket, separator, name = without_scheme.partition("/")
        if not bucket or not separator or not name:
            raise ValueError(f"GCS URI must include bucket and object path, got {gcs_uri!r}")
        return GcsObjectRef(bucket=bucket, name=name)

    def _access_token(self) -> str:
        try:
            import google.auth
            from google.auth.transport.requests import Request
        except ImportError as exc:  # pragma: no cover - depends on optional Google stack
            raise RuntimeError("Install the Vertex/Gemini extra with `uv sync --extra gemini` before using Vertex Batch submit.") from exc
        credentials, _project_id = google.auth.default(scopes=[self.CLOUD_PLATFORM_SCOPE])
        credentials.refresh(Request())
        token = credentials.token
        if not token:
            raise RuntimeError("Could not obtain an ADC access token for GCS upload.")
        return token
