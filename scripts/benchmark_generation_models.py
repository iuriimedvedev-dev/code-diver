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
from dataclasses import fields, replace
from pathlib import Path
from typing import Any, Callable

import yaml

from code_diver.cli import (
    close_vector_store,
    config_for_search_hypothesis,
    make_embedding_provider,
    make_graph_indexer,
    make_indexing_service,
    make_plugin_manager,
    make_retrieval_strategy,
)
from code_diver.config import ConfigLoader
from code_diver.domain import CodeItem
from code_diver.env import EnvFileLoader
from code_diver.providers.query_caching_embedding_provider import QueryCachingEmbeddingProvider
from code_diver.services import DatasetLoader, IndexCompositionAnalyzer
from code_diver.services.evaluation_service import EvaluationService
from code_diver.store import create_vector_store


class GenerationBenchmarkRunner:
    def __init__(self, suite_path: Path):
        self.suite_path = suite_path
        self.suite = yaml.safe_load(suite_path.read_text(encoding="utf-8"))
        self.run_id = str(self.suite.get("run_id") or uuid.uuid4().hex[:12])
        self.output_path = Path(
            self.suite.get("output", f".code-diver/reports/generation-benchmark-{self.run_id}.json")
        )
        self.log_dir = Path(self.suite.get("log_dir", ".code-diver/logs/generation-models"))
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.base_config = self._apply_config_overrides(
            ConfigLoader().load(Path(self.suite["base_config"])),
            self.suite.get("config_overrides") or {},
        )
        EnvFileLoader().load(self.base_config.env_file.path, self.base_config.env_file.override)

    def run(self, only: set[str] | None = None) -> dict[str, Any]:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        config = self._config_for_embedding(self.suite["embedding"])
        embedding_process: subprocess.Popen | None = None
        index_row: dict[str, Any] = {}
        rows: list[dict[str, Any]] = []
        try:
            if self.suite["embedding"].get("runtime"):
                embedding_process = self._start_embedding_server(self.suite["embedding"])
                self._wait_embedding_until_ready(self.suite["embedding"], embedding_process)
            index_row = self._ensure_index(config, self.suite["embedding"])
            selected_models = [
                model for model in self.suite.get("generation_models", []) if not only or model["name"] in only
            ]
            for model in selected_models:
                rows.append(
                    self._run_generation_model(
                        config,
                        model,
                        on_update=lambda row: self._write_report(index_row, [*rows, row]),
                    )
                )
                self._write_report(index_row, rows)
            report = {"run_id": self.run_id, "output": str(self.output_path), "index": index_row, "results": rows}
            self._write_report(index_row, rows)
            return report
        finally:
            if embedding_process is not None:
                self._stop_server(embedding_process)

    def _ensure_index(self, config: Any, embedding: dict[str, Any]) -> dict[str, Any]:
        row: dict[str, Any] = {
            "provider": config.embedding.provider,
            "model": config.embedding.model,
            "collection": config.storage.qdrant.collection,
            "dataset": str(config.evaluation.dataset),
            "reindexed": False,
        }
        vector_store = create_vector_store(config)
        try:
            if bool(self.suite.get("reindex", False)) or not vector_store.exists():
                close_vector_store(vector_store)
                started = time.perf_counter()
                provider = make_embedding_provider(config)
                indexing_service = make_indexing_service(config)
                items = indexing_service.build(config.root, provider, plugin_config={"config": config})
                if config.graph.enabled:
                    graph_indexer = make_graph_indexer(config)
                    if graph_indexer is not None:
                        graph_indexer(items)
                row.update(
                    {
                        "reindexed": True,
                        "duration_ms": (time.perf_counter() - started) * 1000,
                        "indexed_items": len(items),
                        "unique_paths": len({item.path for item in items}),
                        "composition": IndexCompositionAnalyzer().analyze(items),
                        "estimated_input_tokens": self._estimated_tokens(items, config.embedding.max_input_chars),
                        "estimated_cost_usd": self._estimated_cost(items, embedding, config.embedding.max_input_chars),
                    }
                )
                close_vector_store(indexing_service.vector_store)
                vector_store = create_vector_store(config)
            count_items = getattr(vector_store, "count_items", None)
            if callable(count_items):
                row["stored_items"] = count_items()
        finally:
            close_vector_store(vector_store)
        return row

    def _run_generation_model(
        self,
        config: Any,
        model: dict[str, Any],
        on_update: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        process: subprocess.Popen | None = None
        log_path = self.log_dir / f"{self._safe_name(model['name'])}.log"
        row: dict[str, Any] = {
            "name": model["name"],
            "runtime": model.get("runtime", "api"),
            "model": model.get("model"),
            "precision": model.get("precision"),
            "quantization": model.get("quantization"),
            "evaluations": [],
            "server": {"log_path": str(log_path)},
        }
        started = time.perf_counter()
        try:
            if model.get("runtime") not in {None, "api"}:
                process = self._start_server(model, log_path)
                self._wait_until_ready(model, process)
                row["server"]["startup_duration_ms"] = (time.perf_counter() - started) * 1000
            self._evaluate_generation_model(config, model, row, on_update)
        except Exception as exc:
            row["error"] = str(exc)
            if on_update is not None:
                on_update(row)
        finally:
            if process is not None:
                stop_error = self._stop_server(process)
                if stop_error:
                    row["server"]["stop_error"] = stop_error
                    if on_update is not None:
                        on_update(row)
        return row

    def _evaluate_generation_model(
        self,
        config: Any,
        model: dict[str, Any],
        row: dict[str, Any],
        on_update: Callable[[dict[str, Any]], None] | None,
    ) -> None:
        vector_store = create_vector_store(config)
        try:
            provider = QueryCachingEmbeddingProvider(make_embedding_provider(config, vector_store.metadata()))
            cases = DatasetLoader().load(config.evaluation.dataset)
            plugin_manager = make_plugin_manager(config)
            for case in cases:
                case.query = plugin_manager.prepare_query(case.query)
            for hypothesis_name, strategy_config in self._strategy_configs(config, model):
                trace_offset = self._trace_size(strategy_config.trace.artifact)
                started = time.perf_counter()
                metrics, _ = EvaluationService(
                    make_retrieval_strategy(strategy_config, provider, vector_store)
                ).evaluate(
                    cases,
                    strategy_config.evaluation.limit,
                    workers=strategy_config.evaluation.workers,
                )
                metrics["duration_ms"] = (time.perf_counter() - started) * 1000
                metrics["llm_usage"] = self._llm_usage(strategy_config.trace.artifact, trace_offset)
                row["evaluations"].append({"strategy": hypothesis_name, "metrics": metrics})
                if on_update is not None:
                    on_update(row)
        finally:
            close_vector_store(vector_store)

    def _strategy_configs(self, config: Any, model: dict[str, Any]):
        hypotheses = {hypothesis.name: hypothesis for hypothesis in config.experiments.hypotheses}
        for hypothesis_name in self.suite["hypotheses"]:
            hypothesis = hypotheses.get(hypothesis_name)
            if hypothesis is None:
                raise ValueError(f"Unknown experiment hypothesis: {hypothesis_name}")
            strategy_config = config_for_search_hypothesis(config, hypothesis)
            strategy_config = self._apply_config_overrides(
                strategy_config,
                self.suite.get("search_config_overrides") or {},
            )
            yield hypothesis_name, self._config_for_generation_model(strategy_config, model)

    def _config_for_embedding(self, embedding: dict[str, Any]):
        embedding_config = replace(
            self.base_config.embedding,
            provider=str(embedding.get("provider", self.base_config.embedding.provider)),
            model=str(embedding.get("model", self.base_config.embedding.model)),
            dimensions=self._optional_int(embedding.get("dimensions", self.base_config.embedding.dimensions)),
            api_key=embedding.get("api_key", self.base_config.embedding.api_key),
            project=embedding.get("project", self.base_config.embedding.project),
            location=embedding.get("location", self.base_config.embedding.location),
            url=embedding.get("url", self.base_config.embedding.url),
            batch_size=int(embedding.get("batch_size", self.base_config.embedding.batch_size)),
            workers=int(embedding.get("workers", self.base_config.embedding.workers)),
            max_input_chars=self._optional_int(
                embedding.get("max_input_chars", self.base_config.embedding.max_input_chars)
            ),
            document_prefix=embedding.get("document_prefix", self.base_config.embedding.document_prefix),
            query_prefix=embedding.get("query_prefix", self.base_config.embedding.query_prefix),
        )
        qdrant = replace(
            self.base_config.storage.qdrant,
            collection=str(embedding.get("collection", self.base_config.storage.qdrant.collection)),
        )
        storage = replace(self.base_config.storage, qdrant=qdrant)
        return replace(self.base_config, embedding=embedding_config, storage=storage)

    def _config_for_generation_model(self, config: Any, model: dict[str, Any]):
        provider = str(model.get("provider", "openai_compatible"))
        generation = replace(
            config.generation,
            provider=provider,
            model=str(model.get("model", config.generation.model)),
            fallback_models=list(model.get("fallback_models", [])),
            api_key=model.get("api_key", "local" if provider == "openai_compatible" else config.generation.api_key),
            project=model.get("project", config.generation.project),
            location=model.get("location", config.generation.location),
            url=model.get("url", self._chat_url(model)),
            temperature=float(model.get("temperature", 0)),
            thinking_budget=model.get("thinking_budget"),
            api_version=model.get("api_version", config.generation.api_version),
            timeout_ms=int(model.get("timeout_ms", self.suite.get("timeout_ms", 120000))),
        )
        trace_name = f"{config.trace.artifact.stem}_{model['name']}_{self.run_id}{config.trace.artifact.suffix}"
        trace = replace(config.trace, artifact=config.trace.artifact.with_name(trace_name))
        return replace(config, generation=generation, trace=trace)

    def _start_server(self, model: dict[str, Any], log_path: Path) -> subprocess.Popen:
        runtime = str(model["runtime"])
        port = int(model.get("port", self.suite.get("port", 8002)))
        env = {
            **os.environ,
            "VLLM_HOST_IP": "127.0.0.1",
            "GLOO_SOCKET_IFNAME": "lo0",
            "VLLM_METAL_MEMORY_FRACTION": str(model.get("memory_fraction", self.suite.get("memory_fraction", 0.65))),
        }
        command = self._server_command(runtime, model, port)
        with log_path.open("w", encoding="utf-8") as log:
            return subprocess.Popen(
                command,
                cwd=Path.cwd(),
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )

    def _start_embedding_server(self, embedding: dict[str, Any]) -> subprocess.Popen:
        runtime = str(embedding["runtime"])
        if runtime != "vllm_pooling":
            raise ValueError(f"Unknown embedding runtime: {runtime}")
        port = int(embedding.get("port", 8001))
        model_id = str(embedding["model"])
        log_path = self.log_dir / f"{self._safe_name(str(embedding.get('name', model_id)))}_embedding.log"
        env = {
            **os.environ,
            "VLLM_HOST_IP": "127.0.0.1",
            "GLOO_SOCKET_IFNAME": "lo0",
            "VLLM_METAL_MEMORY_FRACTION": str(embedding.get("memory_fraction", self.suite.get("memory_fraction", 0.65))),
        }
        command = [
            str(Path(embedding.get("binary", ".venv-vllm-metal-official/bin/vllm"))),
            "serve",
            model_id,
            "--runner",
            "pooling",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--max-model-len",
            str(embedding.get("max_model_len", self.suite.get("embedding_max_model_len", 512))),
        ]
        with log_path.open("w", encoding="utf-8") as log:
            return subprocess.Popen(
                command,
                cwd=Path.cwd(),
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )

    def _wait_embedding_until_ready(self, embedding: dict[str, Any], process: subprocess.Popen) -> None:
        port = int(embedding.get("port", 8001))
        model_id = str(embedding["model"])
        deadline = time.monotonic() + int(
            embedding.get("startup_timeout_seconds", self.suite.get("startup_timeout_seconds", 900))
        )
        payload = json.dumps({"model": model_id, "input": ["code search smoke"]}).encode("utf-8")
        last_error = "server did not answer"
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"embedding server exited before ready with code {process.returncode}: {last_error}")
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/embeddings",
                data=payload,
                headers={"Content-Type": "application/json", "Authorization": "Bearer local"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    if response.status == 200:
                        return
                    last_error = f"HTTP {response.status}"
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = str(exc)
            time.sleep(3)
        raise TimeoutError(f"embedding model did not become ready: {model_id}: {last_error}")

    def _server_command(self, runtime: str, model: dict[str, Any], port: int) -> list[str]:
        model_id = str(model["model"])
        if runtime == "vllm":
            return [
                str(Path(model.get("binary", ".venv-vllm-metal-official/bin/vllm"))),
                "serve",
                model_id,
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--max-model-len",
                str(model.get("max_model_len", self.suite.get("max_model_len", 2048))),
            ]
        if runtime == "mlx_lm":
            command = [
                str(Path(model.get("binary", ".venv-vllm-metal-official/bin/mlx_lm.server"))),
                "--model",
                model_id,
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--max-tokens",
                str(model.get("max_tokens", 256)),
                "--temp",
                str(model.get("temperature", 0)),
                "--prompt-concurrency",
                str(model.get("prompt_concurrency", 1)),
                "--decode-concurrency",
                str(model.get("decode_concurrency", 1)),
            ]
            if model.get("chat_template_args"):
                command.extend(["--chat-template-args", str(model["chat_template_args"])])
            return command
        if runtime == "mlx_vlm":
            command = [
                str(Path(model.get("binary", ".venv-vllm-metal-official/bin/mlx_vlm.server"))),
                "--model",
                model_id,
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--max-tokens",
                str(model.get("max_tokens", 256)),
            ]
            if model.get("enable_thinking"):
                command.append("--enable-thinking")
            return command
        raise ValueError(f"Unknown local generation runtime: {runtime}")

    def _wait_until_ready(self, model: dict[str, Any], process: subprocess.Popen) -> None:
        deadline = time.monotonic() + int(model.get("startup_timeout_seconds", self.suite.get("startup_timeout_seconds", 900)))
        last_error = "server did not answer"
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"generation server exited before ready with code {process.returncode}: {last_error}")
            for response_format in (True, False):
                try:
                    with urllib.request.urlopen(self._chat_request(model, response_format), timeout=30) as response:
                        if response.status == 200:
                            return
                        last_error = f"HTTP {response.status}"
                except urllib.error.HTTPError as exc:
                    detail = exc.read().decode("utf-8", errors="replace")
                    last_error = f"HTTP {exc.code}: {detail}"
                    if exc.code == 400 and response_format:
                        continue
                except (urllib.error.URLError, TimeoutError) as exc:
                    last_error = str(exc)
                break
            time.sleep(3)
        raise TimeoutError(f"generation model did not become ready: {model['model']}: {last_error}")

    def _chat_request(self, model: dict[str, Any], response_format: bool) -> urllib.request.Request:
        payload: dict[str, Any] = {
            "model": model["model"],
            "messages": [
                {"role": "system", "content": "Return JSON only."},
                {"role": "user", "content": "Return {\"ok\": true}."},
            ],
            "temperature": 0,
            "max_tokens": 32,
            "stream": False,
        }
        if response_format:
            payload["response_format"] = {"type": "json_object"}
        return urllib.request.Request(
            self._chat_url(model),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer local"},
            method="POST",
        )

    def _stop_server(self, process: subprocess.Popen) -> str | None:
        if process.poll() is not None:
            return None
        error: str | None = None
        try:
            os.killpg(process.pid, signal.SIGINT)
        except ProcessLookupError:
            return None
        try:
            process.wait(timeout=30)
            return None
        except subprocess.TimeoutExpired:
            error = "server ignored SIGINT"
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return error
        try:
            process.wait(timeout=30)
            return error
        except subprocess.TimeoutExpired:
            error = f"{error}; server ignored SIGTERM" if error else "server ignored SIGTERM"
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return error
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            error = f"{error}; server ignored SIGKILL" if error else "server ignored SIGKILL"
        return error

    def _write_report(self, index_row: dict[str, Any], rows: list[dict[str, Any]]) -> None:
        self.output_path.write_text(
            json.dumps({"run_id": self.run_id, "index": index_row, "results": rows}, indent=2),
            encoding="utf-8",
        )

    def _apply_config_overrides(self, config: Any, overrides: dict[str, Any]) -> Any:
        if not overrides:
            return config
        result = config
        for section_name, section_overrides in overrides.items():
            if not isinstance(section_overrides, dict) or not hasattr(result, section_name):
                continue
            section = getattr(result, section_name)
            next_section = self._replace_section(section, section_overrides)
            result = replace(result, **{section_name: next_section})
        return result

    def _replace_section(self, section: Any, overrides: dict[str, Any]) -> Any:
        values: dict[str, Any] = {}
        field_map = {field.name: field for field in fields(section)}
        for key, value in overrides.items():
            if key not in field_map:
                continue
            current_value = getattr(section, key)
            if isinstance(value, dict) and hasattr(current_value, "__dataclass_fields__"):
                values[key] = self._replace_section(current_value, value)
                continue
            if isinstance(current_value, Path):
                values[key] = Path(value)
            else:
                values[key] = value
        return replace(section, **values)

    def _estimated_tokens(self, items: list[CodeItem], max_input_chars: int | None) -> int:
        tokens = 0
        for item in items:
            text = item.to_embedding_text()
            if max_input_chars is not None and max_input_chars > 0:
                text = text[:max_input_chars]
            tokens += max(len(text) // 4, 1)
        return tokens

    def _estimated_cost(self, items: list[CodeItem], model: dict[str, Any], max_input_chars: int | None) -> float:
        cost_per_1m = float(model.get("cost_per_1m_tokens_usd", 0.0) or 0.0)
        return self._estimated_tokens(items, max_input_chars) / 1_000_000 * cost_per_1m

    def _trace_size(self, path: Path) -> int:
        if not path.exists():
            return 0
        return path.stat().st_size

    def _llm_usage(self, path: Path, offset: int) -> dict[str, Any]:
        usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "calls": 0,
            "errors": 0,
            "duration_ms": 0.0,
        }
        if not path.exists():
            return usage
        with path.open("r", encoding="utf-8") as handle:
            handle.seek(offset)
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                event = record.get("event")
                payload = record.get("payload") or {}
                if event == "llm_rerank_response":
                    usage["calls"] += 1
                    usage["input_tokens"] += int(payload.get("input_tokens", 0) or 0)
                    usage["output_tokens"] += int(payload.get("output_tokens", 0) or 0)
                    usage["total_tokens"] += int(payload.get("total_tokens", 0) or 0)
                    usage["estimated_cost_usd"] += float(payload.get("estimated_cost", 0.0) or 0.0)
                    usage["duration_ms"] += float(payload.get("duration_ms", 0.0) or 0.0)
                elif event == "llm_rerank_error":
                    usage["errors"] += 1
                    usage["duration_ms"] += float(payload.get("duration_ms", 0.0) or 0.0)
        return usage

    def _chat_url(self, model: dict[str, Any]) -> str:
        if model.get("url"):
            return str(model["url"])
        port = int(model.get("port", self.suite.get("port", 8002)))
        return f"http://127.0.0.1:{port}/v1/chat/completions"

    def _optional_int(self, value: Any) -> int | None:
        if value is None or value == "":
            return None
        return int(value)

    def _safe_name(self, value: str) -> str:
        return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--only", action="append", default=[])
    args = parser.parse_args()
    result = GenerationBenchmarkRunner(args.suite).run(set(args.only) if args.only else None)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
