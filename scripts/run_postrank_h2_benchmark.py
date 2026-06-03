from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any


class ManagedServer:
    def __init__(self, command: list[str], log_path: Path, env: dict[str, str]):
        self.command = command
        self.log_path = log_path
        self.env = env
        self.process: subprocess.Popen[str] | None = None

    def start(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("w", encoding="utf-8") as log:
            self.process = subprocess.Popen(
                self.command,
                cwd=Path.cwd(),
                env=self.env,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )

    def stop(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        for sig, timeout in ((signal.SIGINT, 30), (signal.SIGTERM, 20), (signal.SIGKILL, 10)):
            try:
                os.killpg(self.process.pid, sig)
            except ProcessLookupError:
                return
            try:
                self.process.wait(timeout=timeout)
                return
            except subprocess.TimeoutExpired:
                continue


class PostrankH2Benchmark:
    def __init__(self, args: argparse.Namespace):
        self.config = args.config
        self.output = args.output
        self.report = args.report
        self.cases = args.cases
        self.dataset = args.dataset
        self.run_id = args.run_id or uuid.uuid4().hex[:12]
        self.log_dir = args.log_dir
        self.embedding_port = args.embedding_port
        self.generation_port = args.generation_port
        self.embedding_model = args.embedding_model
        self.generation_model = args.generation_model
        self.generation_max_tokens = args.generation_max_tokens
        self.generation_prompt_concurrency = args.generation_prompt_concurrency
        self.generation_decode_concurrency = args.generation_decode_concurrency
        self.hypotheses = args.hypothesis
        self.start_embedding = not args.no_start_embedding
        self.start_generation = not args.no_start_generation
        self.startup_timeout_seconds = args.startup_timeout_seconds
        self.servers: list[ManagedServer] = []

    def run(self) -> dict[str, Any]:
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        dataset = self._dataset_path()
        try:
            if self.start_embedding:
                self._start_embedding_server()
            if self.start_generation:
                self._start_generation_server()
            result = self._run_eval(dataset)
            result["run_id"] = result.get("run_id") or self.run_id
            result["benchmark"] = {
                "config": str(self.config),
                "dataset": str(dataset),
                "cases": self.cases,
                "embedding_model": self.embedding_model,
                "generation_model": self.generation_model,
            }
            self.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            if self.report is not None:
                self._build_report()
            return result
        finally:
            for server in reversed(self.servers):
                server.stop()

    def _dataset_path(self) -> Path:
        if self.cases <= 0:
            return self.dataset
        target = Path(".code-diver/tmp/postrank-h2") / f"{self.dataset.stem}_{self.cases}_{self.run_id}.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        lines = self.dataset.read_text(encoding="utf-8").splitlines()[: self.cases]
        target.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return target

    def _start_embedding_server(self) -> None:
        env = {
            **os.environ,
            "VLLM_HOST_IP": "127.0.0.1",
            "GLOO_SOCKET_IFNAME": "lo0",
            "VLLM_METAL_MEMORY_FRACTION": "0.55",
        }
        server = ManagedServer(
            [
                ".venv-vllm-metal-official/bin/vllm",
                "serve",
                self.embedding_model,
                "--runner",
                "pooling",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.embedding_port),
                "--max-model-len",
                "512",
            ],
            self.log_dir / f"postrank-h2-embedding-{self.run_id}.log",
            env,
        )
        server.start()
        self.servers.append(server)
        self._wait_embeddings(server, self.embedding_model, self.embedding_port)

    def _start_generation_server(self) -> None:
        server = ManagedServer(
            [
                ".venv-vllm-metal-official/bin/mlx_lm.server",
                "--model",
                self.generation_model,
                "--host",
                "127.0.0.1",
                "--port",
                str(self.generation_port),
                "--max-tokens",
                str(self.generation_max_tokens),
                "--temp",
                "0",
                "--prompt-concurrency",
                str(self.generation_prompt_concurrency),
                "--decode-concurrency",
                str(self.generation_decode_concurrency),
                "--chat-template-args",
                '{"enable_thinking": false}',
            ],
            self.log_dir / f"postrank-h2-generation-{self.run_id}.log",
            dict(os.environ),
        )
        server.start()
        self.servers.append(server)
        self._wait_chat(server, self.generation_model, self.generation_port)

    def _wait_embeddings(self, server: ManagedServer, model: str, port: int) -> None:
        payload = json.dumps({"model": model, "input": ["code search smoke"]}).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/embeddings",
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": "Bearer local"},
            method="POST",
        )
        self._wait_http(server, request, "embedding")

    def _wait_chat(self, server: ManagedServer, model: str, port: int) -> None:
        payload = json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": "Return {\"ok\": true} as JSON."}],
                "temperature": 0,
                "max_tokens": 32,
                "stream": False,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": "Bearer local"},
            method="POST",
        )
        self._wait_http(server, request, "generation")

    def _wait_http(self, server: ManagedServer, request: urllib.request.Request, label: str) -> None:
        deadline = time.monotonic() + self.startup_timeout_seconds
        last_error = "server did not answer"
        while time.monotonic() < deadline:
            if server.process is not None and server.process.poll() is not None:
                raise RuntimeError(f"{label} server exited with {server.process.returncode}: {last_error}")
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    if response.status == 200:
                        return
                    last_error = f"HTTP {response.status}"
            except urllib.error.HTTPError as exc:
                last_error = f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}"
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = str(exc)
            time.sleep(3)
        raise TimeoutError(f"{label} server did not become ready: {last_error}; log={server.log_path}")

    def _run_eval(self, dataset: Path) -> dict[str, Any]:
        command = [
            ".venv/bin/code-diver",
            "--config",
            str(self.config),
            "evaluate-search-tools",
            "--dataset",
            str(dataset),
            "--details",
            "--json",
        ]
        for hypothesis in self.hypotheses:
            command.extend(["--hypothesis", hypothesis])
        completed = subprocess.run(command, text=True, capture_output=True, timeout=None, check=False)
        if completed.returncode != 0:
            raise RuntimeError(f"eval failed with {completed.returncode}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}")
        return json.loads(completed.stdout)

    def _build_report(self) -> None:
        subprocess.run(
            [
                ".venv/bin/python",
                "scripts/build_eval_report.py",
                str(self.output),
                "--output",
                str(self.report),
            ],
            check=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the IntelliJ H2 post-ranking 2x3 benchmark.")
    parser.add_argument("--config", type=Path, default=Path("configs/intellij-postrank-h2.yml"))
    parser.add_argument("--dataset", type=Path, default=Path("datasets/intellij_eval_1000.jsonl"))
    parser.add_argument("--cases", type=int, default=100, help="Use first N cases; pass 0 for the full dataset.")
    parser.add_argument("--output", type=Path, default=Path(".code-diver/reports/intellij-postrank-h2-100.json"))
    parser.add_argument("--report", type=Path, default=Path(".code-diver/reports/intellij-postrank-h2-100.html"))
    parser.add_argument("--run-id", default="")
    parser.add_argument("--log-dir", type=Path, default=Path(".code-diver/logs/postrank-h2"))
    parser.add_argument("--embedding-port", type=int, default=8001)
    parser.add_argument("--generation-port", type=int, default=8012)
    parser.add_argument("--embedding-model", default="mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ")
    parser.add_argument("--generation-model", default="mlx-community/Qwen3.5-4B-OptiQ-4bit")
    parser.add_argument("--generation-max-tokens", type=int, default=1536)
    parser.add_argument("--generation-prompt-concurrency", type=int, default=2)
    parser.add_argument("--generation-decode-concurrency", type=int, default=2)
    parser.add_argument("--hypothesis", action="append", default=[])
    parser.add_argument("--startup-timeout-seconds", type=int, default=1200)
    parser.add_argument("--no-start-embedding", action="store_true")
    parser.add_argument("--no-start-generation", action="store_true")
    args = parser.parse_args()
    result = PostrankH2Benchmark(args).run()
    print(json.dumps({"run_id": result.get("run_id"), "output": str(args.output), "report": str(args.report)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
