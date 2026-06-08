from __future__ import annotations

import argparse
import json
import re
import signal
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark llama.cpp prompt-cache behavior for local chat models.")
    parser.add_argument("--model", type=Path, required=True, help="GGUF model path.")
    parser.add_argument("--context", type=Path, default=None, help="Stable prompt/context file to reuse.")
    parser.add_argument("--output", type=Path, default=Path(".code-diver/reports/llama-cache-benchmark.json"))
    parser.add_argument("--llama-server", default="llama-server")
    parser.add_argument("--api-key", default="local")
    parser.add_argument("--model-id", default=None)
    return parser.parse_args()


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def context_text(path: Path | None) -> str:
    if path and path.is_file():
        return path.read_text(encoding="utf-8", errors="replace")
    return "Repository context\n" + ("src/api/routes/team_builder.py handles team builder APIs.\n" * 300)


def wait_ready(port: int, api_key: str, process: subprocess.Popen[bytes], timeout: float = 90.0) -> None:
    deadline = time.time() + timeout
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    last: Exception | None = None
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"llama-server exited early with code {process.returncode}")
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last = exc
            time.sleep(1)
    raise RuntimeError(f"llama-server was not ready on {port}: {last}")


def chat(port: int, api_key: str, model: str, prefix: str, user: str) -> float:
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": prefix},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "max_tokens": 64,
            "stream": False,
        }
    ).encode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=180) as response:
        response.read()
    return (time.perf_counter() - started) * 1000


def parse_log(text: str) -> dict[str, Any]:
    return {
        "prompt_eval_ms": [float(value) for value in re.findall(r"prompt eval time =\s+([0-9.]+) ms", text)],
        "prompt_eval_tokens": [
            int(value) for value in re.findall(r"prompt eval time =\s+[0-9.]+ ms /\s+(\d+) tokens", text)
        ],
        "total_ms_log": [float(value) for value in re.findall(r"total time =\s+([0-9.]+) ms", text)],
        "forced_reprocess_count": len(re.findall(r"forcing full prompt re-processing", text)),
        "restored_checkpoint_count": len(re.findall(r"restored context checkpoint", text)),
        "cache_state_events": len(re.findall(r"cache state:", text)),
    }


def run_config(args: argparse.Namespace, config: dict[str, Any], prefix: str) -> dict[str, Any]:
    port = free_port()
    log_path = args.output.parent / f"{args.output.stem}-{config['name']}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        args.llama_server,
        "-m",
        str(args.model),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--api-key",
        args.api_key,
        *config["args"],
    ]
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            wait_ready(port, args.api_key, process)
            model_id = args.model_id or args.model.stem
            latencies = [
                chat(port, args.api_key, model_id, prefix, "Summarize this repository in one JSON object."),
                chat(port, args.api_key, model_id, prefix, "Which directory likely contains team builder routes?"),
            ]
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
    parsed = parse_log(log_path.read_text(encoding="utf-8", errors="replace"))
    return {
        "name": config["name"],
        "args": config["args"],
        "latency_ms_wall": latencies,
        "log": str(log_path),
        **parsed,
    }


def main() -> int:
    args = parse_args()
    prefix = context_text(args.context)
    configs = [
        {
            "name": "baseline_np2_cache_prompt",
            "args": ["-c", "32768", "-np", "2", "--cache-prompt", "--cache-reuse", "256", "--jinja", "--slots"],
        },
        {
            "name": "gemma_swa_single_slot_no_unified",
            "args": [
                "-c",
                "32768",
                "-np",
                "1",
                "--cache-prompt",
                "--cache-reuse",
                "1024",
                "--swa-full",
                "-no-kvu",
                "--ctx-checkpoints",
                "512",
                "--checkpoint-min-step",
                "64",
                "--cache-ram",
                "-1",
                "--jinja",
                "--slots",
            ],
        },
        {
            "name": "gemma_swa_single_slot_unified",
            "args": [
                "-c",
                "32768",
                "-np",
                "1",
                "--cache-prompt",
                "--cache-reuse",
                "1024",
                "--swa-full",
                "--ctx-checkpoints",
                "512",
                "--checkpoint-min-step",
                "64",
                "--cache-ram",
                "-1",
                "--jinja",
                "--slots",
            ],
        },
    ]
    results: list[dict[str, Any]] = []
    for config in configs:
        try:
            results.append(run_config(args, config, prefix))
        except Exception as exc:
            results.append({"name": config["name"], "args": config["args"], "error": str(exc)})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(args.output)
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
