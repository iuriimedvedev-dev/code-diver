from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .config import AppConfig, ConfigLoader
from .domain import SearchResult
from .pi import PiRunner
from .plugins import PluginManager
from .providers import create_embedding_provider
from .services import (
    CodebaseScanner,
    DatasetLoader,
    EvaluationService,
    IndexingService,
    RetrievalService,
)
from .store import IndexStore
from .ui import EditorOpener, SearchRenderer


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = ConfigLoader().load(args.config)
        return int(args.func(args, config))
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="code-diver", description="Config-first codebase RAG CLI.")
    parser.add_argument("--config", type=Path, default=None, help="YAML config path. Defaults to code-diver.yml.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    index = subparsers.add_parser("index", help="Index repository code into the configured artifact.")
    index.set_defaults(func=cmd_index)

    search = subparsers.add_parser("search", help="Search indexed code.")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=None)
    search.add_argument("--json", action="store_true")
    search.set_defaults(func=cmd_search)

    open_result = subparsers.add_parser("open", help="Open the best search result in the configured editor.")
    open_result.add_argument("query")
    open_result.add_argument("--rank", type=int, default=1)
    open_result.set_defaults(func=cmd_open)

    chat = subparsers.add_parser("chat", help="Start Pi with Code Diver RAG tools loaded.")
    chat.add_argument("prompt", nargs="?", default=None)
    chat.set_defaults(func=cmd_chat)

    ask = subparsers.add_parser("ask", help="Ask Pi once with Code Diver RAG tools loaded.")
    ask.add_argument("query")
    ask.set_defaults(func=cmd_ask)

    evaluate = subparsers.add_parser("evaluate", help="Evaluate retrieval on the configured dataset.")
    evaluate.add_argument("--dataset", type=Path, default=None)
    evaluate.add_argument("--limit", type=int, default=None)
    evaluate.add_argument("--details", action="store_true")
    evaluate.add_argument("--json", action="store_true")
    evaluate.add_argument("--reindex", action="store_true")
    evaluate.set_defaults(func=cmd_evaluate)

    return parser


def cmd_index(_: argparse.Namespace, config: AppConfig) -> int:
    provider = make_embedding_provider(config)
    items = make_indexing_service(config).build(
        root=config.root,
        artifact=config.artifact,
        provider=provider,
        plugin_config={"config": config},
    )
    print(
        f"Indexed {len(items)} items -> {config.artifact} "
        f"({provider.name}, model={provider.model}, dimensions={provider.dimensions})"
    )
    return 0


def cmd_search(args: argparse.Namespace, config: AppConfig) -> int:
    results = run_search(config, args.query, _limit(args.limit, config.search, "limit", 10))
    if args.json:
        print(json.dumps([result_to_json(result) for result in results], indent=2))
    else:
        SearchRenderer(config.root, search_ui_config(config)).render(args.query, results)
    return 0


def cmd_open(args: argparse.Namespace, config: AppConfig) -> int:
    rank = max(int(args.rank), 1)
    limit = max(rank, _limit(None, config.search, "limit", 10))
    results = run_search(config, args.query, limit)
    if not results:
        print("No search results.")
        return 1
    if rank > len(results):
        print(f"Only {len(results)} search results available.")
        return 1
    result = results[rank - 1]
    command_line = EditorOpener(config.root, config.ui).open(result)
    location = result.item.path
    if result.item.start_line is not None:
        location = f"{location}:{result.item.start_line}"
    print(f"Opened {location} with: {' '.join(command_line)}")
    return 0


def cmd_ask(args: argparse.Namespace, config: AppConfig) -> int:
    return PiRunner().run_print(config, args.config, args.query)


def cmd_chat(args: argparse.Namespace, config: AppConfig) -> int:
    return PiRunner().run_interactive(config, args.config, args.prompt)


def cmd_evaluate(args: argparse.Namespace, config: AppConfig) -> int:
    if args.reindex or not config.artifact.exists():
        cmd_index(args, config)

    dataset = args.dataset or Path(config.evaluation.get("dataset", "datasets/sample_eval.jsonl"))
    limit = _limit(args.limit, config.evaluation, "limit", 10)
    store = IndexStore()
    payload, items, vectors = store.load_items_and_vectors(config.artifact)
    provider = make_embedding_provider(config, payload)
    plugin_manager = make_plugin_manager(config)
    cases = DatasetLoader().load(dataset)
    for case in cases:
        case.query = plugin_manager.prepare_query(case.query)

    metrics, results = EvaluationService().evaluate(cases, provider, items, vectors, limit)
    if args.json:
        print(json.dumps({"metrics": metrics, "results": [eval_result_to_json(result) for result in results]}, indent=2))
        return 0

    for name, value in metrics.items():
        print(f"{name}: {value:.4f}" if isinstance(value, float) else f"{name}: {value}")
    if args.details:
        print()
        for result in results:
            status = "hit" if result.hit else "miss"
            print(f"{result.case_id}: {status} rr={result.reciprocal_rank:.4f}")
            print(f"  query: {result.query}")
            print(f"  expected: {', '.join(result.expected)}")
            print(f"  top: {', '.join(result.retrieved[:3])}")
    return 0


def run_search(config: AppConfig, query: str, limit: int) -> list[SearchResult]:
    payload, items, vectors = IndexStore().load_items_and_vectors(config.artifact)
    provider = make_embedding_provider(config, payload)
    prepared_query = make_plugin_manager(config).prepare_query(query)
    return RetrievalService().search(provider, prepared_query, items, vectors, limit)


def make_indexing_service(config: AppConfig) -> IndexingService:
    scanner_config = config.scanner
    scanner = CodebaseScanner(
        include=list(scanner_config.get("include") or []),
        exclude=list(scanner_config.get("exclude") or []),
        max_file_bytes=int(scanner_config.get("max_file_bytes", 1_000_000)),
        chunk_lines=int(scanner_config.get("chunk_lines", 120)),
    )
    return IndexingService(scanner, make_plugin_manager(config), IndexStore())


def make_plugin_manager(config: AppConfig) -> PluginManager:
    return PluginManager([Path(path) for path in config.plugins])


def make_embedding_provider(config: AppConfig, payload: dict[str, Any] | None = None):
    embedding = config.embedding
    provider_name = str(embedding.get("provider") or (payload or {}).get("provider") or "gemini")
    model = embedding.get("model") or (payload or {}).get("model")
    dimensions = embedding.get("dimensions") or (payload or {}).get("dimensions")
    return create_embedding_provider(
        provider_name,
        model=model,
        dimensions=int(dimensions) if dimensions else None,
        api_key=embedding.get("api_key"),
        batch_size=int(embedding.get("batch_size", 32)),
    )


def search_ui_config(config: AppConfig) -> dict[str, Any]:
    ui_config = dict(config.ui)
    ui_config["preview_lines"] = config.search.get("preview_lines", ui_config.get("preview_lines", 8))
    return ui_config


def result_to_json(result: SearchResult) -> dict[str, Any]:
    return {"score": result.score, "item": result.item.to_json()}


def eval_result_to_json(result: Any) -> dict[str, Any]:
    return {
        "case_id": result.case_id,
        "query": result.query,
        "expected": result.expected,
        "retrieved": result.retrieved,
        "hit": result.hit,
        "reciprocal_rank": result.reciprocal_rank,
        "precision": result.precision,
        "recall": result.recall,
    }


def _limit(value: int | None, config: dict[str, Any], key: str, default: int) -> int:
    return int(value if value is not None else config.get(key, default))
