from __future__ import annotations

import os
import subprocess
import time
import urllib.request
from pathlib import Path

from ..config.embedding_profile_registry import EmbeddingProfileRegistry
from .runtime_config import RuntimeConfig


class EmbeddingRuntimeManager:
    def __init__(
        self,
        config: RuntimeConfig,
        registry: EmbeddingProfileRegistry | None = None,
        log_dir: Path = Path(".code-diver/runtime/logs"),
    ) -> None:
        self.config = config
        self.registry = registry or EmbeddingProfileRegistry()
        self.log_dir = log_dir

    def install(self) -> None:
        if self.config.backend == "external":
            return
        self.config.install_dir.parent.mkdir(parents=True, exist_ok=True)
        if not self.config.install_dir.exists():
            subprocess.run(["uv", "venv", str(self.config.install_dir), "--python", "3.12"], check=True)
        python = self.config.install_dir / "bin" / "python"
        packages = ["vllm"]
        if self.config.platform == "apple-metal":
            packages.append("mlx-lm")
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                *packages,
            ],
            check=True,
        )

    def ensure_running(self, timeout_seconds: float = 120.0) -> None:
        if self.is_running():
            return
        if self.config.backend == "external":
            raise RuntimeError(
                f"External embedding server is not running: {self.config.models_url}. "
                "Start the configured container/remote endpoint or rerun `code-diver init` with host-uv."
            )
        if not self.config.auto_start:
            raise RuntimeError(f"Local embedding server is not running: {self.config.models_url}")
        if not self.config.vllm_binary.exists():
            raise RuntimeError(
                "Local embedding runtime is not installed. Run `uv run code-diver init` first, "
                f"or start a compatible server at {self.config.url}."
            )
        self.start()
        self.wait_until_ready(timeout_seconds)

    def is_running(self, timeout_seconds: float = 1.0) -> bool:
        try:
            with urllib.request.urlopen(self.config.models_url, timeout=timeout_seconds) as response:
                return 200 <= response.status < 300
        except Exception:
            return False

    def start(self) -> subprocess.Popen:
        profile = self.registry.get(self.config.embedding_profile)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.log_dir / "embedding-server.log"
        log = log_path.open("ab")
        env = dict(os.environ)
        env.setdefault("VLLM_HOST_IP", self.config.host)
        env.setdefault("GLOO_SOCKET_IFNAME", "lo0")
        env.setdefault("VLLM_METAL_MEMORY_FRACTION", str(self.config.metal_memory_fraction))
        command = [
            str(self.config.vllm_binary),
            "serve",
            str(profile.config.model),
            "--runner",
            "pooling",
            "--host",
            self.config.host,
            "--port",
            str(self.config.port),
            "--max-model-len",
            str(self.config.max_model_len),
        ]
        return subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )

    def wait_until_ready(self, timeout_seconds: float) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self.is_running(timeout_seconds=2.0):
                return
            time.sleep(1.0)
        raise RuntimeError(
            "Timed out waiting for local embedding server. "
            f"Check {self.log_dir / 'embedding-server.log'}."
        )
