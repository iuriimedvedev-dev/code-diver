from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from typing import Any

from .config import AppConfig, ConfigLoader
from .ai_indexing import AiCodebaseScanner, HybridCodebaseScanner
from .domain import SearchResult
from .env import EnvFileLoader
from .experiments import ExperimentRunner
from .generation import create_generation_provider
from .graph import CodeGraphBuilder, CodeGraphStore
from .inspection import GrepService, ReadExcerptService, RgService, SymbolsService, TreeService
from .metrics import ClickHouseClient, ClickHouseDockerClient, ClickHouseMetricsRepository, ExperimentMetricsMapper
from .orchestration import OrchestratedCodebaseScanner
from .pi import PiRunLogParser, PiRunner
from .plugins import PluginManager
from .providers import create_embedding_provider
from .settings import (
    CommandName,
    Defaults,
    OptionName,
    SchemaKey,
    VectorStoreProviderId,
)
from .services import (
    CodebaseScanner,
    DatasetLoader,
    GraphIndexingService,
    IndexingOptions,
    IndexingService,
    SelectedCodeItemBuilder,
    SelectedIndexPayloadParser,
    SelectedIndexingService,
)
from .services.evaluation_service import EvaluationService
from .strategies import RetrievalStrategyFactory
from .store import create_vector_store
from .tracing import TraceLogger
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

    index_selected = subparsers.add_parser(
        CommandName.INDEX_SELECTED.value,
        help="Index agent-selected file ranges from a JSON payload on stdin.",
    )
    index_selected.add_argument(OptionName.JSON.value, action="store_true")
    index_selected.set_defaults(func=cmd_index_selected)

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

    read = subparsers.add_parser(CommandName.READ.value, help="Read a bounded, gitignore-aware file excerpt.")
    read.add_argument("file")
    read.add_argument(OptionName.START_LINE.value, type=int, default=1)
    read.add_argument(OptionName.LINES.value, type=int, default=80)
    read.set_defaults(func=cmd_read)

    symbols = subparsers.add_parser(CommandName.SYMBOLS.value, help="List parsed source symbols.")
    symbols.add_argument(OptionName.PATH.value, default=None)
    symbols.add_argument(OptionName.LIMIT.value, type=int, default=200)
    symbols.set_defaults(func=cmd_symbols)

    open_result = subparsers.add_parser(
        CommandName.OPEN.value, help="Open the best search result in the configured editor."
    )
    open_result.add_argument("query")
    open_result.add_argument(OptionName.RANK.value, type=int, default=1)
    open_result.set_defaults(func=cmd_open)

    chat = subparsers.add_parser(CommandName.CHAT.value, help="Start Pi with Code Diver RAG tools loaded.")
    chat.add_argument("prompt", nargs="?", default=None)
    chat.add_argument(OptionName.TOOLSET.value, default=None)
    chat.add_argument(OptionName.HYPOTHESIS.value, default=None)
    chat.set_defaults(func=cmd_chat)

    ask = subparsers.add_parser(CommandName.ASK.value, help="Ask Pi once with Code Diver RAG tools loaded.")
    ask.add_argument("query")
    ask.add_argument(OptionName.TOOLSET.value, default=None)
    ask.add_argument(OptionName.HYPOTHESIS.value, default=None)
    ask.set_defaults(func=cmd_ask)

    evaluate = subparsers.add_parser(CommandName.EVALUATE.value, help="Evaluate retrieval on the configured dataset.")
    evaluate.add_argument(OptionName.DATASET.value, type=Path, default=None)
    evaluate.add_argument(OptionName.LIMIT.value, type=int, default=None)
    evaluate.add_argument(OptionName.DETAILS.value, action="store_true")
    evaluate.add_argument(OptionName.JSON.value, action="store_true")
    evaluate.add_argument(OptionName.REINDEX.value, action="store_true")
    evaluate.set_defaults(func=cmd_evaluate)

    evaluate_indexing = subparsers.add_parser(
        CommandName.EVALUATE_INDEXING.value,
        help="Ask Pi indexing hypotheses to build isolated indexes, then evaluate retrieval metrics.",
    )
    evaluate_indexing.add_argument(OptionName.LIMIT.value, type=int, default=None)
    evaluate_indexing.add_argument(OptionName.HYPOTHESIS.value, action="append", default=[])
    evaluate_indexing.add_argument(OptionName.DETAILS.value, action="store_true")
    evaluate_indexing.add_argument(OptionName.JSON.value, action="store_true")
    evaluate_indexing.set_defaults(func=cmd_evaluate_indexing)

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
    indexing_service = make_indexing_service(config)
    items = indexing_service.build(
        root=config.root,
        provider=provider,
        plugin_config={"config": config},
    )
    if config.graph.enabled:
        GraphIndexingService(
            CodeGraphBuilder(ast_enabled=config.graph.ast_enabled),
            CodeGraphStore(config.graph.artifact),
        ).build(
            config.root,
            items,
        )
    print(
        f"Indexed {len(items)} items -> {store_label(config)} "
        f"({provider.name}, model={provider.model}, dimensions={provider.dimensions})"
    )
    close_vector_store(indexing_service.vector_store)
    return 0


def cmd_index_selected(args: argparse.Namespace, config: AppConfig) -> int:
    selections = SelectedIndexPayloadParser().parse(sys.stdin.read())
    built = SelectedCodeItemBuilder(config.root, config.scanner.chunk_lines).build(selections)
    if not built.items:
        payload = {"indexed": 0, "skipped": built.skipped, "store": store_label(config), "items": []}
        print(json.dumps(payload, indent=2) if args.json else "Indexed 0 selected items.")
        return 0
    provider = make_embedding_provider(config)
    service = SelectedIndexingService(
        create_vector_store(config),
        IndexingOptions(
            embedding_batch_size=config.embedding.batch_size,
            embedding_workers=config.embedding.workers,
            embedding_max_input_chars=config.embedding.max_input_chars,
            progress=True,
        ),
        make_trace_logger(config),
    )
    items = service.build(config.root, provider, built.items)
    if config.graph.enabled:
        GraphIndexingService(
            CodeGraphBuilder(ast_enabled=config.graph.ast_enabled),
            CodeGraphStore(config.graph.artifact),
        ).build(config.root, items)
    close_vector_store(service.vector_store)
    payload = {
        "indexed": len(items),
        "skipped": built.skipped,
        "store": store_label(config),
        "items": [item.to_json() for item in items],
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Indexed {len(items)} selected items -> {store_label(config)}")
        for skipped in built.skipped:
            print(f"skipped: {skipped}", file=sys.stderr)
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


def cmd_read(args: argparse.Namespace, config: AppConfig) -> int:
    print(ReadExcerptService(config.root).render(args.file, start_line=args.start_line, lines=args.lines))
    return 0


def cmd_symbols(args: argparse.Namespace, config: AppConfig) -> int:
    print(SymbolsService(config.root).render(path=args.path, limit=args.limit))
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
    return PiRunner().run_print(config, args.config, args.query, toolset=args.toolset, hypothesis=args.hypothesis)


def cmd_chat(args: argparse.Namespace, config: AppConfig) -> int:
    return PiRunner().run_interactive(config, args.config, args.prompt, toolset=args.toolset, hypothesis=args.hypothesis)


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


def cmd_evaluate_indexing(args: argparse.Namespace, config: AppConfig) -> int:
    cases = DatasetLoader().load(config.evaluation.dataset)
    limit = args.limit or config.evaluation.limit
    run_id = uuid.uuid4().hex[:12]
    rows: list[dict[str, Any]] = []
    for hypothesis in indexing_hypotheses(config, args.hypothesis):
        eval_config = config_for_indexing_hypothesis(config, hypothesis.name, run_id)
        log_path = indexing_hypothesis_log_path(config, hypothesis.name, run_id)
        prompt = indexing_hypothesis_prompt(hypothesis.name, cases)
        started = perf_counter()
        exit_code = PiRunner().run_print_logged(
            eval_config,
            args.config,
            prompt,
            log_path,
            hypothesis=hypothesis.name,
        )
        indexing_duration_ms = (perf_counter() - started) * 1000
        pi_usage = PiRunLogParser().parse(log_path)
        row: dict[str, Any] = {
            "hypothesis": hypothesis.name,
            "collection": eval_config.storage.qdrant.collection,
            "tools": resolve_hypothesis_tools(config, hypothesis.name),
            "log_path": str(log_path),
            "indexing_exit_code": exit_code,
            "indexing_duration_ms": indexing_duration_ms,
            "pi_usage": pi_usage.to_json(),
        }
        if exit_code != 0:
            row["error"] = "pi_indexing_failed"
            rows.append(row)
            continue
        vector_store = create_vector_store(eval_config)
        if not vector_store.exists():
            row["error"] = "index_not_found"
            close_vector_store(vector_store)
            rows.append(row)
            continue
        count_items = getattr(vector_store, "count_items", None)
        if callable(count_items):
            row["indexed_items"] = count_items()
        provider = make_embedding_provider(eval_config, vector_store.metadata())
        strategy = make_retrieval_strategy(eval_config, provider, vector_store)
        eval_started = perf_counter()
        metrics, results = EvaluationService(strategy).evaluate(cases, limit)
        metrics["evaluation_duration_ms"] = (perf_counter() - eval_started) * 1000
        row["metrics"] = metrics
        if args.details:
            row["results"] = [eval_result_to_json(result) for result in results]
        close_vector_store(vector_store)
        rows.append(row)

    if args.json:
        print(json.dumps({"run_id": run_id, "results": rows}, indent=2))
        return 0

    print(f"run_id: {run_id}")
    for row in rows:
        print()
        print(f"{row['hypothesis']} ({row['collection']})")
        print(f"  tools: {', '.join(row['tools'])}")
        print(f"  log_path: {row['log_path']}")
        print(f"  indexing_duration_ms: {row['indexing_duration_ms']:.1f}")
        usage = row["pi_usage"]
        print(
            "  pi_usage: "
            f"tokens={usage['total_tokens']} "
            f"input={usage['input_tokens']} output={usage['output_tokens']} "
            f"cost=${usage['total_cost']:.6f} tool_calls={usage['tool_calls']}"
        )
        if row.get("error"):
            print(f"  error: {row['error']} exit_code={row['indexing_exit_code']}")
            continue
        print(f"  indexed_items: {row.get('indexed_items', 'unknown')}")
        for name, value in row["metrics"].items():
            print(f"  {name}: {value:.4f}" if isinstance(value, float) else f"  {name}: {value}")
    return 0


def cmd_experiment(args: argparse.Namespace, config: AppConfig) -> int:
    vector_store = None if args.reindex else create_vector_store(config)
    needs_index = args.reindex or not vector_store.exists()
    if needs_index:
        if vector_store is not None:
            close_vector_store(vector_store)
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
    return IndexingService(
        make_codebase_scanner(config),
        make_plugin_manager(config),
        create_vector_store(config),
        IndexingOptions(
            embedding_batch_size=config.embedding.batch_size,
            embedding_workers=config.embedding.workers,
            embedding_max_input_chars=config.embedding.max_input_chars,
            progress=True,
        ),
        make_trace_logger(config),
    )


def make_codebase_scanner(config: AppConfig):
    scanner = CodebaseScanner(
        include=config.scanner.include,
        exclude=config.scanner.exclude,
        max_file_bytes=config.scanner.max_file_bytes,
        chunk_lines=config.scanner.chunk_lines,
        symbol_chunks=config.scanner.symbol_chunks,
    )
    mode = config.indexing.mode
    if mode == "scanner":
        return scanner
    if mode == "orchestrated":
        return OrchestratedCodebaseScanner(scanner, create_generation_provider(config), config, make_trace_logger(config))
    ai_scanner = AiCodebaseScanner(scanner, create_generation_provider(config), config.indexing.ai)
    if mode == "ai":
        return ai_scanner
    if mode == "hybrid":
        return HybridCodebaseScanner([scanner, ai_scanner])
    raise ValueError(f"Unknown indexing mode: {mode}")


def make_plugin_manager(config: AppConfig) -> PluginManager:
    return PluginManager([Path(path) for path in config.plugins])


def make_trace_logger(config: AppConfig) -> TraceLogger:
    return TraceLogger(config.trace)


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
        project=embedding.project,
        location=embedding.location,
        batch_size=embedding.batch_size,
        retry_attempts=embedding.retry_attempts,
        retry_delay_seconds=embedding.retry_delay_seconds,
    )


def make_retrieval_strategy(config: AppConfig, provider: Any, vector_store: Any):
    return RetrievalStrategyFactory().create(config.search.strategy, config, provider, vector_store)


def indexing_hypotheses(config: AppConfig, names: list[str] | None = None):
    selected_names = set(names or [])
    return [
        hypothesis
        for hypothesis in config.experiments.hypotheses
        if not selected_names or hypothesis.name in selected_names
        if "code_diver_index_selected" in resolve_hypothesis_tools(config, hypothesis.name)
    ]


def resolve_hypothesis_tools(config: AppConfig, hypothesis_name: str) -> list[str]:
    hypothesis = next(
        (candidate for candidate in config.experiments.hypotheses if candidate.name == hypothesis_name),
        None,
    )
    if hypothesis is None:
        return []
    if hypothesis.tools:
        return hypothesis.tools
    if hypothesis.toolset:
        return config.pi.toolsets.get(hypothesis.toolset, [])
    return config.pi.tools


def config_for_indexing_hypothesis(config: AppConfig, hypothesis_name: str, run_id: str) -> AppConfig:
    qdrant = replace(
        config.storage.qdrant,
        collection=f"{config.storage.qdrant.collection}_{hypothesis_name}_{run_id}",
    )
    return replace(config, storage=replace(config.storage, qdrant=qdrant))


def indexing_hypothesis_log_path(config: AppConfig, hypothesis_name: str, run_id: str) -> Path:
    base = config.trace.artifact.parent if config.trace.artifact else Path(".code-diver/traces")
    return base / "orchestrator-indexing" / run_id / f"{hypothesis_name}.jsonl"


def indexing_hypothesis_prompt(hypothesis_name: str, cases: list[Any]) -> str:
    queries = "\n".join(f"- {case.query}" for case in cases)
    return (
        f"Evaluate indexing hypothesis `{hypothesis_name}`. Build a compact selected index for this repository "
        "using only the available tools. Use code_diver_index_selected exactly once after inspection. "
        "Index up to 30 high-value ranges that should help later retrieval for these task-style queries. "
        "Do not include expected file paths unless you discovered them with tools. Queries:\n"
        f"{queries}\n"
        "Final answer: one short line with the number of indexed ranges."
    )


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


def close_vector_store(vector_store: Any) -> None:
    close = getattr(vector_store, "close", None)
    if callable(close):
        close()


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
