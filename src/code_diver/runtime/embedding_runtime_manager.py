from __future__ import annotations

import os
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from ..config.embedding_profile_registry import EmbeddingProfileRegistry
from .runtime_config import RuntimeConfig


class EmbeddingRuntimeManager:
    VLLM_METAL_VERSION = "0.22.0"

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
        if self.config.platform == "apple-metal":
            self._install_apple_metal_runtime()
            return
        python = self.config.install_dir / "bin" / "python"
        command = ["uv", "pip", "install", "--python", str(python), *self._uv_project_args()]
        if self.config.dependency_group:
            command.extend(["--group", self.config.dependency_group])
        else:
            command.append("vllm")
        subprocess.run(command, check=True)

    def _install_apple_metal_runtime(self) -> None:
        python = self.config.install_dir / "bin" / "python"
        if self._python_can_import(python, "vllm") and self._python_can_import(python, "vllm_metal"):
            return
        with tempfile.TemporaryDirectory(prefix="code-diver-vllm-metal-") as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / f"vllm-{self.VLLM_METAL_VERSION}.tar.gz"
            source_root = tmp_path / f"vllm-{self.VLLM_METAL_VERSION}"
            url = (
                "https://github.com/vllm-project/vllm/releases/download/"
                f"v{self.VLLM_METAL_VERSION}/vllm-{self.VLLM_METAL_VERSION}.tar.gz"
            )
            subprocess.run(["curl", "-fL", url, "-o", str(archive)], check=True)
            subprocess.run(["tar", "xf", str(archive), "-C", str(tmp_path)], check=True)
            subprocess.run(
                [
                    "uv",
                    "pip",
                    "install",
                    "--python",
                    str(python),
                    "-r",
                    str(source_root / "requirements" / "cpu.txt"),
                    "--index-strategy",
                    "unsafe-best-match",
                ],
                check=True,
            )
            subprocess.run(["uv", "pip", "install", "--python", str(python), str(source_root)], check=True)
        command = ["uv", "pip", "install", "--python", str(python), *self._uv_project_args()]
        if self.config.dependency_group:
            command.extend(["--group", self.config.dependency_group])
        else:
            command.append(
                "vllm-metal @ "
                "https://github.com/vllm-project/vllm-metal/releases/download/"
                "v0.2.0-20260601-072909/vllm_metal-0.2.0-cp312-cp312-macosx_11_0_arm64.whl"
            )
        subprocess.run(command, check=True)

    def _uv_project_args(self) -> list[str]:
        root = Path(__file__).resolve().parents[3]
        if (root / "pyproject.toml").exists():
            return ["--project", str(root)]
        return []

    def _python_can_import(self, python: Path, module: str) -> bool:
        if not python.exists():
            return False
        result = subprocess.run(
            [str(python), "-c", f"import {module}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode == 0

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
        process = self.start()
        self.wait_until_ready(timeout_seconds, process)

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
        log.write(("\n--- code-diver embedding server start ---\n" + " ".join(command) + "\n").encode("utf-8"))
        log.flush()
        return subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )

    def wait_until_ready(self, timeout_seconds: float, process: subprocess.Popen | None = None) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self.is_running(timeout_seconds=2.0):
                return
            if process is not None and process.poll() is not None:
                raise RuntimeError(
                    "Local embedding server exited while starting "
                    f"(exit_code={process.returncode}). Check {self.log_dir / 'embedding-server.log'}.\n"
                    f"{self._last_log_excerpt()}"
                )
            time.sleep(1.0)
        raise RuntimeError(
            "Timed out waiting for local embedding server. "
            f"Check {self.log_dir / 'embedding-server.log'}.\n"
            f"{self._last_log_excerpt()}"
        )

    def _last_log_excerpt(self, line_limit: int = 40) -> str:
        log_path = self.log_dir / "embedding-server.log"
        if not log_path.exists():
            return "Embedding server log does not exist yet."
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if not lines:
            return "Embedding server log is empty."
        return "Last embedding server log lines:\n" + "\n".join(lines[-line_limit:])
