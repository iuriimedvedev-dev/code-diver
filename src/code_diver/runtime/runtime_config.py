from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


def default_runtime_install_dir(platform: str) -> Path:
    if platform == "apple-metal":
        return Path(".code-diver/runtime/vllm-metal")
    return Path(".code-diver/runtime/vllm")


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    embedding_profile: str
    install_dir: Path
    backend: str = "host-uv"
    platform: str = "apple-metal"
    host: str = "127.0.0.1"
    port: int = 8001
    max_model_len: int = 512
    metal_memory_fraction: float = 0.55
    auto_start: bool = True

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/v1/embeddings"

    @property
    def models_url(self) -> str:
        return f"http://{self.host}:{self.port}/v1/models"

    @property
    def vllm_binary(self) -> Path:
        return self.install_dir / "bin" / "vllm"

    @property
    def dependency_group(self) -> str | None:
        if self.platform == "apple-metal":
            return "runtime-apple-metal"
        if self.platform in {"nvidia-cuda", "amd-rocm", "cpu"}:
            return "runtime-vllm"
        return None

    def to_yaml_data(self) -> dict[str, Any]:
        return {
            "embedding_profile": self.embedding_profile,
            "install_dir": str(self.install_dir),
            "backend": self.backend,
            "platform": self.platform,
            "host": self.host,
            "port": self.port,
            "max_model_len": self.max_model_len,
            "metal_memory_fraction": self.metal_memory_fraction,
            "auto_start": self.auto_start,
        }

    @classmethod
    def from_yaml_data(cls, data: dict[str, Any]) -> "RuntimeConfig":
        return cls(
            embedding_profile=str(data["embedding_profile"]),
            install_dir=Path(
                data.get("install_dir", default_runtime_install_dir(str(data.get("platform", "apple-metal"))))
            ),
            backend=str(data.get("backend", "host-uv")),
            platform=str(data.get("platform", "apple-metal")),
            host=str(data.get("host", "127.0.0.1")),
            port=int(data.get("port", 8001)),
            max_model_len=int(data.get("max_model_len", 512)),
            metal_memory_fraction=float(data.get("metal_memory_fraction", 0.55)),
            auto_start=bool(data.get("auto_start", True)),
        )
