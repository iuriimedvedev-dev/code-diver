from __future__ import annotations

from .embedding_config import EmbeddingConfig
from .embedding_profile import EmbeddingProfile


class EmbeddingProfileRegistry:
    def __init__(self) -> None:
        self._profiles = [
            EmbeddingProfile(
                key="qwen3-0.6b",
                label="Qwen3 Embedding 0.6B 4-bit",
                description="Apple Silicon vLLM-Metal server, best practical local default",
                config=EmbeddingConfig(
                    provider="openai_compatible",
                    model="mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ",
                    dimensions=None,
                    api_key="local",
                    url="http://127.0.0.1:8001/v1/embeddings",
                    batch_size=64,
                    workers=1,
                    max_input_chars=400,
                    document_prefix="Represent this code file metadata for retrieval: ",
                    query_prefix="Represent this code search query for retrieving relevant files: ",
                ),
                platforms=("apple-metal", "external"),
                runtime="vllm-metal",
                startup_hint=(
                    ".code-diver/runtime/vllm-metal/bin/vllm serve "
                    "mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ --runner pooling "
                    "--host 127.0.0.1 --port 8001 --max-model-len 512"
                ),
            ),
            EmbeddingProfile(
                key="qwen3-4b",
                label="Qwen3 Embedding 4B 4-bit",
                description="Apple Silicon vLLM-Metal server, stronger but slower; downloads model on first serve",
                config=EmbeddingConfig(
                    provider="openai_compatible",
                    model="mlx-community/Qwen3-Embedding-4B-4bit-DWQ",
                    dimensions=None,
                    api_key="local",
                    url="http://127.0.0.1:8001/v1/embeddings",
                    batch_size=64,
                    workers=1,
                    max_input_chars=400,
                    document_prefix="Represent this code file metadata for retrieval: ",
                    query_prefix="Represent this code search query for retrieving relevant files: ",
                ),
                platforms=("apple-metal", "external"),
                runtime="vllm-metal",
                startup_hint=(
                    ".code-diver/runtime/vllm-metal/bin/vllm serve "
                    "mlx-community/Qwen3-Embedding-4B-4bit-DWQ --runner pooling "
                    "--host 127.0.0.1 --port 8001 --max-model-len 512"
                ),
            ),
            EmbeddingProfile(
                key="qwen3-0.6b-vllm",
                label="Qwen3 Embedding 0.6B",
                description="vLLM server for Nvidia CUDA, AMD ROCm, or CPU; downloads HF model on first serve",
                config=EmbeddingConfig(
                    provider="openai_compatible",
                    model="Qwen/Qwen3-Embedding-0.6B",
                    dimensions=None,
                    api_key="local",
                    url="http://127.0.0.1:8001/v1/embeddings",
                    batch_size=64,
                    workers=1,
                    max_input_chars=400,
                    document_prefix="Represent this code file metadata for retrieval: ",
                    query_prefix="Represent this code search query for retrieving relevant files: ",
                ),
                platforms=("nvidia-cuda", "amd-rocm", "cpu", "external"),
                runtime="vllm",
                startup_hint=(
                    ".code-diver/runtime/vllm/bin/vllm serve Qwen/Qwen3-Embedding-0.6B "
                    "--runner pooling --host 127.0.0.1 --port 8001 --max-model-len 512"
                ),
            ),
            EmbeddingProfile(
                key="qwen3-4b-vllm",
                label="Qwen3 Embedding 4B",
                description="vLLM server for Nvidia CUDA, AMD ROCm, or CPU; stronger but slower",
                config=EmbeddingConfig(
                    provider="openai_compatible",
                    model="Qwen/Qwen3-Embedding-4B",
                    dimensions=None,
                    api_key="local",
                    url="http://127.0.0.1:8001/v1/embeddings",
                    batch_size=64,
                    workers=1,
                    max_input_chars=400,
                    document_prefix="Represent this code file metadata for retrieval: ",
                    query_prefix="Represent this code search query for retrieving relevant files: ",
                ),
                platforms=("nvidia-cuda", "amd-rocm", "cpu", "external"),
                runtime="vllm",
                startup_hint=(
                    ".code-diver/runtime/vllm/bin/vllm serve Qwen/Qwen3-Embedding-4B "
                    "--runner pooling --host 127.0.0.1 --port 8001 --max-model-len 512"
                ),
            ),
            EmbeddingProfile(
                key="gemini",
                label="Gemini Embedding 2 API",
                description="remote Gemini API; requires GEMINI_API_KEY or gcloud ADC",
                config=EmbeddingConfig(
                    provider="gemini",
                    model="gemini-embedding-2",
                    dimensions=768,
                    batch_size=32,
                    workers=1,
                ),
                platforms=("api", "external"),
                runtime="api",
            ),
        ]

    def profiles(self) -> list[EmbeddingProfile]:
        return list(self._profiles)

    def profiles_for_platform(self, platform: str) -> list[EmbeddingProfile]:
        return [profile for profile in self._profiles if platform in profile.platforms]

    def keys(self) -> list[str]:
        return [profile.key for profile in self._profiles]

    def get(self, key: str) -> EmbeddingProfile:
        for profile in self._profiles:
            if profile.key == key:
                return profile
        raise ValueError(f"Unknown embedding profile: {key}")
