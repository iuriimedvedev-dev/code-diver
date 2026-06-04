from __future__ import annotations

import argparse
import json
import time
import uuid
from dataclasses import fields, replace
from pathlib import Path
from typing import Any

import yaml

from code_diver.cli import (
    close_vector_store,
    config_for_search_hypothesis,
    make_embedding_provider,
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


class EmbeddingBenchmarkRunner:
    def __init__(self, suite_path: Path):
        self.suite_path = suite_path
        self.suite = yaml.safe_load(suite_path.read_text(encoding="utf-8"))
        self.base_config = self._apply_config_overrides(
            ConfigLoader().load(Path(self.suite["base_config"])),
            self.suite.get("config_overrides") or {},
        )
        EnvFileLoader().load(self.base_config.env_file.path, self.base_config.env_file.override)
        self.run_id = str(self.suite.get("run_id") or uuid.uuid4().hex[:12])

    def run(self, only: set[str] | None = None) -> dict[str, Any]:
        output_path = Path(self.suite.get("output", f".code-diver/reports/embedding-benchmark-{self.run_id}.json"))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        for model in self.suite.get("models", []):
            if only and model["name"] not in only:
                continue
            rows.append(self._run_model(model))
            output_path.write_text(json.dumps({"run_id": self.run_id, "results": rows}, indent=2), encoding="utf-8")
        return {"run_id": self.run_id, "output": str(output_path), "results": rows}

    def _run_model(self, model: dict[str, Any]) -> dict[str, Any]:
        config = self._config_for_model(model)
        row: dict[str, Any] = {
            "name": model["name"],
            "provider": config.embedding.provider,
            "model": config.embedding.model,
            "collection": config.storage.qdrant.collection,
            "dataset": str(config.evaluation.dataset),
            "index": {},
            "evaluations": [],
        }
        vector_store = create_vector_store(config)
        try:
            if bool(model.get("reindex", self.suite.get("reindex", True))) or not vector_store.exists():
                close_vector_store(vector_store)
                started = time.perf_counter()
                provider = make_embedding_provider(config)
                indexing_service = make_indexing_service(config)
                items = indexing_service.build(config.root, provider, plugin_config={"config": config})
                if config.graph.enabled:
                    from code_diver.cli import make_graph_indexer

                    graph_indexer = make_graph_indexer(config)
                    if graph_indexer is not None:
                        graph_indexer(items)
                index_duration_ms = (time.perf_counter() - started) * 1000
                row["index"] = {
                    "duration_ms": index_duration_ms,
                    "indexed_items": len(items),
                    "unique_paths": len({item.path for item in items}),
                    "composition": IndexCompositionAnalyzer().analyze(items),
                    "estimated_input_tokens": self._estimated_tokens(items, config.embedding.max_input_chars),
                    "estimated_cost_usd": self._estimated_cost(items, model, config.embedding.max_input_chars),
                }
                close_vector_store(indexing_service.vector_store)
                vector_store = create_vector_store(config)
            count_items = getattr(vector_store, "count_items", None)
            if callable(count_items):
                row["index"]["stored_items"] = count_items()
            provider = QueryCachingEmbeddingProvider(make_embedding_provider(config, vector_store.metadata()))
            cases = DatasetLoader().load(config.evaluation.dataset)
            plugin_manager = make_plugin_manager(config)
            for case in cases:
                case.query = plugin_manager.prepare_query(case.query)
            for strategy_name, strategy_config in self._strategy_configs(config):
                trace_offset = self._trace_size(strategy_config.trace.artifact)
                started = time.perf_counter()
                metrics, _ = EvaluationService(
                    make_retrieval_strategy(strategy_config, provider, vector_store)
                ).evaluate(
                    cases,
                    config.evaluation.limit,
                    workers=strategy_config.evaluation.workers,
                )
                metrics["duration_ms"] = (time.perf_counter() - started) * 1000
                metrics["llm_usage"] = self._llm_usage(strategy_config.trace.artifact, trace_offset)
                row["evaluations"].append({"strategy": strategy_name, "metrics": metrics})
        except Exception as exc:
            row["error"] = str(exc)
        finally:
            close_vector_store(vector_store)
        return row

    def _strategy_configs(self, config: Any):
        if self.suite.get("hypotheses"):
            hypotheses = {hypothesis.name: hypothesis for hypothesis in config.experiments.hypotheses}
            for hypothesis_name in self.suite["hypotheses"]:
                hypothesis = hypotheses.get(hypothesis_name)
                if hypothesis is None:
                    raise ValueError(f"Unknown experiment hypothesis: {hypothesis_name}")
                yield hypothesis_name, self._apply_search_config_overrides(
                    config_for_search_hypothesis(config, hypothesis)
                )
            return
        for strategy_name in self.suite.get("strategies", ["hybrid"]):
            yield strategy_name, self._apply_search_config_overrides(
                replace(config, search=replace(config.search, strategy=strategy_name))
            )

    def _apply_search_config_overrides(self, config: Any) -> Any:
        return self._apply_config_overrides(config, self.suite.get("search_config_overrides") or {})

    def _config_for_model(self, model: dict[str, Any]):
        embedding = replace(
            self.base_config.embedding,
            provider=str(model.get("provider", self.base_config.embedding.provider)),
            model=str(model.get("model", self.base_config.embedding.model)),
            dimensions=self._optional_int(model.get("dimensions", self.base_config.embedding.dimensions)),
            api_key=model.get("api_key", self.base_config.embedding.api_key),
            project=model.get("project", self.base_config.embedding.project),
            location=model.get("location", self.base_config.embedding.location),
            url=model.get("url", self.base_config.embedding.url),
            batch_size=int(model.get("batch_size", self.base_config.embedding.batch_size)),
            workers=int(model.get("workers", self.base_config.embedding.workers)),
            max_input_chars=self._optional_int(model.get("max_input_chars", self.base_config.embedding.max_input_chars)),
            document_prefix=model.get("document_prefix", self.base_config.embedding.document_prefix),
            query_prefix=model.get("query_prefix", self.base_config.embedding.query_prefix),
        )
        qdrant = replace(
            self.base_config.storage.qdrant,
            collection=f"{self.base_config.storage.qdrant.collection}_{model['name']}_{self.run_id}",
        )
        storage = replace(self.base_config.storage, qdrant=qdrant)
        graph = replace(
            self.base_config.graph,
            artifact=self.base_config.graph.artifact.with_name(
                f"{self.base_config.graph.artifact.stem}_{model['name']}_{self.run_id}{self.base_config.graph.artifact.suffix}"
            ),
        )
        trace = replace(
            self.base_config.trace,
            artifact=self.base_config.trace.artifact.with_name(
                f"{self.base_config.trace.artifact.stem}_{model['name']}_{self.run_id}{self.base_config.trace.artifact.suffix}"
            ),
        )
        artifact = self.base_config.artifact.with_name(
            f"{self.base_config.artifact.stem}_{model['name']}_{self.run_id}{self.base_config.artifact.suffix}"
        )
        return replace(self.base_config, artifact=artifact, embedding=embedding, storage=storage, graph=graph, trace=trace)

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

    def _optional_int(self, value: Any) -> int | None:
        if value is None or value == "":
            return None
        return int(value)

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
                payload = record.get("payload") or {}
                event = record.get("event")
                if event == "llm_rerank_response":
                    usage["calls"] += 1
                    usage["input_tokens"] += int(payload.get("input_tokens") or 0)
                    usage["output_tokens"] += int(payload.get("output_tokens") or 0)
                    usage["total_tokens"] += int(payload.get("total_tokens") or 0)
                    usage["estimated_cost_usd"] += float(payload.get("estimated_cost") or 0.0)
                    usage["duration_ms"] += float(payload.get("duration_ms") or 0.0)
                elif event == "llm_rerank_error":
                    usage["errors"] += 1
                    usage["duration_ms"] += float(payload.get("duration_ms") or 0.0)
        return usage


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--only", action="append", default=[])
    args = parser.parse_args()
    result = EmbeddingBenchmarkRunner(args.suite).run(set(args.only) if args.only else None)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
