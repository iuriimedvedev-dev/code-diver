from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml

from benchmark_embedding_models import EmbeddingBenchmarkRunner


class VllmEmbeddingBenchmark:
    def __init__(
        self,
        suite_path: Path,
        vllm_bin: Path,
        port: int,
        max_model_len: int,
        memory_fraction: float,
    ):
        self.suite_path = suite_path
        self.vllm_bin = vllm_bin
        self.port = port
        self.max_model_len = max_model_len
        self.memory_fraction = memory_fraction
        self.suite = yaml.safe_load(suite_path.read_text(encoding="utf-8"))
        self.output_path = Path(self.suite["output"])
        self.tmp_dir = Path(".code-diver/tmp/vllm-embedding-benchmark")
        self.log_dir = Path(".code-diver/logs/vllm")
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def run(self, only: set[str] | None = None) -> dict[str, Any]:
        rows = []
        selected_models = [
            model for model in self.suite.get("models", []) if not only or str(model["name"]) in only
        ]
        for model in selected_models:
            rows.append(self._run_model(model))
            self._write_report(rows)
        return {"output": str(self.output_path), "results": rows}

    def _run_model(self, model: dict[str, Any]) -> dict[str, Any]:
        process = None
        log_path = self.log_dir / f"{self._safe_name(model['name'])}.log"
        started = time.perf_counter()
        try:
            process = self._start_server(str(model["model"]), log_path)
            self._wait_until_ready(str(model["model"]), process)
            temp_suite = self._write_temp_suite(model)
            result = EmbeddingBenchmarkRunner(temp_suite).run()
            row = result["results"][0]
            row["vllm"] = {
                "model": model["model"],
                "server_start_duration_ms": (time.perf_counter() - started) * 1000,
                "log_path": str(log_path),
            }
            return row
        except Exception as exc:
            return {
                "name": model.get("name"),
                "model": model.get("model"),
                "error": str(exc),
                "vllm": {
                    "server_start_duration_ms": (time.perf_counter() - started) * 1000,
                    "log_path": str(log_path),
                },
            }
        finally:
            if process is not None:
                self._stop_server(process)

    def _start_server(self, model_id: str, log_path: Path) -> subprocess.Popen:
        env = {
            **os.environ,
            "VLLM_HOST_IP": "127.0.0.1",
            "GLOO_SOCKET_IFNAME": "lo0",
            "VLLM_METAL_MEMORY_FRACTION": str(self.memory_fraction),
        }
        with log_path.open("w", encoding="utf-8") as log:
            return subprocess.Popen(
                [
                    str(self.vllm_bin),
                    "serve",
                    model_id,
                    "--runner",
                    "pooling",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(self.port),
                    "--max-model-len",
                    str(self.max_model_len),
                ],
                cwd=Path.cwd(),
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )

    def _wait_until_ready(self, model_id: str, process: subprocess.Popen) -> None:
        deadline = time.monotonic() + 240
        payload = json.dumps({"model": model_id, "input": ["code search smoke"]}).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/v1/embeddings",
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": "Bearer local"},
            method="POST",
        )
        last_error = "server did not answer"
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"vLLM exited before ready with code {process.returncode}: {last_error}")
            try:
                with urllib.request.urlopen(request, timeout=15) as response:
                    if response.status == 200:
                        return
                    last_error = f"HTTP {response.status}"
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = str(exc)
            time.sleep(2)
        raise TimeoutError(f"vLLM model did not become ready: {model_id}: {last_error}")

    def _write_temp_suite(self, model: dict[str, Any]) -> Path:
        suite = {**self.suite, "models": [model]}
        suite["output"] = str(self.tmp_dir / f"{self._safe_name(model['name'])}.json")
        temp_path = self.tmp_dir / f"{self._safe_name(model['name'])}.yml"
        temp_path.write_text(yaml.safe_dump(suite, sort_keys=False), encoding="utf-8")
        return temp_path

    def _write_report(self, rows: list[dict[str, Any]]) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(json.dumps({"results": rows}, indent=2), encoding="utf-8")

    def _stop_server(self, process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        os.killpg(process.pid, signal.SIGINT)
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=30)

    def _safe_name(self, value: str) -> str:
        return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--vllm-bin", type=Path, default=Path(".venv-vllm-metal-official/bin/vllm"))
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--max-model-len", type=int, default=512)
    parser.add_argument("--memory-fraction", type=float, default=0.55)
    parser.add_argument("--only", action="append", default=[])
    args = parser.parse_args()
    result = VllmEmbeddingBenchmark(
        args.suite,
        args.vllm_bin,
        args.port,
        args.max_model_len,
        args.memory_fraction,
    ).run(set(args.only) if args.only else None)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
