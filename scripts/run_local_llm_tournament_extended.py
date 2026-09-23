#!/usr/bin/env python3
"""Run Extended Tournament of Local MLX & llama.cpp (GGUF) LLMs.

Tests:
1. MLX: gemma-4-e2b-it-4bit
2. MLX: gemma-4-e4b-it-4bit
3. GGUF: gemma-4-e2b-it-qat-GGUF (via llama-server Metal)
4. GGUF: gemma-4-e4b-it-qat-GGUF (via llama-server Metal)
5. MLX: Qwen3.5-4B-MLX-4bit
6. MLX: Qwen3.5-9B-MLX-4bit
"""

import json
import os
import re
import select
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
import numpy as np

CONTEXTS_PATH = Path("artifacts/research/precomputed_agent_contexts_100.json")
REPORT_PATH = Path("artifacts/research/local_llm_tournament_extended_report.json")
REPO_ROOT = Path("/Users/iurii.medvedev/Work/intellij-community")
SERVER_VENV = Path(".venv-vllm-metal-official")
MLX_SERVER_BIN = SERVER_VENV / "bin" / "mlx_lm"
LLAMA_SERVER_BIN = Path("/opt/homebrew/bin/llama-server")
PORT = 8016

MODELS_TO_BENCHMARK = [
    {
        "name": "gemma-4-e2b-it-4bit (MLX)",
        "path": ".code-diver/models/mlx-community-gemma-4-e2b-it-4bit",
        "backend": "mlx",
    },
    {
        "name": "gemma-4-e4b-it-4bit (MLX)",
        "path": ".code-diver/models/mlx-community-gemma-4-e4b-it-4bit",
        "backend": "mlx",
    },
    {
        "name": "gemma-4-e2b-it-qat (GGUF)",
        "path": ".code-diver/models/gemma-4-e2b-it-qat-GGUF/gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf",
        "backend": "llama_server",
    },
    {
        "name": "gemma-4-e4b-it-qat (GGUF)",
        "path": ".code-diver/models/gemma-4-e4b-it-qat-GGUF/gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf",
        "backend": "llama_server",
    },
    {
        "name": "Qwen3.5-4B-4bit (MLX)",
        "path": ".code-diver/models/mlx-community-Qwen3.5-4B-MLX-4bit",
        "backend": "mlx",
    },
    {
        "name": "Qwen3.5-9B-4bit (MLX)",
        "path": ".code-diver/models/mlx-community-Qwen3.5-9B-MLX-4bit",
        "backend": "mlx",
    },
]


def stop_any_server_on_port(port: int):
    try:
        out = subprocess.check_output(["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"], text=True)
        for pid_str in out.strip().splitlines():
            pid = int(pid_str.strip())
            os.kill(pid, 9)
        time.sleep(1)
    except Exception:
        pass


class ModelServer:
    def __init__(self, model_spec: dict, port: int = PORT):
        stop_any_server_on_port(port)
        self.port = port
        self.backend = model_spec["backend"]
        self.model_path = model_spec["path"]

        if self.backend == "mlx":
            cmd = [
                str(SERVER_VENV / "bin" / "python"),
                str(MLX_SERVER_BIN),
                "server",
                "--model", self.model_path,
                "--host", "127.0.0.1",
                "--port", str(port),
                "--chat-template-args", '{"enable_thinking":false}',
            ]
        elif self.backend == "llama_server":
            cmd = [
                str(LLAMA_SERVER_BIN),
                "-m", self.model_path,
                "--host", "127.0.0.1",
                "--port", str(port),
                "-ngl", "99",
                "-c", "16384",
                "--reasoning", "off",
            ]
        else:
            raise ValueError(f"Unknown backend: {self.backend}")

        self.log_file = open(f"/tmp/model-server-{port}.log", "w")
        self.proc = subprocess.Popen(cmd, stdout=self.log_file, stderr=self.log_file)
        self._wait_ready()

    def _wait_ready(self, timeout_sec: int = 180):
        t0 = time.time()
        url = f"http://127.0.0.1:{self.port}/v1/models"
        while time.time() - t0 < timeout_sec:
            if self.proc.poll() is not None:
                raise RuntimeError(f"Server exited with returncode {self.proc.returncode}")
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=2) as resp:
                    if resp.status == 200:
                        return
            except Exception:
                time.sleep(1)
        raise TimeoutError(f"Server {self.backend} failed to start within timeout")

    def generate(self, prompt: str, max_tokens: int = 512, temperature: float = 0.1):
        url = f"http://127.0.0.1:{self.port}/v1/chat/completions"
        payload = {
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read().decode("utf-8")
        dur_ms = (time.perf_counter() - t0) * 1000.0
        parsed = json.loads(raw)
        choice = parsed["choices"][0]
        msg = choice.get("message", {})
        text = msg.get("content") or msg.get("reasoning", "") or msg.get("reasoning_content", "") or ""
        usage = parsed.get("usage", {})
        completion_tokens = usage.get("completion_tokens", len(text.split()))
        tok_per_sec = (completion_tokens / (dur_ms / 1000.0)) if dur_ms > 0 else 0.0
        return {
            "text": text,
            "duration_ms": dur_ms,
            "completion_tokens": completion_tokens,
            "tokens_per_sec": tok_per_sec,
        }

    def close(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()
        self.log_file.close()
        stop_any_server_on_port(self.port)


def extract_json_payload(text: str) -> dict:
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return json.loads(text[first_brace:last_brace + 1])
    return json.loads(text)


def evaluate_model(model_spec, cases):
    print(f"\n=======================================================", flush=True)
    print(f"Testing Model: {model_spec['name']} ({model_spec['path']})", flush=True)
    print(f"Backend: {model_spec['backend']}", flush=True)
    print(f"=======================================================", flush=True)

    t0_start = time.time()
    try:
        server = ModelServer(model_spec, port=PORT)
    except Exception as e:
        print(f"FAILED TO START {model_spec['name']}: {e}", flush=True)
        return None

    load_time_sec = time.time() - t0_start
    print(f"Loaded {model_spec['name']} in {load_time_sec:.2f}s", flush=True)

    durations = []
    tps_list = []
    json_valid_count = 0
    total_citations = 0
    valid_path_citations = 0
    valid_line_citations = 0
    grounded_citations = 0

    file_lines_cache = {}

    def get_file_lines(rel_path: str) -> int:
        if rel_path in file_lines_cache:
            return file_lines_cache[rel_path]
        p = REPO_ROOT / rel_path
        if not p.is_file():
            file_lines_cache[rel_path] = -1
            return -1
        try:
            with open(p, "rb") as f:
                lines = sum(1 for _ in f)
            file_lines_cache[rel_path] = lines
            return lines
        except Exception:
            file_lines_cache[rel_path] = -1
            return -1

    for idx, case in enumerate(cases):
        prompt = case["prompt"]
        context_files = set(case.get("context_files", []))

        try:
            gen_res = server.generate(prompt)
            dur_ms = gen_res["duration_ms"]
            tps = gen_res["tokens_per_sec"]
            durations.append(dur_ms)
            tps_list.append(tps)

            try:
                payload = extract_json_payload(gen_res["text"])
                json_valid_count += 1
                citations = payload.get("citations", [])
                if isinstance(citations, list):
                    for cite in citations:
                        total_citations += 1
                        path = str(cite.get("path", "")).strip()
                        lines_str = str(cite.get("lines", "")).strip()

                        if path in context_files:
                            grounded_citations += 1

                        flines = get_file_lines(path)
                        if flines != -1:
                            valid_path_citations += 1

                            line_match = re.search(r"(\d+)(?:\s*-\s*(\d+))?", lines_str)
                            if line_match:
                                start_l = int(line_match.group(1))
                                end_l = int(line_match.group(2)) if line_match.group(2) else start_l
                                if 1 <= start_l <= flines and 1 <= end_l <= flines:
                                    valid_line_citations += 1
            except Exception:
                pass

        except Exception as e:
            print(f"Error on case {idx}: {e}")

        if (idx + 1) % 25 == 0 or idx + 1 == len(cases):
            avg_ms = np.mean(durations) if durations else 0
            avg_tps = np.mean(tps_list) if tps_list else 0
            print(f"[{idx+1}/{len(cases)}] avg gen: {avg_ms:.0f}ms, avg speed: {avg_tps:.1f} tps, json_valid: {json_valid_count}/{idx+1}", flush=True)

    server.close()

    n = len(cases)
    report = {
        "model": model_spec["name"],
        "backend": model_spec["backend"],
        "load_time_sec": load_time_sec,
        "cases": n,
        "json_valid_rate": json_valid_count / n if n > 0 else 0.0,
        "mean_latency_ms": float(np.mean(durations)) if durations else 0.0,
        "p50_latency_ms": float(np.percentile(durations, 50)) if durations else 0.0,
        "p95_latency_ms": float(np.percentile(durations, 95)) if durations else 0.0,
        "mean_tokens_per_sec": float(np.mean(tps_list)) if tps_list else 0.0,
        "total_citations": total_citations,
        "citation_path_valid_rate": (valid_path_citations / total_citations) if total_citations > 0 else 0.0,
        "citation_line_valid_rate": (valid_line_citations / total_citations) if total_citations > 0 else 0.0,
        "grounded_citation_rate": (grounded_citations / total_citations) if total_citations > 0 else 0.0,
    }
    return report


def main():
    with open(CONTEXTS_PATH, "r", encoding="utf-8") as f:
        cases = json.load(f)
    print(f"Loaded {len(cases)} precomputed cases from {CONTEXTS_PATH}")

    results = []
    for model_spec in MODELS_TO_BENCHMARK:
        p = Path(model_spec["path"])
        if not p.exists():
            print(f"Skipping {model_spec['name']}: {p} not found")
            continue
        rep = evaluate_model(model_spec, cases)
        if rep:
            results.append(rep)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("\n\n================================ EXTENDED TOURNAMENT LEADERBOARD ================================")
    print(f"{'Model':<30} | {'Speed (t/s)':<11} | {'Mean Lat (ms)':<13} | {'p95 Lat (ms)':<13} | {'JSON Valid':<10} | {'Path Valid':<10} | {'Line Valid':<10}")
    print("-" * 115)
    for r in results:
        print(f"{r['model']:<30} | {r['mean_tokens_per_sec']:10.1f} | {r['mean_latency_ms']:12.0f} | {r['p95_latency_ms']:12.0f} | {r['json_valid_rate']*100:9.1f}% | {r['citation_path_valid_rate']*100:9.1f}% | {r['citation_line_valid_rate']*100:9.1f}%")
    print("=================================================================================================\n")


if __name__ == "__main__":
    main()
