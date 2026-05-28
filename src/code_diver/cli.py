from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from .config import AppConfig, ConfigLoader
from .ai_indexing import AiCodebaseScanner, HybridCodebaseScanner
from .domain import SearchResult
from .env import EnvFileLoader
from .experiments import ExperimentRunner
from .generation import create_generation_provider
from .graph import CodeGraphBuilder, CodeGraphStore
from .inspection import GrepService, RgService, TreeService
from .metrics import ClickHouseClient, ClickHouseDockerClient, ClickHouseMetricsRepository, ExperimentMetricsMapper
from .orchestration import OrchestratedCodebaseScanner
from .pi import PiRunner
from .plugins import PluginManager
from .providers import create_embedding_provider
from .settings import (
    CommandName,
    Defaults,
    OptionName,
    SchemaKey,
    VectorStoreProviderId,
)
from .services import CodebaseScanner, DatasetLoader, GraphIndexingService, IndexingService
from .services.evaluation_service import EvaluationService
from .strategies import RetrievalStrategyFactory
from .store import create_vector_store
from .ui import EditorOpener, SearchRenderer


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = ConfigLoader().load(args.config)
        EnvFileLoader().load(config.env_file.path, config.env_file.override)
        return int(args.func(args, config))
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="code-diver", description="Config-first codebase RAG CLI.")
    parser.add_argument(OptionName.CONFIG.value, type=Path, default=None, help="YAML config path.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    index = subparsers.add_parser(CommandName.INDEX.value, help="Index repository code into the configured artifact.")
    index.set_defaults(func=cmd_index)

    search = subparsers.add_parser(CommandName.SEARCH.value, help="Search indexed code.")
    search.add_argument("query")
    search.add_argument(OptionName.LIMIT.value, type=int, default=None)
    search.add_argument(OptionName.JSON.value, action="store_true")
    search.set_defaults(func=cmd_search)

    tree = subparsers.add_parser(CommandName.TREE.value, help="Print a gitignore-aware repository tree.")
    tree.add_argument(OptionName.PATH.value, default=None)
    tree.add_argument(OptionName.LIMIT.value, type=int, default=200)
    tree.add_argument("--depth", type=int, default=3)
    tree.set_defaults(func=cmd_tree)

    grep = subparsers.add_parser(CommandName.GREP.value, help="Literal gitignore-aware text search.")
    grep.add_argument("pattern")
    grep.add_argument(OptionName.PATH.value, default=None)
    grep.add_argument(OptionName.LIMIT.value, type=int, default=100)
    grep.set_defaults(func=cmd_grep)

    rg = subparsers.add_parser(CommandName.RG.value, help="Regex gitignore-aware text search via rg.")
    rg.add_argument("pattern")
    rg.add_argument(OptionName.PATH.value, default=None)
    rg.add_argument(OptionName.LIMIT.value, type=int, default=100)
    rg.set_defaults(func=cmd_rg)

    open_result = subparsers.add_parser(
        CommandName.OPEN.value, help="Open the best search result in the configured editor."
    )
    open_result.add_argument("query")
    open_result.add_argument(OptionName.RANK.value, type=int, default=1)
    open_result.set_defaults(func=cmd_open)

    chat = subparsers.add_parser(CommandName.CHAT.value, help="Start Pi with Code Diver RAG tools loaded.")
    chat.add_argument("prompt", nargs="?", default=None)
    chat.set_defaults(func=cmd_chat)

    ask = subparsers.add_parser(CommandName.ASK.value, help="Ask Pi once with Code Diver RAG tools loaded.")
    ask.add_argument("query")
    ask.set_defaults(func=cmd_ask)

    evaluate = subparsers.add_parser(CommandName.EVALUATE.value, help="Evaluate retrieval on the configured dataset.")
    evaluate.add_argument(OptionName.DATASET.value, type=Path, default=None)
    evaluate.add_argument(OptionName.LIMIT.value, type=int, default=None)
    evaluate.add_argument(OptionName.DETAILS.value, action="store_true")
    evaluate.add_argument(OptionName.JSON.value, action="store_true")
    evaluate.add_argument(OptionName.REINDEX.value, action="store_true")
    evaluate.set_defaults(func=cmd_evaluate)

    experiment = subparsers.add_parser(
        CommandName.EXPERIMENT.value,
        help="Run configured retrieval hypotheses and optionally record metrics.",
    )
    experiment.add_argument(OptionName.JSON.value, action="store_true")
    experiment.add_argument(OptionName.REINDEX.value, action="store_true")
    experiment.set_defaults(func=cmd_experiment)

    return parser


def cmd_index(_: argparse.Namespace, config: AppConfig) -> int:
    provider = make_embedding_provider(config)
    items = make_indexing_service(config).build(
        root=config.root,
        provider=provider,
        plugin_config={"config": config},
    )
    if config.graph.enabled:
        GraphIndexingService(CodeGraphBuilder(), CodeGraphStore(config.graph.artifact)).build(config.root, items)
    print(
        f"Indexed {len(items)} items -> {store_label(config)} "
        f"({provider.name}, model={provider.model}, dimensions={provider.dimensions})"
    )
    return 0


def cmd_search(args: argparse.Namespace, config: AppConfig) -> int:
    results = run_search(config, args.query, args.limit or config.search.limit)
    if args.json:
        print(json.dumps([result_to_json(result) for result in results], indent=2))
    else:
        SearchRenderer(config.root, config.ui, config.search.preview_lines).render(args.query, results)
    return 0


def cmd_tree(args: argparse.Namespace, config: AppConfig) -> int:
    print(TreeService(config.root).render(path=args.path, max_depth=args.depth, limit=args.limit))
    return 0


def cmd_grep(args: argparse.Namespace, config: AppConfig) -> int:
    print(GrepService(config.root).render(args.pattern, path=args.path, limit=args.limit))
    return 0


def cmd_rg(args: argparse.Namespace, config: AppConfig) -> int:
    print(RgService(config.root).search(args.pattern, path=args.path, limit=args.limit))
    return 0


def cmd_open(args: argparse.Namespace, config: AppConfig) -> int:
    rank = max(int(args.rank), 1)
    limit = max(rank, config.search.limit)
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
    vector_store = create_vector_store(config)
    if args.reindex or not vector_store.exists():
        cmd_index(args, config)
        vector_store = create_vector_store(config)

    dataset = args.dataset or config.evaluation.dataset
    limit = args.limit or config.evaluation.limit
    provider = make_embedding_provider(config, vector_store.metadata())
    plugin_manager = make_plugin_manager(config)
    cases = DatasetLoader().load(dataset)
    for case in cases:
        case.query = plugin_manager.prepare_query(case.query)

    strategy = make_retrieval_strategy(config, provider, vector_store)
    metrics, results = EvaluationService(strategy).evaluate(cases, limit)
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


def cmd_experiment(args: argparse.Namespace, config: AppConfig) -> int:
    vector_store = create_vector_store(config)
    if args.reindex or not vector_store.exists():
        cmd_index(args, config)
        vector_store = create_vector_store(config)

    provider = make_embedding_provider(config, vector_store.metadata())
    plugin_manager = make_plugin_manager(config)
    cases = DatasetLoader().load(config.evaluation.dataset)
    for case in cases:
        case.query = plugin_manager.prepare_query(case.query)

    run_id = uuid.uuid4().hex
    experiment_run = ExperimentRunner(
        RetrievalStrategyFactory(),
        provider,
        vector_store,
    ).run(run_id, config, cases)

    saved_rows = 0
    if config.metrics.enabled:
        repository = make_metrics_repository(config)
        repository.ensure_schema()
        metric_rows, case_rows = ExperimentMetricsMapper().to_rows(experiment_run, config, args.config)
        repository.save(metric_rows, case_rows)
        saved_rows = len(metric_rows) + len(case_rows)

    if args.json:
        print(json.dumps(experiment_run_to_json(experiment_run, saved_rows), indent=2))
        return 0

    print(f"run_id: {experiment_run.run_id}")
    print(f"suite: {experiment_run.suite}")
    for strategy_result in experiment_run.strategy_results:
        print()
        print(f"{strategy_result.strategy}:")
        for name, value in strategy_result.metrics.items():
            print(f"  {name}: {value:.4f}" if isinstance(value, float) else f"  {name}: {value}")
    if config.metrics.enabled:
        print(f"\nrecorded_rows: {saved_rows}")
    return 0


def run_search(config: AppConfig, query: str, limit: int) -> list[SearchResult]:
    vector_store = create_vector_store(config)
    provider = make_embedding_provider(config, vector_store.metadata())
    prepared_query = make_plugin_manager(config).prepare_query(query)
    return make_retrieval_strategy(config, provider, vector_store).search(prepared_query, limit)


def make_indexing_service(config: AppConfig) -> IndexingService:
    return IndexingService(make_codebase_scanner(config), make_plugin_manager(config), create_vector_store(config))


def make_codebase_scanner(config: AppConfig):
    scanner = CodebaseScanner(
        include=config.scanner.include,
        exclude=config.scanner.exclude,
        max_file_bytes=config.scanner.max_file_bytes,
        chunk_lines=config.scanner.chunk_lines,
    )
    mode = config.indexing.mode
    if mode == "scanner":
        return scanner
    if mode == "orchestrated":
        return OrchestratedCodebaseScanner(scanner, create_generation_provider(config), config)
    ai_scanner = AiCodebaseScanner(scanner, create_generation_provider(config), config.indexing.ai)
    if mode == "ai":
        return ai_scanner
    if mode == "hybrid":
        return HybridCodebaseScanner([scanner, ai_scanner])
    raise ValueError(f"Unknown indexing mode: {mode}")


def make_plugin_manager(config: AppConfig) -> PluginManager:
    return PluginManager([Path(path) for path in config.plugins])


def make_embedding_provider(config: AppConfig, payload: dict[str, Any] | None = None):
    embedding = config.embedding
    provider_name = embedding.provider or str((payload or {}).get(SchemaKey.PROVIDER.value, Defaults.EMBEDDING_PROVIDER))
    model = embedding.model or (payload or {}).get(SchemaKey.MODEL.value)
    dimensions = embedding.dimensions or (payload or {}).get(SchemaKey.DIMENSIONS.value)
    return create_embedding_provider(
        provider_name,
        model=model,
        dimensions=int(dimensions) if dimensions else None,
        api_key=embedding.api_key,
        url=embedding.url,
        batch_size=embedding.batch_size,
        retry_attempts=embedding.retry_attempts,
        retry_delay_seconds=embedding.retry_delay_seconds,
    )


def make_retrieval_strategy(config: AppConfig, provider: Any, vector_store: Any):
    return RetrievalStrategyFactory().create(config.search.strategy, config, provider, vector_store)


def make_metrics_repository(config: AppConfig) -> ClickHouseMetricsRepository:
    metrics = config.metrics
    if metrics.docker_container:
        client = ClickHouseDockerClient(
            metrics.docker_container,
            metrics.username,
            metrics.password,
            metrics.timeout_seconds,
        )
    else:
        client = ClickHouseClient(metrics.url, metrics.username, metrics.password, metrics.timeout_seconds)
    return ClickHouseMetricsRepository(
        client,
        database=metrics.database,
        metrics_table=metrics.metrics_table,
        cases_table=metrics.cases_table,
        retention_days=metrics.retention_days,
    )


def store_label(config: AppConfig) -> str:
    provider = config.storage.provider
    if provider == VectorStoreProviderId.QDRANT.value:
        return f"{provider}:{config.storage.qdrant.collection}"
    return str(config.artifact)


def result_to_json(result: SearchResult) -> dict[str, Any]:
    return {SchemaKey.SCORE.value: result.score, SchemaKey.ITEM.value: result.item.to_json()}


def eval_result_to_json(result: Any) -> dict[str, Any]:
    return {
        "case_id": result.case_id,
        SchemaKey.QUERY.value: result.query,
        SchemaKey.EXPECTED.value: result.expected,
        SchemaKey.RETRIEVED.value: result.retrieved,
        SchemaKey.HIT.value: result.hit,
        SchemaKey.RECIPROCAL_RANK.value: result.reciprocal_rank,
        SchemaKey.PRECISION.value: result.precision,
        SchemaKey.RECALL.value: result.recall,
    }


def experiment_run_to_json(run: Any, saved_rows: int) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "suite": run.suite,
        "recorded_rows": saved_rows,
        "strategies": [
            {
                "strategy": strategy_result.strategy,
                "metrics": strategy_result.metrics,
                "results": [eval_result_to_json(result) for result in strategy_result.results],
            }
            for strategy_result in run.strategy_results
        ],
    }
