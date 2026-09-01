from __future__ import annotations

import argparse
import contextlib
import fnmatch
import json
import os
import shutil
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from .agent import DirectIndexingOrchestrator, DirectSearchOrchestrator
from .agent.h3_search_tool_handler import H3SearchToolHandler
from .agent.rerank_tool_handler import RerankToolHandler
from .ai_indexing import AiCodebaseScanner, HybridCodebaseScanner
from .answering import (
    AnswerDatasetLoader,
    AnswerEvaluator,
    AnswerJudge,
    AnswerPairwiseJudge,
    AnswerPairwiseReport,
    AnswerReportJudge,
    AnswerReportMetrics,
    SweQaProDatasetPreparer,
)
from .answering.answer_pipeline_factory import (
    AnswerPipelineFactory,
    search_uses_llm_rerank,
)
from .answering.answer_pipeline_options import AnswerPipelineOptions
from .answering.answer_report_metrics import DURATION_METRICS, JUDGE_METRICS, PRIMARY_METRICS
from .answering.answer_service import AnswerService
from .benchmarks import (
    BenchmarkAssetService,
    BenchmarkProfile,
    BenchmarkProfileRegistry,
)
from .config import AppConfig, ConfigLoader
from .config.embedding_profile_registry import EmbeddingProfileRegistry
from .domain import CodeItemIndexKindResolver, EvalResult, SearchResult
from .env import EnvFileLoader
from .experiments import ExperimentRunner
from .explanation import (
    CodeExplanationDatasetPreparer,
    CodeExplanationEvaluator,
    ExplanationDatasetLoader,
    ExplanationJudge,
)
from .generation import create_generation_provider
from .graph import CodeGraphBuilder, CodeGraphStore
from .inspection import (
    GrepService,
    ReadExcerptService,
    RgService,
    SymbolsService,
    TreeService,
)
from .inspection.exclude_patterns import inspection_exclude_patterns
from .metrics import (
    ClickHouseClient,
    ClickHouseDockerClient,
    ClickHouseMetricsRepository,
    ExperimentMetricsMapper,
)
from .orchestration import OrchestratedCodebaseScanner
from .pi import (
    AgyCliAgentRunner,
    GeminiCliAgentRunner,
    PiRunner,
    PiRuntimeManager,
    PiSessionOptions,
)
from .pi.repository_context_resolver import build_repository_context
from .plugins import PluginManager
from .providers import (
    ProviderCheckResult,
    ProviderTestOptions,
    ProviderTestService,
    VertexBatchTestOptions,
    VertexBatchTestResult,
    VertexBatchTestService,
)
from .providers.embedding_provider_builder import (
    make_embedding_provider,
)
from .ranking import LtrFeatureCollector, LtrFeatureSinkAttacher
from .reranking import RerankProviderFactory
from .runtime import (
    QdrantRuntimeManager,
    RuntimeConfigStore,
    RuntimeSetupWizard,
    SearchRuntime,
)
from .services import (
    CandidateFileScanner,
    CodebaseScanner,
    DatasetLoader,
    EphemeralDeepIndexService,
    GraphIndexingService,
    IndexCollectionResolver,
    IndexCompositionAnalyzer,
    IndexingOptions,
    IndexingService,
    LocalEvalDatasetGenerator,
    SelectedCodeItemBuilder,
    SelectedIndexingService,
    SelectedIndexPayloadParser,
)
from .services.eval_case_bucket_classifier import EvalCaseBucketClassifier
from .services.evaluation_service import EvaluationService
from .services.evaluation_statistics import EvaluationStatistics
from .settings import (
    CommandName,
    Defaults,
    EmbeddingProviderId,
    OptionName,
    RetrievalStrategyId,
    SchemaKey,
    VectorStoreProviderId,
)
from .store import create_vector_store
from .strategies import RetrievalStrategyFactory
from .strategies.fan_out_union_rerank_search import FanOutUnionRerankSearch
from .strategies.retrieval_strategy_builder import make_retrieval_strategy
from .tracing import TraceLogger
from .ui import (
    EditorOpener,
    EvaluationRenderer,
    MarkdownRenderer,
    SearchRenderer,
    TraceMonitor,
)

ADVANCED_COMMANDS = {
    CommandName.ANSWER_PAIRWISE.value,
    CommandName.ANSWER_REPORT.value,
    CommandName.ASK.value,
    CommandName.CHAT.value,
    CommandName.EVALUATE_ANSWERS.value,
    CommandName.EVALUATE_INDEXING.value,
    CommandName.EVALUATE_EXPLANATIONS.value,
    CommandName.EVALUATE_SEARCH_TOOLS.value,
    CommandName.EXPERIMENT.value,
    CommandName.GREP.value,
    CommandName.INDEX_SELECTED.value,
    CommandName.MONITOR.value,
    CommandName.OPEN.value,
    CommandName.READ.value,
    CommandName.RG.value,
    CommandName.SYMBOLS.value,
    CommandName.TREE.value,
}

INDEX_MAINTENANCE_COMMANDS = {"clear", "prune", "reset"}


def status_console() -> Console:
    return Console(stderr=True, color_system="auto")


def render_status_panel(
    title: str, rows: list[tuple[str, object]], border_style: str = "cyan"
) -> None:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold cyan", no_wrap=True)
    table.add_column()
    for key, value in rows:
        table.add_row(key, str(value))
    status_console().print(
        Panel(
            table,
            title=f"[bold]{title}[/bold]",
            border_style=border_style,
            padding=(0, 1),
        )
    )


def render_status_line(message: str, style: str = "cyan") -> None:
    status_console().print(f"[{style}]\\[code-diver][/{style}] {message}")


@contextlib.contextmanager
def render_activity(message: str, enabled: bool = True, style: str = "cyan"):
    if not enabled:
        yield
        return
    progress = Progress(
        TextColumn(f"[{style}]\\[code-diver][/{style}] {message}"),
        SpinnerColumn("dots"),
        console=status_console(),
        transient=True,
    )
    with progress:
        progress.add_task("working", total=None)
        yield


def ensure_storage_runtime(config: AppConfig, progress: bool = True) -> None:
    manager = QdrantRuntimeManager(config)
    if not manager.should_manage():
        return
    with render_activity(
        f"checking local Qdrant from config: {config.storage.qdrant.url}",
        enabled=progress,
        style="blue",
    ):
        status = manager.ensure_running()
    if progress and status.started:
        render_status_line(
            f"started local Qdrant: {config.storage.qdrant.url}", "green"
        )


def make_vector_store(config: AppConfig, progress: bool = False):
    ensure_storage_runtime(config, progress=progress)
    return create_vector_store(config)


def main(argv: list[str] | None = None) -> int:
    normalized = normalize_argv(argv)
    index_maintenance_help = index_maintenance_help_command(normalized)
    if index_maintenance_help is not None:
        build_index_maintenance_help_parser(index_maintenance_help).print_help()
        return 0
    include_advanced = bool(
        normalized
        and (
            OptionName.HELP_ALL.value in normalized
            or any(token in ADVANCED_COMMANDS for token in normalized)
        )
    )
    parser = build_parser(include_advanced=include_advanced)
    if include_advanced:
        normalized = [
            token for token in normalized or [] if token != OptionName.HELP_ALL.value
        ]
        if not normalized:
            parser.print_help()
            return 0
    args = parser.parse_args(normalized)
    try:
        config = ConfigLoader().load(args.config)
        config = apply_runtime_config(args, config)
        EnvFileLoader().load(config.env_file.path, config.env_file.override)
        return int(args.func(args, config))
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def build_parser(include_advanced: bool = False) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="code-diver", description="Config-first codebase RAG CLI."
    )
    parser.add_argument(
        OptionName.CONFIG.value, type=Path, default=None, help="YAML config path."
    )
    parser.add_argument(
        OptionName.ROOT.value,
        type=Path,
        default=None,
        help="Repository root for built-in profiles.",
    )
    parser.add_argument(
        OptionName.HELP_ALL.value,
        action="store_true",
        help="Show advanced inspection, agent, and research commands.",
    )
    command_metavar = (
        None if include_advanced else "{init,index,search,answer,evaluate,provider}"
    )
    subparsers = parser.add_subparsers(
        dest="command", required=True, metavar=command_metavar
    )

    init = subparsers.add_parser(
        CommandName.INIT.value, help="Interactively configure local model runtimes."
    )
    init.add_argument(
        "--embedding",
        choices=EmbeddingProfileRegistry().keys(),
        default=None,
        help="Embedding extractor profile to configure.",
    )
    init.add_argument(
        "--yes",
        action="store_true",
        help="Accept defaults and install without prompting.",
    )
    init.add_argument(
        "--platform",
        choices=["apple-metal", "nvidia-cuda", "amd-rocm", "cpu", "api", "external"],
        default=None,
        help="Hardware/runtime platform used to filter model choices.",
    )
    init.add_argument(
        "--runtime",
        choices=["host-uv", "external"],
        default=None,
        help="Model runtime backend: managed host uv subprocess or external/container endpoint.",
    )
    init.add_argument(
        "--skip-install",
        action="store_true",
        help="Write config without installing vLLM/MLX.",
    )
    init.add_argument(
        "--start",
        action="store_true",
        help="Start the configured local embedding server after setup.",
    )
    init.set_defaults(func=cmd_init)

    index = subparsers.add_parser(
        CommandName.INDEX.value,
        help="Index repository code into the configured artifact.",
    )
    index.add_argument(
        "index_root",
        nargs="?",
        type=Path,
        default=None,
        metavar="index_root|clear",
        help="Repository root to index, or `clear`/`prune`/`reset` to delete Qdrant index collections.",
    )
    index_mode = index.add_mutually_exclusive_group()
    index_mode.add_argument(
        "--update-index",
        action="store_true",
        help="Replace only the current repo/model collection if it already exists.",
    )
    index_mode.add_argument(
        "--override-repo",
        action="store_true",
        help="Delete other Qdrant collections for this repository before indexing.",
    )
    index.add_argument(
        "--all",
        action="store_true",
        help="With `index clear`, delete all Code Diver index collections.",
    )
    index.add_argument(
        "--no-progress", action="store_true", help="Disable indexing progress bars."
    )
    index.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Only print the final indexing summary.",
    )
    index.set_defaults(func=cmd_index)

    search = subparsers.add_parser(
        CommandName.SEARCH.value, help="Ask the code exploration agent."
    )
    search.add_argument("query", nargs="*")
    search.add_argument(OptionName.LIMIT.value, type=int, default=None)
    search.add_argument(
        "-j",
        OptionName.JSON.value,
        action="store_true",
        help="Return raw deterministic retrieval results instead of invoking the agent.",
    )
    search.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Open an interactive Search agent.",
    )
    search.set_defaults(func=cmd_search)

    # The measured pipeline, reachable directly. `search` returns places; `answer` explains.
    # Deliberately a primary command rather than an advanced one: it is the product's main
    # verb, and every quality number we publish describes exactly this code path.
    answer = subparsers.add_parser(
        CommandName.ANSWER.value,
        help="Answer a question about the repository, with citations.",
    )
    answer.add_argument("query", nargs="*")
    add_answer_arguments(answer)
    answer.set_defaults(func=cmd_answer)

    evaluate = subparsers.add_parser(
        CommandName.EVALUATE.value, help="Evaluate retrieval on the configured dataset."
    )
    evaluate.add_argument(
        OptionName.BENCHMARK.value,
        choices=BenchmarkProfileRegistry().names(),
        default=None,
        help="Use a reproducible benchmark profile.",
    )
    evaluate.add_argument(OptionName.DATASET.value, type=Path, default=None)
    evaluate.add_argument(OptionName.LIMIT.value, type=int, default=None)
    evaluate.add_argument(OptionName.DETAILS.value, action="store_true")
    evaluate.add_argument(OptionName.JSON.value, action="store_true")
    evaluate.add_argument(OptionName.REINDEX.value, action="store_true")
    evaluate.add_argument(
        "--generate-dataset",
        action="store_true",
        help="Generate a small repository-local evaluation dataset before running evaluation.",
    )
    evaluate.add_argument(
        "--cases",
        type=int,
        default=50,
        help="Number of local evaluation cases to generate with --generate-dataset.",
    )
    evaluate.add_argument(
        "--dump-features",
        type=Path,
        default=None,
        help="Write one learning-to-rank training row per (query, candidate) to PATH.",
    )
    evaluate.add_argument(
        OptionName.YES.value,
        action="store_true",
        help="Allow benchmark asset downloads without asking.",
    )
    evaluate.set_defaults(func=cmd_evaluate)

    provider = subparsers.add_parser(
        CommandName.PROVIDER.value, help="Diagnose configured model providers."
    )
    provider_subparsers = provider.add_subparsers(
        dest="provider_command", required=True
    )
    provider_test = provider_subparsers.add_parser(
        "test", help="Smoke-test configured generation and embedding providers."
    )
    provider_test.add_argument(
        "--skip-generation",
        action="store_true",
        help="Do not call the generation provider.",
    )
    provider_test.add_argument(
        "--skip-embedding",
        action="store_true",
        help="Do not call the embedding provider.",
    )
    provider_test.add_argument(
        "--fallback-chain",
        action="store_true",
        help="Also force an invalid primary generation model and verify configured fallbacks are used.",
    )
    provider_test.add_argument(
        OptionName.JSON.value, action="store_true", help="Print machine-readable JSON."
    )
    provider_test.set_defaults(func=cmd_provider_test)
    provider_batch = provider_subparsers.add_parser(
        "batch-test", help="Smoke-test Vertex Gemini Batch JSONL/job setup."
    )
    provider_batch.add_argument(
        "--submit",
        action="store_true",
        help="Upload JSONL to GCS and create a Vertex Batch job.",
    )
    provider_batch.add_argument(
        "--gcs-uri",
        default=None,
        help="Writable GCS prefix for batch input/output. Defaults to CODE_DIVER_VERTEX_BATCH_GCS_URI.",
    )
    provider_batch.add_argument(
        "--model",
        default=None,
        help="Override the Vertex model used for this batch smoke.",
    )
    provider_batch.add_argument(
        OptionName.JSON.value, action="store_true", help="Print machine-readable JSON."
    )
    provider_batch.set_defaults(func=cmd_provider_batch_test)

    if include_advanced:
        add_advanced_parsers(subparsers)

    return parser


def add_advanced_parsers(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    index_selected = subparsers.add_parser(
        CommandName.INDEX_SELECTED.value,
        help="Index agent-selected file ranges from a JSON payload on stdin.",
    )
    index_selected.add_argument(OptionName.JSON.value, action="store_true")
    index_selected.set_defaults(func=cmd_index_selected)

    tree = subparsers.add_parser(
        CommandName.TREE.value, help="Print a gitignore-aware repository tree."
    )
    tree.add_argument(OptionName.PATH.value, default=None)
    tree.add_argument(OptionName.LIMIT.value, type=int, default=200)
    tree.add_argument("--depth", type=int, default=3)
    tree.set_defaults(func=cmd_tree)

    grep = subparsers.add_parser(
        CommandName.GREP.value, help="Literal gitignore-aware text search."
    )
    grep.add_argument("pattern")
    grep.add_argument(OptionName.PATH.value, default=None)
    grep.add_argument(OptionName.LIMIT.value, type=int, default=100)
    grep.set_defaults(func=cmd_grep)

    rg = subparsers.add_parser(
        CommandName.RG.value, help="Regex gitignore-aware text search via rg."
    )
    rg.add_argument("pattern")
    rg.add_argument(OptionName.PATH.value, default=None)
    rg.add_argument(OptionName.LIMIT.value, type=int, default=100)
    rg.set_defaults(func=cmd_rg)

    read = subparsers.add_parser(
        CommandName.READ.value, help="Read a bounded, gitignore-aware file excerpt."
    )
    read.add_argument("file")
    read.add_argument(OptionName.START_LINE.value, type=int, default=1)
    read.add_argument(OptionName.LINES.value, type=int, default=80)
    read.set_defaults(func=cmd_read)

    symbols = subparsers.add_parser(
        CommandName.SYMBOLS.value, help="List parsed source symbols."
    )
    symbols.add_argument(OptionName.PATH.value, default=None)
    symbols.add_argument(OptionName.LIMIT.value, type=int, default=200)
    symbols.set_defaults(func=cmd_symbols)

    open_result = subparsers.add_parser(
        CommandName.OPEN.value,
        help="Open the best search result in the configured editor.",
    )
    open_result.add_argument("query", nargs="+")
    open_result.add_argument(OptionName.RANK.value, type=int, default=1)
    open_result.set_defaults(func=cmd_open)

    chat = subparsers.add_parser(
        CommandName.CHAT.value, help="Start or resume the interactive Search agent."
    )
    chat.add_argument("prompt", nargs="*", default=[])
    chat.add_argument(
        "--resume",
        "-r",
        action="store_true",
        help="Select a saved Code Diver chat session to resume.",
    )
    chat.add_argument(
        "--continue",
        "-c",
        dest="continue_session",
        action="store_true",
        help="Continue the last session.",
    )
    chat.add_argument(
        OptionName.SESSION.value,
        default=None,
        help="Resume a specific Pi session path or partial id.",
    )
    chat.add_argument(
        OptionName.SESSION_ID.value,
        default=None,
        help="Use an exact project session id.",
    )
    chat.add_argument(
        OptionName.SESSION_DIR.value,
        type=Path,
        default=None,
        help="Override Code Diver chat session storage.",
    )
    chat.add_argument(
        OptionName.NAME.value, default=None, help="Set the session display name."
    )
    chat.add_argument(OptionName.TOOLSET.value, default=None)
    chat.add_argument(OptionName.HYPOTHESIS.value, default=None)
    chat.set_defaults(func=cmd_chat)

    ask = subparsers.add_parser(
        CommandName.ASK.value, help="Ask a question once, through the answering pipeline."
    )
    ask.add_argument("query", nargs="+")
    # `ask` answers through the core by default. It used to launch the pi agent, which composes
    # its own answer from raw search hits -- a different pipeline from every number we publish.
    # The agent is still reachable, but now you have to ask for it.
    ask.add_argument(
        "--agent",
        action="store_true",
        help="Run the pi Search agent instead of the answering pipeline.",
    )
    add_answer_arguments(ask)
    ask.add_argument(OptionName.TOOLSET.value, default=None)
    ask.add_argument(OptionName.HYPOTHESIS.value, default=None)
    ask.set_defaults(func=cmd_ask)

    evaluate_indexing = subparsers.add_parser(
        CommandName.EVALUATE_INDEXING.value,
        help="Run direct AI indexing hypotheses, then evaluate retrieval metrics.",
    )
    evaluate_indexing.add_argument(OptionName.LIMIT.value, type=int, default=None)
    evaluate_indexing.add_argument(
        OptionName.HYPOTHESIS.value, action="append", default=[]
    )
    evaluate_indexing.add_argument(OptionName.DETAILS.value, action="store_true")
    evaluate_indexing.add_argument(OptionName.JSON.value, action="store_true")
    evaluate_indexing.set_defaults(func=cmd_evaluate_indexing)

    evaluate_search_tools = subparsers.add_parser(
        CommandName.EVALUATE_SEARCH_TOOLS.value,
        help="Run direct AI search-tool hypotheses on the configured dataset.",
    )
    evaluate_search_tools.add_argument(
        OptionName.DATASET.value, type=Path, default=None
    )
    evaluate_search_tools.add_argument(OptionName.LIMIT.value, type=int, default=None)
    evaluate_search_tools.add_argument(
        "--cases",
        type=int,
        default=None,
        help="Evaluate only the first N dataset cases. --limit remains the retrieval top-k.",
    )
    evaluate_search_tools.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Run direct search-tool cases concurrently. Defaults to evaluation.workers.",
    )
    evaluate_search_tools.add_argument(
        OptionName.HYPOTHESIS.value, action="append", default=[]
    )
    evaluate_search_tools.add_argument(OptionName.DETAILS.value, action="store_true")
    evaluate_search_tools.add_argument(OptionName.JSON.value, action="store_true")
    evaluate_search_tools.set_defaults(func=cmd_evaluate_search_tools)

    evaluate_explanations = subparsers.add_parser(
        CommandName.EVALUATE_EXPLANATIONS.value,
        help="Evaluate generated code explanations with reference and optional LLM judge metrics.",
    )
    evaluate_explanations.add_argument(
        OptionName.BENCHMARK.value,
        choices=["codexglue-code-to-text-python"],
        default="codexglue-code-to-text-python",
    )
    evaluate_explanations.add_argument(
        OptionName.DATASET.value, type=Path, default=None
    )
    evaluate_explanations.add_argument("--cases", type=int, default=50)
    evaluate_explanations.add_argument("--output", type=Path, default=None)
    evaluate_explanations.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Evaluate explanation cases concurrently. Defaults to evaluation.workers.",
    )
    evaluate_explanations.add_argument(
        "--partial-output",
        type=Path,
        default=None,
        help="Write an incremental partial report after each completed case.",
    )
    evaluate_explanations.add_argument(
        "--judge",
        action="store_true",
        help="Score answers with an LLM-as-judge rubric.",
    )
    evaluate_explanations.add_argument(
        "--judge-prompt",
        type=Path,
        default=None,
        help="Editable markdown prompt used by the LLM judge.",
    )
    evaluate_explanations.add_argument(
        "--judge-config",
        type=Path,
        default=None,
        help="Optional YAML config for the LLM judge provider.",
    )
    evaluate_explanations.add_argument("--judge-model", default=None)
    evaluate_explanations.add_argument(OptionName.YES.value, action="store_true")
    evaluate_explanations.add_argument(OptionName.JSON.value, action="store_true")
    evaluate_explanations.set_defaults(func=cmd_evaluate_explanations)

    evaluate_answers = subparsers.add_parser(
        CommandName.EVALUATE_ANSWERS.value,
        help="Evaluate end-to-end code answers: search, read context, answer, and optional LLM judge.",
    )
    evaluate_answers.add_argument(
        OptionName.BENCHMARK.value,
        choices=["swe-qa-pro"],
        default=None,
        help="Prepare/load a public repository QA benchmark.",
    )
    evaluate_answers.add_argument(OptionName.DATASET.value, type=Path, default=None)
    evaluate_answers.add_argument("--cases", type=int, default=20)
    evaluate_answers.add_argument(OptionName.LIMIT.value, type=int, default=None)
    evaluate_answers.add_argument(
        "--repo",
        default=None,
        help="Filter benchmark rows to a repository, e.g. owner/name.",
    )
    evaluate_answers.add_argument(
        "--context-files",
        type=int,
        default=None,
        help="Files to read into answer context. Defaults to 4 for hybrid_rerank, 8 otherwise.",
    )
    evaluate_answers.add_argument("--context-lines", type=int, default=160)
    evaluate_answers.add_argument(
        "--agentic-queries",
        action="store_true",
        help="Let the LLM generate multiple search queries before retrieval.",
    )
    evaluate_answers.add_argument(
        "--query-count",
        type=int,
        default=4,
        help="Maximum LLM-generated search queries.",
    )
    evaluate_answers.add_argument(
        "--query-workers",
        type=int,
        default=4,
        help="Parallel retrieval workers for planned queries.",
    )
    evaluate_answers.add_argument(
        "--agentic-query-search-strategy",
        choices=[
            RetrievalStrategyId.VECTOR.value,
            RetrievalStrategyId.HYBRID.value,
            RetrievalStrategyId.HYBRID_RERANK.value,
            RetrievalStrategyId.GRAPH_FILE.value,
            RetrievalStrategyId.GRAPH_FILE_RERANK.value,
        ],
        default=None,
        help="Retrieval strategy used for LLM-planned probe queries. Defaults to the configured search strategy.",
    )
    evaluate_answers.add_argument(
        "--agentic-query-rerank",
        action="store_true",
        help="Experimental: after planned probe queries, run one shared LLM rerank over the merged candidate pool.",
    )
    evaluate_answers.add_argument("--output", type=Path, default=None)
    evaluate_answers.add_argument("--partial-output", type=Path, default=None)
    evaluate_answers.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Evaluate answer cases concurrently. Defaults to evaluation.workers.",
    )
    evaluate_answers.add_argument(
        "--judge",
        action="store_true",
        help="Score final answers with an LLM-as-judge rubric.",
    )
    evaluate_answers.add_argument(
        "--judge-prompt",
        type=Path,
        default=None,
        help="Editable markdown prompt used by the answer judge.",
    )
    evaluate_answers.add_argument(
        "--judge-config",
        type=Path,
        default=None,
        help="Optional YAML config for the answer judge provider.",
    )
    evaluate_answers.add_argument("--judge-model", default=None)
    evaluate_answers.add_argument(
        "--omit-context",
        action="store_true",
        help="Do not store retrieved context text in the report. Smaller artifacts, but weaker post-hoc judging.",
    )
    evaluate_answers.add_argument(OptionName.REINDEX.value, action="store_true")
    evaluate_answers.add_argument(OptionName.YES.value, action="store_true")
    evaluate_answers.add_argument(OptionName.JSON.value, action="store_true")
    evaluate_answers.set_defaults(func=cmd_evaluate_answers)

    answer_report = subparsers.add_parser(
        CommandName.ANSWER_REPORT.value,
        help="Summarize, compare, or post-hoc judge saved evaluate-answers reports.",
    )
    answer_report.add_argument("reports", nargs="+", type=Path)
    answer_report.add_argument("--output", type=Path, default=None)
    answer_report.add_argument(
        "--judge",
        action="store_true",
        help="Run the answer judge over a saved report and write a judged report.",
    )
    answer_report.add_argument(
        "--judge-prompt",
        type=Path,
        default=None,
        help="Editable markdown prompt used by the answer judge.",
    )
    answer_report.add_argument(
        "--judge-config",
        type=Path,
        default=None,
        help="Optional YAML config for the answer judge provider.",
    )
    answer_report.add_argument("--judge-model", default=None)
    answer_report.add_argument(
        "--context-files",
        type=int,
        default=4,
        help="Files to reconstruct for old reports without stored context_text.",
    )
    answer_report.add_argument(
        "--context-lines",
        type=int,
        default=160,
        help="Lines per reconstructed context file for old reports without stored context_text.",
    )
    answer_report.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Judge rows concurrently.",
    )
    answer_report.add_argument(OptionName.JSON.value, action="store_true")
    answer_report.set_defaults(func=cmd_answer_report)

    answer_pairwise = subparsers.add_parser(
        CommandName.ANSWER_PAIRWISE.value,
        help=(
            "Forced-choice comparison of two saved evaluate-answers reports. Use when the "
            "absolute judge saturates and cannot separate the arms."
        ),
    )
    answer_pairwise.add_argument("baseline", type=Path, help="Report treated as the incumbent.")
    answer_pairwise.add_argument("arm", type=Path, help="Report treated as the challenger.")
    answer_pairwise.add_argument(
        "--baseline-name",
        default=None,
        help="Label for the baseline in the results. Defaults to the report filename stem.",
    )
    answer_pairwise.add_argument(
        "--arm-name",
        default=None,
        help="Label for the arm in the results. Defaults to the report filename stem.",
    )
    answer_pairwise.add_argument("--output", type=Path, default=None)
    answer_pairwise.add_argument(
        "--judge-prompt",
        type=Path,
        default=None,
        help="Editable markdown prompt used by the pairwise judge.",
    )
    answer_pairwise.add_argument(
        "--judge-config",
        type=Path,
        default=None,
        help="Optional YAML config for the pairwise judge provider.",
    )
    answer_pairwise.add_argument("--judge-model", default=None)
    answer_pairwise.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Compare pairs concurrently. Keep at 1 for a single-slot local server.",
    )
    answer_pairwise.add_argument(OptionName.JSON.value, action="store_true")
    answer_pairwise.set_defaults(func=cmd_answer_pairwise)

    experiment = subparsers.add_parser(
        CommandName.EXPERIMENT.value,
        help="Run configured retrieval hypotheses and optionally record metrics.",
    )
    experiment.add_argument(OptionName.HYPOTHESIS.value, action="append", default=[])
    experiment.add_argument(OptionName.JSON.value, action="store_true")
    experiment.add_argument(OptionName.REINDEX.value, action="store_true")
    experiment.set_defaults(func=cmd_experiment)

    monitor = subparsers.add_parser(
        CommandName.MONITOR.value, help="Show a live Rich view of a JSONL trace."
    )
    monitor.add_argument("--trace", type=Path, default=None)
    monitor.add_argument("--refresh", type=float, default=0.5)
    monitor.add_argument("--max-events", type=int, default=200)
    monitor.set_defaults(func=cmd_monitor)


def build_index_maintenance_help_parser(command: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=f"code-diver index {command}",
        description="Delete Code Diver Qdrant index collections.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Delete all Code Diver index collections instead of only the current repository collections.",
    )
    parser.add_argument(
        "--no-progress", action="store_true", help="Disable progress output."
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Only print the final deletion summary.",
    )
    return parser


def normalize_argv(argv: list[str] | None) -> list[str] | None:
    raw = list(sys.argv[1:]) if argv is None else list(argv)
    normalized: list[str] = []
    config_tokens: list[str] = []
    index = 0
    while index < len(raw):
        token = raw[index]
        if token in {
            OptionName.CONFIG.value,
            OptionName.ROOT.value,
        } and index + 1 < len(raw):
            config_tokens.extend([token, raw[index + 1]])
            index += 2
            continue
        if token.startswith((f"{OptionName.CONFIG.value}=", f"{OptionName.ROOT.value}=")):
            config_tokens.append(token)
            index += 1
            continue
        normalized.append(token)
        index += 1
    return normalize_command_homoglyphs([*config_tokens, *normalized])


def normalize_command_homoglyphs(tokens: list[str]) -> list[str]:
    commands = {
        CommandName.INIT.value,
        CommandName.INDEX.value,
        CommandName.SEARCH.value,
        CommandName.EVALUATE.value,
        CommandName.PROVIDER.value,
    }
    normalized = list(tokens)
    index = 0
    while index < len(normalized):
        token = normalized[index]
        if token in {
            OptionName.CONFIG.value,
            OptionName.ROOT.value,
        } and index + 1 < len(normalized):
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        candidate = command_homoglyph_fold(token)
        if candidate == "promider":
            candidate = CommandName.PROVIDER.value
        if candidate in commands:
            normalized[index] = candidate
        return normalized
    return normalized


def command_homoglyph_fold(token: str) -> str:
    return token.translate(
        str.maketrans(
            {
                "А": "A",
                "а": "a",
                "В": "B",
                "Е": "E",
                "е": "e",
                "К": "K",
                "М": "M",
                "м": "m",
                "Н": "H",
                "О": "O",
                "о": "o",
                "Р": "P",
                "р": "p",
                "С": "C",
                "с": "c",
                "Т": "T",
                "Х": "X",
                "х": "x",
                "У": "Y",
                "у": "y",
            }
        )
    )


def index_maintenance_help_command(argv: list[str] | None) -> str | None:
    if not argv:
        return None
    for index, token in enumerate(argv):
        if token != CommandName.INDEX.value:
            continue
        if index + 1 >= len(argv):
            return None
        command = argv[index + 1]
        if command not in INDEX_MAINTENANCE_COMMANDS:
            return None
        if any(token in {"-h", "--help"} for token in argv[index + 2 :]):
            return command
    return None


def apply_runtime_config(args: argparse.Namespace, config: AppConfig) -> AppConfig:
    root = runtime_root(args)
    if should_apply_builtin_h5(args):
        config = apply_builtin_h5(config)
    if root is not None:
        config = replace(config, root=root)
        config = scope_relative_repo_artifacts(config)
    embedding_profile = getattr(args, "embedding", None)
    if embedding_profile:
        config = apply_embedding_profile(config, embedding_profile, announce=False)
    elif should_apply_configured_runtime_profile(args):
        config = apply_configured_runtime_profile(config)
    if getattr(args, "command", None) != CommandName.INIT.value:
        config = IndexCollectionResolver().resolve(config)
    return config


def scope_relative_repo_artifacts(config: AppConfig) -> AppConfig:
    return replace(
        config,
        artifact=repo_path(config.root, config.artifact),
        graph=replace(
            config.graph, artifact=repo_path(config.root, config.graph.artifact)
        ),
        trace=replace(
            config.trace, artifact=repo_path(config.root, config.trace.artifact)
        ),
    )


def repo_path(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def apply_embedding_profile(
    config: AppConfig, profile_key: str, announce: bool = True
) -> AppConfig:
    profile = EmbeddingProfileRegistry().get(profile_key)
    if announce:
        render_status_line(f"embedding extractor: {profile.label}", "green")
        if profile.startup_hint:
            render_status_line(
                f"local server expected: {profile.startup_hint}", "yellow"
            )
    return replace(config, embedding=profile.config)


def apply_configured_runtime_profile(config: AppConfig) -> AppConfig:
    store = RuntimeConfigStore()
    if not store.exists():
        return config
    runtime = store.load()
    return apply_embedding_profile(config, runtime.embedding_profile, announce=False)


def should_apply_configured_runtime_profile(args: argparse.Namespace) -> bool:
    if getattr(args, "command", None) == CommandName.INIT.value:
        return False
    config_path = getattr(args, "config", None)
    if config_path is None:
        return True
    return is_default_config_path(config_path)


def is_default_config_path(path: Path) -> bool:
    return path.resolve() == Defaults.CONFIG_PATH.resolve()


def runtime_root(args: argparse.Namespace) -> Path | None:
    command_root = getattr(args, "index_root", None)
    if is_index_maintenance_command(command_root):
        return getattr(args, "root", None)
    if command_root is not None:
        return command_root
    global_root = getattr(args, "root", None)
    return global_root if global_root is not None else None


def is_index_maintenance_command(value: object) -> bool:
    return value is not None and str(value) in INDEX_MAINTENANCE_COMMANDS


def should_apply_builtin_h5(args: argparse.Namespace) -> bool:
    if getattr(args, "benchmark", None):
        return False
    if getattr(args, "config", None) is not None:
        return False
    return not Defaults.CONFIG_PATH.exists()


def apply_builtin_h5(config: AppConfig) -> AppConfig:
    scanner = replace(
        config.scanner,
        line_chunks=False,
        chunk_lines=220,
        structural_chunks=False,
        symbol_chunks=False,
        symbol_body=False,
        file_summary_chunks=True,
        file_manifest_chunks=True,
        file_api_manifest_chunks=False,
        file_body_evidence_chunks=False,
        max_symbols_per_file=96,
    )
    search = replace(config.search, strategy="hybrid", limit=10, preview_lines=10)
    hybrid = replace(
        config.hybrid_search,
        candidate_limit=280,
        lexical_candidate_limit=900,
        vector_weight=0.5625,
        lexical_weight=0.1875,
        path_weight=0.08333333333333334,
        symbol_weight=0.04166666666666667,
        symbol_match_weight=0.04166666666666667,
        graph_weight=0.08333333333333334,
        file_vote_weight=0.0,
        graph_depth=0,
        graph_neighbor_limit=0,
        vector_kind_limits={"file_summary": 170, "file_manifest": 170},
        vector_kind_multipliers={"file_summary": 1.0, "file_manifest": 1.08},
        routing_enabled=True,
        lexical_scoring="bm25",
        fusion="weighted",
        preserve_vector_top=True,
        vector_top_score_margin=0.03,
        item_kind_weights={"file_summary": 1.0, "file_manifest": 1.08},
        min_token_length=3,
    )
    llm_rerank = replace(
        config.llm_rerank,
        candidate_limit=30,
        rerank_limit=10,
        max_preview_chars=700,
        mode="precision",
        include_reasons=False,
        preserve_top_candidate=False,
        retry_attempts=3,
        retry_base_delay_seconds=1.0,
        retry_max_delay_seconds=8.0,
    )
    generation = replace(
        config.generation,
        provider=Defaults.GENERATION_PROVIDER,
        model=Defaults.GENERATION_MODEL,
        fallback_models=[],
        location="global",
        temperature=0.0,
        thinking_budget=Defaults.GENERATION_THINKING_BUDGET,
        api_version=Defaults.GENERATION_API_VERSION,
        timeout_ms=Defaults.GENERATION_TIMEOUT_MS,
        max_tokens=Defaults.GENERATION_MAX_TOKENS,
    )
    graph = replace(
        config.graph,
        ast_enabled=False,
        reference_edges_enabled=False,
        call_edges_enabled=False,
        expansion_depth=0,
        neighbor_limit=0,
    )
    trace = replace(config.trace, include_prompts=True)
    return replace(
        config,
        scanner=scanner,
        search=search,
        hybrid_search=hybrid,
        llm_rerank=llm_rerank,
        generation=generation,
        graph=graph,
        trace=trace,
    )


def apply_builtin_pure_h3(config: AppConfig) -> AppConfig:
    return apply_builtin_h5(config)


def cmd_index(args: argparse.Namespace, config: AppConfig) -> int:
    if is_index_maintenance_command(getattr(args, "index_root", None)):
        return cmd_index_clear(args, config)
    if bool(getattr(args, "all", False)):
        raise ValueError("`--all` is only supported with `code-diver index clear`.")
    progress = not bool(
        getattr(args, "no_progress", False) or getattr(args, "quiet", False)
    )
    ensure_storage_runtime(config, progress=progress)
    prepare_index_collection(args, config, progress=progress)
    with render_activity("building repository context artifact", enabled=progress):
        repository_context_result = build_repository_context(config)
    if progress:
        render_status_panel(
            "Index",
            [
                ("root", config.root.resolve()),
                ("store", store_label(config)),
                ("mode", index_write_mode_label(args)),
                ("scanner", config.indexing.mode),
                ("profile", index_profile_label(config)),
                ("embeds", index_content_label(config)),
                (
                    "repo ctx",
                    (
                        f"{repository_context_result.mode} ({repository_context_result.chars} chars)"
                        if repository_context_result is not None
                        else "disabled"
                    ),
                ),
                ("graph", graph_label(config)),
                ("include", config.scanner.include or ["default-code-files"]),
                ("exclude", f"{len(config.scanner.exclude)} configured patterns"),
            ],
        )
    with render_activity(embedding_activity_message(config), enabled=progress):
        provider = make_embedding_provider(config)
    if progress:
        render_status_panel(
            "Embedding",
            [
                ("provider", provider.name),
                ("model", provider.model),
                (
                    "endpoint",
                    config.embedding.url
                    or config.embedding.location
                    or "provider default",
                ),
                ("dimensions", provider.dimensions or "auto"),
                ("batch size", config.embedding.batch_size),
                ("workers", config.embedding.workers),
                ("max chars", config.embedding.max_input_chars or "provider default"),
            ],
            border_style="magenta",
        )
    indexing_service = make_indexing_service(config, progress=progress)
    try:
        items = indexing_service.build(
            config.root,
            provider=provider,
            plugin_config={"config": config},
        )
        if config.graph.enabled:
            with render_activity(
                graph_activity_message(config, len(items)), enabled=progress
            ):
                GraphIndexingService(
                    CodeGraphBuilder(
                        ast_enabled=config.graph.ast_enabled,
                        reference_edges_enabled=config.graph.reference_edges_enabled,
                        call_edges_enabled=config.graph.call_edges_enabled,
                    ),
                    CodeGraphStore(config.graph.artifact),
                ).build(
                    config.root,
                    items,
                )
            if progress:
                render_status_line(
                    f"saved graph artifact: {config.graph.artifact}", "green"
                )
        print(
            f"Indexed {len(items)} items -> {store_label(config)} "
            f"({provider.name}, model={provider.model}, dimensions={provider.dimensions})"
        )
        print(format_index_composition(items))
    except KeyboardInterrupt:
        render_status_line(
            "indexing interrupted; staged index writes were discarded", "yellow"
        )
        raise
    finally:
        close_vector_store(indexing_service.vector_store)
    return 0


def cmd_index_clear(args: argparse.Namespace, config: AppConfig) -> int:
    if bool(
        getattr(args, "update_index", False) or getattr(args, "override_repo", False)
    ):
        raise ValueError(
            "`index clear` cannot be combined with `--update-index` or `--override-repo`."
        )
    if config.storage.provider != VectorStoreProviderId.QDRANT.value:
        raise ValueError("`index clear` is only supported for Qdrant storage.")
    progress = not bool(
        getattr(args, "no_progress", False) or getattr(args, "quiet", False)
    )
    ensure_storage_runtime(config, progress=progress)
    prefix = (
        Defaults.QDRANT_COLLECTION
        if bool(getattr(args, "all", False))
        else current_repo_collection_prefix(config)
    )
    scope = (
        "all Code Diver index collections"
        if bool(getattr(args, "all", False))
        else "current repository collections"
    )
    if progress:
        render_status_panel(
            "Index Clear",
            [
                ("scope", scope),
                ("prefix", prefix),
                (
                    "store",
                    config.storage.qdrant.url
                    if config.storage.qdrant.location is None
                    else config.storage.qdrant.location,
                ),
            ],
            border_style="yellow",
        )
    vector_store = make_vector_store(config)
    try:
        with render_activity(
            f"deleting Qdrant index collections: {prefix}",
            enabled=progress,
            style="yellow",
        ):
            deleted = vector_store.delete_collections_with_prefix(prefix)
    finally:
        close_vector_store(vector_store)
    print(f"Deleted {len(deleted)} Qdrant collection entries for prefix `{prefix}`.")
    if deleted and not bool(getattr(args, "quiet", False)):
        for name in deleted:
            print(f"  {name}")
    return 0


def prepare_index_collection(
    args: argparse.Namespace, config: AppConfig, progress: bool = True
) -> None:
    if config.storage.provider != VectorStoreProviderId.QDRANT.value:
        return
    vector_store = make_vector_store(config)
    try:
        if bool(getattr(args, "override_repo", False)):
            prefix = current_repo_collection_prefix(config)
            with render_activity(
                f"removing existing Qdrant collections for repo prefix: {prefix}",
                enabled=progress,
            ):
                deleted = vector_store.delete_collections_with_prefix(prefix)
            if progress:
                render_status_line(
                    f"removed {len(deleted)} repo collection entries", "yellow"
                )
            return
        if bool(
            getattr(args, "update_index", False) or getattr(args, "reindex", False)
        ):
            return
        if vector_store.exists():
            raise RuntimeError(
                f"Index collection already exists: {config.storage.qdrant.collection}. "
                "Use `--update-index` to replace only this collection, or `--override-repo` "
                "to delete all collections for this repository before indexing."
            )
    finally:
        close_vector_store(vector_store)


def current_repo_collection_prefix(config: AppConfig) -> str:
    collection = config.storage.qdrant.collection
    marker = "__emb_"
    if marker in collection:
        return collection.split(marker, 1)[0]
    return collection


def index_write_mode_label(args: argparse.Namespace) -> str:
    if bool(getattr(args, "override_repo", False)):
        return "override repo collections"
    if bool(getattr(args, "update_index", False) or getattr(args, "reindex", False)):
        return "update current collection"
    return "create new collection"


def embedding_activity_message(config: AppConfig) -> str:
    model = config.embedding.model or "provider default"
    provider = config.embedding.provider or Defaults.EMBEDDING_PROVIDER
    if config.embedding.provider == EmbeddingProviderId.OPENAI_COMPATIBLE.value:
        return (
            "checking embedding runtime from init config and preparing local client: "
            f"model={model} endpoint={config.embedding.url}"
        )
    if config.embedding.provider in {"gemini", "vertex"}:
        location = (
            f" location={config.embedding.location}"
            if config.embedding.location
            else ""
        )
        return f"creating API embedding client: provider={provider} model={model}{location}"
    return f"creating embedding client: provider={provider} model={model}"


def index_profile_label(config: AppConfig) -> str:
    if (
        config.scanner.file_summary_chunks
        and config.scanner.file_manifest_chunks
        and config.scanner.documentation_summary_chunks
        and config.scanner.documentation_manifest_chunks
        and config.scanner.documentation_chunk_chunks
        and not config.scanner.file_api_manifest_chunks
        and not config.scanner.file_body_evidence_chunks
        and not config.scanner.line_chunks
        and not config.scanner.structural_chunks
        and not config.scanner.symbol_chunks
    ):
        return "H14 text-graph code/docs locator"
    if (
        config.scanner.file_summary_chunks
        and config.scanner.file_manifest_chunks
        and config.scanner.documentation_summary_chunks
        and config.scanner.documentation_manifest_chunks
        and not config.scanner.file_api_manifest_chunks
        and not config.scanner.file_body_evidence_chunks
        and not config.scanner.line_chunks
        and not config.scanner.structural_chunks
        and not config.scanner.symbol_chunks
    ):
        return "H12 dual-lane code/docs locator"
    if (
        config.scanner.file_summary_chunks
        and config.scanner.file_manifest_chunks
        and config.scanner.file_api_manifest_chunks
        and not config.scanner.file_body_evidence_chunks
        and not config.scanner.line_chunks
        and not config.scanner.structural_chunks
        and not config.scanner.symbol_chunks
    ):
        return "H7.1 API manifest file locator"
    if (
        config.scanner.file_summary_chunks
        and config.scanner.file_manifest_chunks
        and not config.scanner.file_api_manifest_chunks
        and config.scanner.file_body_evidence_chunks
        and not config.scanner.line_chunks
        and not config.scanner.structural_chunks
        and not config.scanner.symbol_chunks
    ):
        return "H9 body-evidence file locator"
    if (
        config.scanner.file_summary_chunks
        and config.scanner.file_manifest_chunks
        and not config.scanner.file_api_manifest_chunks
        and not config.scanner.file_body_evidence_chunks
        and not config.scanner.line_chunks
        and not config.scanner.structural_chunks
        and not config.scanner.symbol_chunks
    ):
        return "H6.1 file locator"
    return "custom"


def index_content_label(config: AppConfig) -> str:
    enabled: list[str] = []
    if config.scanner.file_summary_chunks:
        enabled.append("file summaries")
    if config.scanner.file_manifest_chunks:
        enabled.append("file manifests")
    if config.scanner.file_api_manifest_chunks:
        enabled.append("API manifests")
    if config.scanner.file_body_evidence_chunks:
        enabled.append("body evidence")
    if config.scanner.file_purpose_chunks:
        enabled.append("file purpose")
    if config.scanner.symbol_chunk_chunks:
        enabled.append("symbol chunks")
    if config.scanner.documentation_summary_chunks:
        enabled.append("doc summaries")
    if config.scanner.documentation_manifest_chunks:
        enabled.append("doc manifests")
    if config.scanner.documentation_chunk_chunks:
        enabled.append("doc chunks")
    if config.scanner.line_chunks:
        enabled.append("line chunks")
    if config.scanner.structural_chunks:
        enabled.append("AST chunks")
    if config.scanner.symbol_chunks:
        enabled.append("symbols")
    return ", ".join(enabled) if enabled else "scanner output"


def graph_label(config: AppConfig) -> str:
    if not config.graph.enabled:
        return "disabled"
    enabled = []
    if config.graph.ast_enabled:
        enabled.append("AST")
    if config.graph.reference_edges_enabled:
        enabled.append("references")
    if config.graph.call_edges_enabled:
        enabled.append("calls")
    suffix = ", ".join(enabled) if enabled else "containment"
    return f"enabled ({suffix})"


def graph_activity_message(config: AppConfig, item_count: int) -> str:
    return (
        "building graph artifact from indexed items: "
        f"items={item_count} artifact={config.graph.artifact} {graph_label(config)}"
    )


def cmd_init(args: argparse.Namespace, config: AppConfig) -> int:
    if bool(args.skip_install):
        render_status_line(
            "skipping Search agent npm dependency install because --skip-install was passed",
            "yellow",
        )
    else:
        with render_activity(
            "installing Search agent npm dependencies from package-lock/package.json",
            style="blue",
        ):
            PiRuntimeManager().install()
        render_status_line("Search agent npm runtime is installed", "green")
    RuntimeSetupWizard().run(
        profile_key=args.embedding,
        platform=args.platform,
        backend=args.runtime,
        install=False if args.skip_install else None,
        start=bool(args.start),
        yes=bool(args.yes),
    )
    try:
        ensure_storage_runtime(config, progress=True)
    except Exception as exc:
        render_status_line(
            f"storage runtime was not started during init: {exc}", "yellow"
        )
    return 0


def cmd_provider_test(args: argparse.Namespace, config: AppConfig) -> int:
    options = ProviderTestOptions(
        generation=not args.skip_generation,
        embedding=not args.skip_embedding,
        fallback_chain=bool(args.fallback_chain),
    )
    results = ProviderTestService().run(config, options)
    payload = {
        "ok": all(result.ok for result in results),
        "generation": {
            "provider": config.generation.provider,
            "model": config.generation.model,
            "fallback_models": list(config.generation.fallback_models),
            "project": config.generation.project,
            "location": config.generation.location,
            "url": config.generation.url,
            "urls": list(config.generation.urls),
        },
        "embedding": {
            "provider": config.embedding.provider,
            "model": config.embedding.model,
            "dimensions": config.embedding.dimensions,
            "project": config.embedding.project,
            "location": config.embedding.location,
            "url": config.embedding.url,
        },
        "checks": [result.to_dict() for result in results],
    }
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        render_provider_test_results(config, results)
    return 0 if payload["ok"] else 1


def cmd_provider_batch_test(args: argparse.Namespace, config: AppConfig) -> int:
    options = VertexBatchTestOptions(
        submit=bool(args.submit),
        model=args.model,
        gcs_uri=args.gcs_uri,
    )
    result = VertexBatchTestService().run(config, options)
    payload = result.to_dict()
    payload["ok"] = result.ok
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        render_provider_batch_test_result(result)
    return 0 if result.ok else 1


def render_provider_batch_test_result(result: VertexBatchTestResult) -> None:
    console = Console()
    settings = Table.grid(padding=(0, 2))
    settings.add_column(style="bold cyan", no_wrap=True)
    settings.add_column()
    settings.add_row("model", result.model)
    settings.add_row("location", result.location)
    settings.add_row("project", result.project or "resolved by ADC")
    settings.add_row("local input", str(result.local_input))
    if result.gcs_input_uri:
        settings.add_row("gcs input", result.gcs_input_uri)
    if result.gcs_output_uri:
        settings.add_row("gcs output", result.gcs_output_uri)
    if result.job_name:
        settings.add_row("job", result.job_name)
    if result.job_state:
        settings.add_row("state", result.job_state)
    status_style = "green" if result.ok else "red"
    console.print(
        Panel(
            settings,
            title=f"[bold]Vertex Batch Smoke: [{status_style}]{result.status}[/{status_style}][/bold]",
            border_style=status_style,
            padding=(0, 1),
        )
    )
    if result.details:
        console.print(f"[dim]{result.details}[/dim]")


def render_provider_test_results(
    config: AppConfig, results: list[ProviderCheckResult]
) -> None:
    console = Console()
    settings = Table.grid(padding=(0, 2))
    settings.add_column(style="bold cyan", no_wrap=True)
    settings.add_column()
    settings.add_row(
        "generation",
        provider_summary(config.generation.provider, config.generation.model),
    )
    if config.generation.fallback_models:
        settings.add_row("fallbacks", ", ".join(config.generation.fallback_models))
    settings.add_row(
        "embedding", provider_summary(config.embedding.provider, config.embedding.model)
    )
    if config.generation.project or config.embedding.project:
        settings.add_row(
            "project", config.generation.project or config.embedding.project or ""
        )
    if config.generation.location or config.embedding.location:
        settings.add_row(
            "location", config.generation.location or config.embedding.location or ""
        )
    console.print(
        Panel(
            settings,
            title="[bold]Provider Test[/bold]",
            border_style="cyan",
            padding=(0, 1),
        )
    )

    table = Table(show_lines=False)
    table.add_column("check", style="bold")
    table.add_column("provider")
    table.add_column("model")
    table.add_column("status")
    table.add_column("latency", justify="right")
    table.add_column("tokens", justify="right")
    table.add_column("details")
    for result in results:
        table.add_row(
            result.name,
            result.provider,
            result.model or "-",
            provider_status_text(result.status),
            f"{result.latency_ms} ms" if result.latency_ms else "-",
            str(result.total_tokens) if result.total_tokens else "-",
            compact_text(result.details, 120) if result.details else "-",
        )
    console.print(table)


def provider_summary(provider: str, model: str | None) -> str:
    return f"{provider}:{model}" if model else provider


def provider_status_text(status: str) -> str:
    if status == "ok":
        return "[bold green]ok[/bold green]"
    if status == "skipped":
        return "[yellow]skipped[/yellow]"
    return "[bold red]failed[/bold red]"


def compact_text(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: max(limit - 3, 0)].rstrip() + "..."


def cmd_index_selected(args: argparse.Namespace, config: AppConfig) -> int:
    selections = SelectedIndexPayloadParser().parse(sys.stdin.read())
    built = SelectedCodeItemBuilder(
        config.root,
        config.scanner.chunk_lines,
        inspection_exclude_patterns(config),
    ).build(selections)
    if not built.items:
        payload = {
            "indexed": 0,
            "skipped": built.skipped,
            "store": store_label(config),
            "items": [],
        }
        print(
            json.dumps(payload, indent=2) if args.json else "Indexed 0 selected items."
        )
        return 0
    provider = make_embedding_provider(config)
    service = SelectedIndexingService(
        make_vector_store(config),
        IndexingOptions(
            embedding_batch_size=config.embedding.batch_size,
            embedding_workers=config.embedding.workers,
            embedding_max_input_chars=config.embedding.max_input_chars,
            embedding_max_input_tokens=config.embedding.max_input_tokens,
            embedding_token_safety_margin=config.embedding.token_safety_margin,
            progress=True,
        ),
        make_trace_logger(config),
    )
    items = service.build(config.root, provider, built.items)
    if config.graph.enabled:
        GraphIndexingService(
            CodeGraphBuilder(
                ast_enabled=config.graph.ast_enabled,
                reference_edges_enabled=config.graph.reference_edges_enabled,
                call_edges_enabled=config.graph.call_edges_enabled,
            ),
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
    query = normalize_query(args.query)
    if not query and not args.interactive:
        print(
            "error: search query is required unless -i/--interactive is used.",
            file=sys.stderr,
        )
        return 1
    if args.json:
        results = run_search(config, query, args.limit or config.search.limit)
        print(json.dumps([result_to_json(result) for result in results], indent=2))
        return 0
    if not args.json and not code_explorer_preflight(config, args.config):
        return 1
    if not search_agent_binary_available(config):
        if args.interactive:
            render_status_panel(
                "Search Agent Unavailable",
                [
                    ("binary", config.pi.binary),
                    (
                        "fix",
                        "install/configure the Search agent runtime, or use non-interactive search",
                    ),
                    (
                        "deterministic",
                        f'uv run code-diver --root {config.root} search "{query}" --json',
                    ),
                ],
                border_style="red",
            )
            return 1
        return run_deterministic_search_fallback(
            config, query, args.limit or config.search.limit, config.pi.binary
        )
    if args.interactive:
        prompt = search_agent_prompt(config, query) if query else None
        return make_search_agent_runner(config).run_interactive(
            config, args.config, prompt=prompt
        )
    with render_activity(
        "running Search agent: planning tool calls, reading bounded excerpts, preparing answer",
        enabled=True,
        style="green",
    ):
        exit_code, output = make_search_agent_runner(config).run_print_capture(
            config,
            args.config,
            search_agent_prompt(config, query),
            toolset=None,
            hypothesis=None,
        )
    if output.strip():
        MarkdownRenderer(config.ui).render(output)
    return exit_code


def search_agent_binary_available(config: AppConfig) -> bool:
    binary = search_agent_binary(config)
    return bool(shutil.which(binary) or Path(binary).exists())


def search_agent_binary(config: AppConfig) -> str:
    if (
        config.pi.provider in GeminiCliAgentRunner.PROVIDERS
        and config.pi.binary == Defaults.PI_BINARY
    ):
        return Defaults.GEMINI_CLI_BINARY
    if (
        config.pi.provider in AgyCliAgentRunner.PROVIDERS
        and config.pi.binary == Defaults.PI_BINARY
    ):
        return Defaults.AGY_CLI_BINARY
    return config.pi.binary


def make_search_agent_runner(config: AppConfig):
    if config.pi.provider in AgyCliAgentRunner.PROVIDERS:
        return AgyCliAgentRunner()
    if config.pi.provider in GeminiCliAgentRunner.PROVIDERS:
        return GeminiCliAgentRunner()
    return PiRunner()


def search_agent_prompt(config: AppConfig, query: str) -> str:
    if (
        config.pi.provider in AgyCliAgentRunner.PROVIDERS
        or config.pi.provider in GeminiCliAgentRunner.PROVIDERS
    ):
        return query
    return build_code_exploration_prompt(query)


def run_deterministic_search_fallback(
    config: AppConfig, query: str, limit: int, missing_binary: str
) -> int:
    render_status_panel(
        "Deterministic Search Fallback",
        [
            ("reason", f"Search agent binary is not available: {missing_binary}"),
            ("mode", "retrieval only; no LLM explanation"),
            ("json", f'uv run code-diver --root {config.root} search "{query}" --json'),
        ],
        border_style="yellow",
    )
    with render_activity(
        "running deterministic retrieval over the existing index",
        enabled=True,
        style="yellow",
    ):
        results = run_search(config, query, limit)
    SearchRenderer(config.root, config.ui, config.search.preview_lines).render(
        query, results
    )
    return 0


def code_explorer_preflight(config: AppConfig, config_path: Path | None) -> bool:
    if config.pi.provider in AgyCliAgentRunner.PROVIDERS:
        render_status_panel(
            "Search Agent",
            [
                ("root", str(config.root.resolve())),
                ("config", str((config_path or Defaults.CONFIG_PATH).resolve())),
                ("backend", "Antigravity CLI"),
                ("mode", "read-only sandbox"),
                ("model", config.pi.model or "default"),
            ],
            border_style="cyan",
        )
        return True
    if config.pi.provider in GeminiCliAgentRunner.PROVIDERS:
        render_status_panel(
            "Search Agent",
            [
                ("root", str(config.root.resolve())),
                ("config", str((config_path or Defaults.CONFIG_PATH).resolve())),
                ("backend", "Gemini CLI"),
                ("mode", "read-only plan"),
                ("model", config.pi.model or "default"),
            ],
            border_style="cyan",
        )
        return True
    render_status_panel(
        "Search Agent",
        [
            ("root", config.root.resolve()),
            ("config", (config_path or Defaults.CONFIG_PATH).resolve()),
            ("store", store_label(config)),
            ("model", config.pi.model or "default"),
            (
                "tools",
                ", ".join(config.pi.tools) if config.pi.tools else "(none configured)",
            ),
        ],
    )
    vector_store = make_vector_store(config)
    try:
        if not vector_store.exists():
            render_status_panel(
                "Index Missing",
                [
                    ("store", store_label(config)),
                    ("fix", f"uv run code-diver --root {config.root} index"),
                    (
                        "raw check",
                        f'uv run code-diver --root {config.root} search "your query" --json',
                    ),
                ],
                border_style="red",
            )
            return False
        metadata = vector_store.metadata()
        count_items = getattr(vector_store, "count_items", None)
        item_count = count_items() if callable(count_items) else None
        model = metadata.get(SchemaKey.MODEL.value) or "unknown"
        provider = metadata.get(SchemaKey.PROVIDER.value) or "unknown"
        dimensions = metadata.get(SchemaKey.DIMENSIONS.value) or "unknown"
        rows: list[tuple[str, object]] = [
            ("provider", provider),
            ("model", model),
            ("dimensions", dimensions),
        ]
        if item_count is not None:
            rows.append(("items", item_count))
        render_status_panel("Index Ready", rows, border_style="green")
        render_status_line(
            "starting agent: search, verify, read bounded excerpts, explain",
            "green",
        )
        return True
    except Exception as exc:
        render_status_panel(
            "Index Error",
            [
                ("store", store_label(config)),
                ("cause", exc),
                ("qdrant", "docker compose up -d qdrant"),
            ],
            border_style="red",
        )
        return False
    finally:
        close_vector_store(vector_store)


def build_code_exploration_prompt(query: str) -> str:
    return f"""You are Code Diver's code exploration agent.

Answer the user's repository question by using the registered read-only code_diver tools.

User question:
{query}

Required workflow:
1. Start with code_diver_search or code_diver_inspect. Run multiple independent search probes in parallel when useful.
2. Convert the user's wording into several search intents: exact identifiers, likely file/path names, domain concepts, and implementation responsibilities.
3. Verify the top candidates with symbols, grep/rg, and bounded reads before making claims.
4. Explain the code, not only where it is. Cover the owner file/function/class, how control or data flows through it, and why the cited locations answer the question.
5. Cite every important claim with relative file paths and line numbers from tool output.
6. If evidence is weak, say what was checked and what remains uncertain.

Output format:
- Short answer first.
- Evidence table with file/function/lines/relevance.
- Explanation of the mechanism.
- Optional follow-up probes only if they are genuinely useful.

Do not edit files. Do not invent APIs, symbols, or line numbers."""


def cmd_tree(args: argparse.Namespace, config: AppConfig) -> int:
    print(
        TreeService(config.root, inspection_exclude_patterns(config)).render(
            path=args.path, max_depth=args.depth, limit=args.limit
        )
    )
    return 0


def cmd_grep(args: argparse.Namespace, config: AppConfig) -> int:
    print(
        GrepService(
            config.root,
            inspection_exclude_patterns(config),
            config.scanner.max_file_bytes,
        ).render(args.pattern, path=args.path, limit=args.limit)
    )
    return 0


def cmd_rg(args: argparse.Namespace, config: AppConfig) -> int:
    print(
        RgService(
            config.root,
            inspection_exclude_patterns(config),
            config.scanner.max_file_bytes,
        ).search(args.pattern, path=args.path, limit=args.limit)
    )
    return 0


def cmd_read(args: argparse.Namespace, config: AppConfig) -> int:
    print(
        ReadExcerptService(
            config.root,
            inspection_exclude_patterns(config),
            config.scanner.max_file_bytes,
        ).render(args.file, start_line=args.start_line, lines=args.lines)
    )
    return 0


def cmd_symbols(args: argparse.Namespace, config: AppConfig) -> int:
    print(
        SymbolsService(
            config.root,
            inspection_exclude_patterns(config),
            config.scanner.max_file_bytes,
        ).render(path=args.path, limit=args.limit)
    )
    return 0


def cmd_open(args: argparse.Namespace, config: AppConfig) -> int:
    rank = max(int(args.rank), 1)
    limit = max(rank, config.search.limit)
    results = run_search(config, normalize_query(args.query), limit)
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


def cmd_answer(args: argparse.Namespace, config: AppConfig) -> int:
    query = normalize_query(args.query)
    if not query:
        print("error: answer requires a question.", file=sys.stderr)
        return 1
    vector_store = make_vector_store(config, progress=not bool(args.json))
    # Fail loudly. `evaluate` silently indexes when the store is missing, which turns a
    # forgotten `index` into a surprise hour-long build in the middle of a question.
    if not vector_store.exists():
        close_vector_store(vector_store)
        print(
            "error: no index found for this config. Run `code-diver index` first.",
            file=sys.stderr,
        )
        return 1
    try:
        with render_activity(
            "answering: retrieving candidates, building context, generating",
            enabled=not bool(args.json),
            style="green",
        ):
            pipeline = AnswerPipelineFactory().create(
                config,
                vector_store,
                answer_pipeline_options(args, config),
                on_notice=None
                if args.json
                else (lambda text: status_console().print(f"[yellow]{text}[/yellow]")),
            )
            service = AnswerService.from_pipeline(
                pipeline,
                restrict_citations_to_context=pipeline.config.evaluation.restrict_citations_to_context,
            )
            outcome = service.answer(query)
    finally:
        close_vector_store(vector_store)
    if args.json:
        print(json.dumps(answer_outcome_to_json(outcome, args.show_context), indent=2))
        return 0 if outcome.parse_error is None else 1
    return render_answer(outcome, pipeline, args.show_context)


def answer_outcome_to_json(outcome: Any, include_context: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "question": outcome.question,
        "answer": outcome.answer,
        "citations": outcome.citations,
        "confidence": outcome.confidence,
        "retrieved_files": outcome.retrieved_files,
        "context_files": outcome.context.files if outcome.context else [],
        "generation_model": outcome.generation_model,
        "usage": outcome.usage,
        "durations_ms": {
            "retrieval": outcome.retrieval_duration_ms,
            "context": outcome.context_duration_ms,
            "generation": outcome.generation_duration_ms,
        },
    }
    if outcome.parse_error is not None:
        payload["parse_error"] = outcome.parse_error
        payload["raw_prediction"] = outcome.raw_prediction
    if include_context and outcome.context is not None:
        payload["context_text"] = outcome.context.text
    return payload


def render_answer(outcome: Any, pipeline: Any, show_context: bool) -> int:
    console = Console()
    if outcome.parse_error is not None:
        render_status_panel(
            "Answer Not Parseable",
            [
                ("error", outcome.parse_error),
                ("model", outcome.generation_model),
                ("raw", compact_preview(outcome.raw_prediction, 400)),
            ],
            border_style="red",
        )
        return 1
    console.print(
        Panel(
            outcome.answer or "(empty answer)",
            title=outcome.question,
            border_style="cyan",
        )
    )
    if outcome.citations:
        table = Table(title="Citations", show_lines=False)
        table.add_column("path", style="bold")
        table.add_column("lines", no_wrap=True)
        table.add_column("reason")
        for citation in outcome.citations:
            if not isinstance(citation, dict):
                continue
            table.add_row(
                str(citation.get("path") or ""),
                str(citation.get("lines") or ""),
                str(citation.get("reason") or ""),
            )
        console.print(table)
    total_ms = (
        outcome.retrieval_duration_ms
        + outcome.context_duration_ms
        + outcome.generation_duration_ms
    )
    render_status_panel(
        "Answer Trace",
        [
            ("strategy", pipeline.config.search.strategy),
            ("model", outcome.generation_model),
            ("candidates", len(outcome.retrieved_files)),
            (
                "context files",
                len(outcome.context.files) if outcome.context else 0,
            ),
            ("confidence", outcome.confidence if outcome.confidence is not None else "-"),
            (
                "timing",
                f"retrieval {outcome.retrieval_duration_ms:.0f}ms | "
                f"context {outcome.context_duration_ms:.0f}ms | "
                f"generation {outcome.generation_duration_ms:.0f}ms | "
                f"total {total_ms:.0f}ms",
            ),
        ],
    )
    if show_context and outcome.context is not None:
        console.print(
            Panel(outcome.context.text, title="Retrieved context", border_style="blue")
        )
    return 0


def cmd_ask(args: argparse.Namespace, config: AppConfig) -> int:
    if not getattr(args, "agent", False):
        # The default: one question, one grounded answer, through the measured pipeline.
        return cmd_answer(args, config)
    build_repository_context(config)
    return make_search_agent_runner(config).run_print(
        config,
        args.config,
        normalize_query(args.query),
        toolset=args.toolset,
        hypothesis=args.hypothesis,
    )


def cmd_chat(args: argparse.Namespace, config: AppConfig) -> int:
    build_repository_context(config)
    prompt, session = chat_prompt_and_session(args, config)
    return make_search_agent_runner(config).run_interactive(
        config,
        args.config,
        prompt,
        toolset=args.toolset,
        hypothesis=args.hypothesis,
        session=session,
    )


def chat_prompt_and_session(
    args: argparse.Namespace, config: AppConfig
) -> tuple[str | None, PiSessionOptions]:
    words = list(getattr(args, "prompt", []) or [])
    resume = bool(getattr(args, "resume", False))
    continue_session = bool(getattr(args, "continue_session", False))
    session = getattr(args, "session", None)
    session_id = getattr(args, "session_id", None)

    if words and words[0] in {"resume", "continue"}:
        mode = words.pop(0)
        resume = resume or mode == "resume"
        continue_session = continue_session or mode == "continue"
        if words and not session and not session_id:
            session = words.pop(0)

    prompt = normalize_query(words) if words else None
    session_dir = getattr(args, "session_dir", None) or config.pi.session_dir
    return prompt, PiSessionOptions(
        session_dir=session_dir,
        resume=resume,
        continue_session=continue_session,
        session=session,
        session_id=session_id,
        name=getattr(args, "name", None),
    )


def cmd_evaluate(args: argparse.Namespace, config: AppConfig) -> int:
    benchmark = resolve_benchmark_profile(args)
    if (
        benchmark is not None
        and args.config is None
        and benchmark.config_path is not None
    ):
        config = ConfigLoader().load(benchmark.config_path)
        EnvFileLoader().load(config.env_file.path, config.env_file.override)
    if benchmark is not None:
        BenchmarkAssetService().ensure(
            benchmark, assume_yes=bool(getattr(args, "yes", False))
        )

    dataset = args.dataset or (
        benchmark.dataset if benchmark is not None else config.evaluation.dataset
    )
    generated_cases: list[dict[str, Any]] | None = None
    if bool(getattr(args, "generate_dataset", False)):
        dataset = (
            args.dataset or config.root / ".code-diver" / "eval" / "local_eval.jsonl"
        )
        generated_cases = generate_local_eval_dataset(
            config, dataset, int(getattr(args, "cases", 50))
        )
        if not bool(args.json):
            render_status_line(
                f"generated local eval dataset: {dataset} ({len(generated_cases)} cases)",
                "green",
            )

    vector_store = make_vector_store(config, progress=not bool(args.json))
    if args.reindex or not vector_store.exists():
        if args.json:
            with contextlib.redirect_stdout(sys.stderr):
                cmd_index(args, config)
        else:
            cmd_index(args, config)
        vector_store = make_vector_store(config, progress=not bool(args.json))

    limit = args.limit or config.evaluation.limit
    provider = make_embedding_provider(config, vector_store.metadata())
    plugin_manager = make_plugin_manager(config)
    cases = DatasetLoader().load(dataset)
    for case in cases:
        case.query = plugin_manager.prepare_query(case.query)

    strategy = make_retrieval_strategy(config, provider, vector_store)
    feature_dump_path = getattr(args, "dump_features", None)
    feature_collector: LtrFeatureCollector | None = None
    if feature_dump_path is not None:
        feature_collector = LtrFeatureCollector()
        if not LtrFeatureSinkAttacher().attach(strategy, feature_collector.collect):
            raise SystemExit(
                f"--dump-features needs a strategy that fuses per-file scores; "
                f"{config.search.strategy} does not."
            )
    settings = evaluation_settings(
        config,
        dataset,
        limit,
        args.config or (benchmark.config_path if benchmark else None),
    )
    if not bool(args.json):
        render_status_panel(
            "Evaluate",
            [
                ("cases", len(cases)),
                ("limit", limit),
                ("workers", config.evaluation.workers),
                ("strategy", config.search.strategy),
                ("ranker", f"{settings['ranker provider']}:{settings['ranker model']}"),
                ("dataset", dataset),
            ],
            border_style="green",
        )
    progress_callback = None
    if not bool(args.json):
        progress = Progress(
            SpinnerColumn("dots"),
            TextColumn("[cyan]\\[code-diver][/cyan] evaluating cases"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=status_console(),
        )
        with progress:
            task_id = progress.add_task("cases", total=len(cases))

            def progress_callback(completed: int, total: int) -> None:
                progress.update(task_id, total=total, completed=completed)

            metrics, results = EvaluationService(
                strategy, trace_logger=make_trace_logger(config)
            ).evaluate(
                cases,
                limit,
                workers=config.evaluation.workers,
                progress_callback=progress_callback,
            )
    else:
        metrics, results = EvaluationService(
            strategy, trace_logger=make_trace_logger(config)
        ).evaluate(
            cases,
            limit,
            workers=config.evaluation.workers,
        )
    if feature_collector is not None:
        written = feature_collector.write_jsonl(Path(feature_dump_path), cases)
        if not bool(args.json):
            render_status_line(
                f"wrote {written} learning-to-rank feature rows: {feature_dump_path}",
                "green",
            )
    if args.json:
        print(
            json.dumps(
                {
                    "benchmark": benchmark.to_json() if benchmark is not None else None,
                    "config": str(
                        args.config
                        or (
                            benchmark.config_path
                            if benchmark is not None
                            else Defaults.CONFIG_PATH
                        )
                    ),
                    "dataset": str(dataset),
                    "settings": settings,
                    "generated_dataset": {
                        "path": str(dataset),
                        "cases": len(generated_cases),
                    }
                    if generated_cases is not None
                    else None,
                    "limit": limit,
                    "metrics": metrics,
                    "results": [eval_result_to_json(result) for result in results],
                },
                indent=2,
            )
        )
        return 0

    EvaluationRenderer(config.ui.color).render(
        metrics,
        results,
        benchmark=benchmark.to_json() if benchmark is not None else None,
        settings=settings,
        details=args.details,
    )
    return 0


def evaluation_settings(
    config: AppConfig, dataset: Path, limit: int, config_path: Path | None
) -> dict[str, Any]:
    return {
        "config": str(config_path or Defaults.CONFIG_PATH),
        "root": str(config.root),
        "dataset": str(dataset),
        "limit": limit,
        "workers": config.evaluation.workers,
        "store": store_label(config),
        "search strategy": config.search.strategy,
        "index profile": index_profile_label(config),
        "indexed content": index_content_label(config),
        "embedding provider": config.embedding.provider,
        "embedding model": config.embedding.model or "provider default",
        "embedding endpoint": config.embedding.url
        or config.embedding.location
        or "provider default",
        "embedding batch/workers": f"{config.embedding.batch_size}/{config.embedding.workers}",
        "embedding max chars": config.embedding.max_input_chars or "provider default",
        "ranker provider": config.generation.provider
        if search_uses_llm_rerank(config)
        else "none",
        "ranker model": config.generation.model
        if search_uses_llm_rerank(config)
        else "none",
        "rerank candidates/top": f"{config.llm_rerank.candidate_limit}/{config.llm_rerank.rerank_limit}",
        "rerank mode": config.llm_rerank.mode,
        "hybrid candidates": config.hybrid_search.candidate_limit,
        "hybrid weights": (
            f"vector={config.hybrid_search.vector_weight}, lexical={config.hybrid_search.lexical_weight}, "
            f"path={config.hybrid_search.path_weight}, symbol={config.hybrid_search.symbol_weight}, "
            f"symbol_match={config.hybrid_search.symbol_match_weight}, graph={config.hybrid_search.graph_weight}, "
            f"file_vote={config.hybrid_search.file_vote_weight}"
        ),
        "graph-file": graph_file_settings_label(config),
        "graph": graph_label(config),
    }


def graph_file_settings_label(config: AppConfig) -> str:
    if config.search.strategy not in {
        RetrievalStrategyId.GRAPH_FILE.value,
        RetrievalStrategyId.GRAPH_FILE_RERANK.value,
        RetrievalStrategyId.GRAPH_FILE_CROSS_ENCODER.value,
    }:
        return "disabled"
    graph_file = config.graph_file_search
    label = (
        f"seeds={graph_file.seed_limit}, lexical={graph_file.lexical_seed_limit}, "
        f"depth={graph_file.depth}, neighbors={graph_file.neighbor_limit}, decay={graph_file.decay}, "
        f"weights=vector:{graph_file.vector_weight}/lexical:{graph_file.lexical_weight}/"
        f"path:{graph_file.path_weight}/symbol:{graph_file.symbol_weight}/graph:{graph_file.graph_weight}"
    )
    # Only appended when the learned ranker is on, so reports of existing configs are
    # unchanged -- but a run that used a model can never be mistaken for one that did not.
    if graph_file.ltr_ranker_enabled:
        label += f", ltr={graph_file.ltr_model_path or 'no-artifact'}"
    return label


def final_rerank_settings(reranker: object | None) -> dict[str, Any]:
    """What the final candidate rerank will actually be, for the report's settings block."""
    if reranker is None:
        return {"final_rerank_kind": None}
    provider = getattr(reranker, "provider", None)
    return {
        "final_rerank_kind": type(reranker).__name__,
        "final_rerank_provider": getattr(provider, "name", None),
        "final_rerank_model": getattr(provider, "model", None),
        "final_rerank_candidate_limit": getattr(reranker, "candidate_limit", None),
    }


def resolve_benchmark_profile(args: argparse.Namespace) -> BenchmarkProfile | None:
    name = getattr(args, "benchmark", None)
    if not name:
        return None
    return BenchmarkProfileRegistry().get(str(name))


def cmd_evaluate_indexing(args: argparse.Namespace, config: AppConfig) -> int:
    cases = DatasetLoader().load(config.evaluation.dataset)
    limit = args.limit or config.evaluation.limit
    run_id = uuid.uuid4().hex[:12]
    rows: list[dict[str, Any]] = []
    for hypothesis in indexing_hypotheses(config, args.hypothesis):
        eval_config = config_for_indexing_hypothesis(config, hypothesis.name, run_id)
        log_path = indexing_hypothesis_log_path(config, hypothesis.name, run_id)
        tools = resolve_hypothesis_tools(config, hypothesis.name)
        vector_store = make_vector_store(eval_config)
        embedding_provider = make_embedding_provider(eval_config)
        graph_indexer = make_graph_indexer(eval_config)
        started = perf_counter()
        indexing_result = DirectIndexingOrchestrator(
            root=eval_config.root,
            generation_provider=create_generation_provider(eval_config),
            embedding_provider=embedding_provider,
            vector_store=vector_store,
            allowed_tools=tools,
            max_lines=eval_config.scanner.chunk_lines,
            indexing_options=IndexingOptions(
                embedding_batch_size=eval_config.embedding.batch_size,
                embedding_workers=eval_config.embedding.workers,
                embedding_max_input_chars=eval_config.embedding.max_input_chars,
                embedding_max_input_tokens=eval_config.embedding.max_input_tokens,
                embedding_token_safety_margin=eval_config.embedding.token_safety_margin,
                progress=True,
            ),
            log_path=log_path,
            include_prompts=eval_config.trace.include_prompts,
            exclude=inspection_exclude_patterns(eval_config),
            max_file_bytes=eval_config.scanner.max_file_bytes,
            graph_indexer=graph_indexer,
        ).run(hypothesis.name, cases)
        close_vector_store(vector_store)
        vector_store = make_vector_store(eval_config)
        indexing_duration_ms = (perf_counter() - started) * 1000
        row: dict[str, Any] = {
            "hypothesis": hypothesis.name,
            "collection": eval_config.storage.qdrant.collection,
            "tools": tools,
            "log_path": str(log_path),
            "orchestrator": "direct",
            "indexing_exit_code": indexing_result.exit_code,
            "indexing_duration_ms": indexing_duration_ms,
            "orchestrator_usage": indexing_result.to_usage_json(),
            "indexed_items": indexing_result.indexed_items,
            "error": indexing_result.error,
        }
        if indexing_result.exit_code != 0:
            close_vector_store(vector_store)
            rows.append(row)
            continue
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
        metrics, results = EvaluationService(
            strategy, trace_logger=make_trace_logger(eval_config)
        ).evaluate(
            cases,
            limit,
            workers=eval_config.evaluation.workers,
        )
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
        usage = row["orchestrator_usage"]
        print(
            "  orchestrator_usage: "
            f"tokens={usage['total_tokens']} "
            f"input={usage['input_tokens']} output={usage['output_tokens']} "
            f"cost=${usage['total_cost']:.6f} tool_calls={usage['tool_calls']}"
        )
        if row.get("error"):
            print(f"  error: {row['error']} exit_code={row['indexing_exit_code']}")
            continue
        print(f"  indexed_items: {row.get('indexed_items', 'unknown')}")
        for name, value in row["metrics"].items():
            print(
                f"  {name}: {value:.4f}"
                if isinstance(value, float)
                else f"  {name}: {value}"
            )
    return 0


def cmd_evaluate_search_tools(args: argparse.Namespace, config: AppConfig) -> int:
    cases = DatasetLoader().load(args.dataset or config.evaluation.dataset)
    if getattr(args, "cases", None) is not None:
        cases = cases[: max(0, int(args.cases))]
    limit = args.limit or config.evaluation.limit
    worker_count = max(1, int(args.workers or config.evaluation.workers or 1))
    run_id = uuid.uuid4().hex[:12]
    rows: list[dict[str, Any]] = []
    for hypothesis in search_tool_hypotheses(config, args.hypothesis):
        eval_config = config_for_search_hypothesis(config, hypothesis)
        tools = resolve_hypothesis_tools(config, hypothesis.name)
        log_path = search_hypothesis_log_path(eval_config, hypothesis.name, run_id)
        search_vector_store = None
        search_runtime = None
        started = perf_counter()
        eval_results: list[Any] = []
        durations_ms: list[float] = []
        usage = empty_agent_usage()
        errors: list[str] = []
        try:
            search_handler = None
            h3_search_handler = None
            fan_out_union_handler = None
            generation_provider = create_generation_provider(eval_config)
            rerank_generation_provider = generation_provider
            if getattr(hypothesis, "rerank_generation", None) is not None:
                rerank_generation_provider = create_generation_provider(
                    replace(eval_config, generation=hypothesis.rerank_generation)
                )
            rerank_handler = (
                make_rerank_tool_handler(eval_config, rerank_generation_provider)
                if "code_diver_rerank" in tools
                else None
            )
            ephemeral_search_handler = (
                make_ephemeral_search_tool_handler(eval_config)
                if "code_diver_ephemeral_search" in tools
                else None
            )
            if "code_diver_search" in tools or "code_diver_h3_search" in tools:
                persistent_runtime = eval_config.search.persistent_runtime or os.environ.get(
                    "CODE_DIVER_PERSISTENT_SEARCH_RUNTIME"
                ) == "1"
                if persistent_runtime:
                    search_runtime = SearchRuntime(
                        eval_config,
                        fan_out_fusion=getattr(hypothesis, "fan_out_fusion", None),
                    )
                    search_runtime.warm()
                    search_vector_store = search_runtime.vector_store
                    search_provider = search_runtime.provider
                else:
                    search_vector_store = make_vector_store(eval_config)
                    search_provider = make_embedding_provider(
                        eval_config, search_vector_store.metadata()
                    )
                if "code_diver_search" in tools:
                    search_handler = make_search_tool_handler(
                        search_runtime.base_strategy
                        if search_runtime is not None
                        else make_retrieval_strategy(eval_config, search_provider, search_vector_store)
                    )
                if fan_out_union_rerank_enabled(hypothesis):
                    fan_out_union_handler = (
                        search_runtime.fan_out_handler
                        if search_runtime is not None
                        else make_fan_out_union_handler(
                            eval_config,
                            search_provider,
                            search_vector_store,
                            hypothesis.fan_out_fusion,
                        )
                    )
                if "code_diver_h3_search" in tools:
                    h3_search_handler = (
                        search_runtime.h3_handler
                        if search_runtime is not None
                        else H3SearchToolHandler(
                            eval_config,
                            search_provider,
                            search_vector_store,
                            exclude=inspection_exclude_patterns(eval_config),
                        ).search
                    )
            orchestrator = DirectSearchOrchestrator(
                root=eval_config.root,
                generation_provider=generation_provider,
                allowed_tools=tools,
                log_path=log_path,
                include_prompts=eval_config.trace.include_prompts,
                search_handler=search_handler,
                h3_search_handler=h3_search_handler,
                rerank_handler=rerank_handler,
                ephemeral_search_handler=ephemeral_search_handler,
                exclude=inspection_exclude_patterns(eval_config),
                max_file_bytes=eval_config.scanner.max_file_bytes,
                fan_out_fusion=getattr(hypothesis, "fan_out_fusion", None),
                fan_out_union_handler=fan_out_union_handler,
            )

            def run_case(
                index: int, case: Any
            ) -> tuple[int, Any, float, dict[str, Any], str | None]:
                case_started = perf_counter()
                try:
                    search_result = orchestrator.search(  # noqa: B023 - joined before next iteration
                        hypothesis_name=hypothesis.name,  # noqa: B023 - joined before next iteration
                        case_id=case.id,
                        query=case.query,
                        limit=limit,
                    )
                    duration_ms = (perf_counter() - case_started) * 1000
                    error = (
                        f"{case.id}: {search_result.error}"
                        if search_result.error
                        else None
                    )
                    return (
                        index,
                        direct_search_eval_result(case, search_result.retrieved, limit),
                        duration_ms,
                        search_result.usage_json(),
                        error,
                    )
                except Exception as exc:
                    duration_ms = (perf_counter() - case_started) * 1000
                    return (
                        index,
                        direct_search_eval_result(case, [], limit),
                        duration_ms,
                        empty_agent_usage(),
                        f"{case.id}: {type(exc).__name__}: {exc}",
                    )

            eval_results_by_index: list[Any | None] = [None] * len(cases)
            durations_by_index: list[float] = [0.0] * len(cases)
            if worker_count == 1 or len(cases) <= 1:
                completed_rows = [
                    run_case(index, case) for index, case in enumerate(cases)
                ]
            else:
                completed_rows = []
                with ThreadPoolExecutor(
                    max_workers=min(worker_count, max(len(cases), 1))
                ) as executor:
                    futures = {
                        executor.submit(run_case, index, case): index
                        for index, case in enumerate(cases)
                    }
                    for future in as_completed(futures):
                        completed_rows.append(future.result())
            for index, eval_result, duration_ms, case_usage, error in completed_rows:
                eval_results_by_index[index] = eval_result
                durations_by_index[index] = duration_ms
                merge_agent_usage(usage, case_usage)
                if error:
                    errors.append(error)
            eval_results = [
                result for result in eval_results_by_index if result is not None
            ]
            durations_ms = durations_by_index[: len(eval_results)]
        finally:
            if search_runtime is not None:
                search_runtime.close()
            elif search_vector_store is not None:
                close_vector_store(search_vector_store)
        metrics = direct_search_metrics(eval_results, durations_ms, limit)
        metrics["duration_ms"] = (perf_counter() - started) * 1000
        metrics["evaluation_workers"] = worker_count
        metrics["degraded"] = bool(errors)
        metrics["degraded_cases"] = len(errors)
        metrics["degraded_case_rate"] = len(errors) / max(len(cases), 1)
        row: dict[str, Any] = {
            "hypothesis": hypothesis.name,
            "tools": tools,
            "log_path": str(log_path),
            "orchestrator": "direct",
            "orchestrator_usage": usage,
            "metrics": metrics,
            "errors": errors[:20],
            "error_count": len(errors),
        }
        if args.details:
            row["results"] = [eval_result_to_json(result) for result in eval_results]
        rows.append(row)

    if args.json:
        print(json.dumps({"run_id": run_id, "results": rows}, indent=2))
        return 0

    print(f"run_id: {run_id}")
    for row in rows:
        print()
        print(row["hypothesis"])
        print(f"  tools: {', '.join(row['tools'])}")
        print(f"  log_path: {row['log_path']}")
        usage = row["orchestrator_usage"]
        print(
            "  orchestrator_usage: "
            f"tokens={usage['total_tokens']} "
            f"input={usage['input_tokens']} output={usage['output_tokens']} "
            f"cost=${usage['total_cost']:.6f} tool_calls={usage['tool_calls']}"
        )
        if row["error_count"]:
            print(f"  error_count: {row['error_count']}")
        for name, value in row["metrics"].items():
            print(
                f"  {name}: {value:.4f}"
                if isinstance(value, float)
                else f"  {name}: {value}"
            )
    return 0


def cmd_evaluate_explanations(args: argparse.Namespace, config: AppConfig) -> int:
    dataset = args.dataset or Path(
        ".code-diver/benchmarks/codexglue-code-to-text-python/explanations.jsonl"
    )
    output = args.output or Path(
        ".code-diver/reports/codexglue-code-explanation-eval.json"
    )
    if not dataset.exists():
        if not args.yes and not sys.stdin.isatty():
            print(
                "error: explanation benchmark dataset is missing; pass --yes to download/prepare it.",
                file=sys.stderr,
            )
            return 1
        if not args.yes:
            print(
                "Benchmark 'codexglue-code-to-text-python' is not prepared.\n"
                "Source: google/code_x_glue_ct_code_to_text (python test split).\n"
                f"Local output: {dataset}\n"
                "Download and prepare it now? [y/N] ",
                end="",
                file=sys.stderr,
            )
            if input().strip().lower() not in {"y", "yes"}:
                return 1
        with render_activity(
            "preparing CodeXGLUE Python code explanation benchmark",
            enabled=not args.json,
        ):
            preparation = CodeExplanationDatasetPreparer().prepare_codexglue_python(
                dataset, limit=max(args.cases, 1)
            )
    else:
        preparation = None

    cases = ExplanationDatasetLoader().load(dataset)[: max(args.cases, 0)]
    if (
        args.cases > 0
        and len(cases) < args.cases
        and args.benchmark == "codexglue-code-to-text-python"
    ):
        if not args.yes and not sys.stdin.isatty():
            print(
                f"error: explanation benchmark has only {len(cases)} cases; pass --yes to prepare {args.cases}.",
                file=sys.stderr,
            )
            return 1
        if not args.yes:
            print(
                f"Benchmark has only {len(cases)} local cases, but {args.cases} were requested.\n"
                f"Expand local output now? [y/N] ",
                end="",
                file=sys.stderr,
            )
            if input().strip().lower() not in {"y", "yes"}:
                return 1
        with render_activity(
            "expanding CodeXGLUE Python code explanation benchmark",
            enabled=not args.json,
        ):
            preparation = CodeExplanationDatasetPreparer().prepare_codexglue_python(
                dataset, limit=args.cases
            )
        cases = ExplanationDatasetLoader().load(dataset)[: args.cases]
    if not cases:
        print(f"error: no explanation cases found in {dataset}", file=sys.stderr)
        return 1

    judge = None
    if args.judge:
        judge_config = (
            ConfigLoader().load(args.judge_config) if args.judge_config else config
        )
        judge_config = apply_runtime_config(args, judge_config)
        if args.judge_model:
            judge_config = replace(
                judge_config,
                generation=replace(judge_config.generation, model=args.judge_model),
            )
        judge = ExplanationJudge(
            create_generation_provider(judge_config), prompt_path=args.judge_prompt
        )

    worker_count = max(1, int(args.workers or config.evaluation.workers or 1))
    partial_output = args.partial_output or output.with_suffix(
        f"{output.suffix}.partial"
    )
    partial_rows: list[dict[str, Any]] = []

    progress_bar = None
    task_id = None
    if not args.json:
        progress_bar = Progress(
            SpinnerColumn(style="green"),
            TextColumn("[bold green]evaluating explanation cases[/bold green]"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=status_console(),
        )
        progress_bar.start()
        task_id = progress_bar.add_task("explanations", total=len(cases))
    try:

        def advance_progress(completed: int, _total: int, _case: object) -> None:
            if progress_bar is not None and task_id is not None:
                progress_bar.update(task_id, completed=completed)

        def write_partial(completed: int, total: int, row: dict[str, Any]) -> None:
            partial_rows.append(row)
            partial_output.parent.mkdir(parents=True, exist_ok=True)
            partial_output.write_text(
                json.dumps(
                    {
                        "partial": True,
                        "completed": completed,
                        "total": total,
                        "workers": worker_count,
                        "output": str(output),
                        "results": partial_rows,
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

        report = CodeExplanationEvaluator(
            create_generation_provider(config),
            judge=judge,
            progress_callback=advance_progress,
            row_callback=write_partial,
            workers=worker_count,
        ).evaluate(cases)
    finally:
        if progress_bar is not None:
            progress_bar.stop()
    payload = {
        "benchmark": args.benchmark,
        "dataset": str(dataset),
        "prepared": preparation,
        "generation": {
            "provider": config.generation.provider,
            "model": config.generation.model,
        },
        "workers": worker_count,
        "judge": {
            "enabled": bool(args.judge),
            "config": str(args.judge_config) if args.judge_config else None,
            "prompt": str(args.judge_prompt or ExplanationJudge.DEFAULT_PROMPT_PATH),
            "model": args.judge_model
            or (
                judge_config.generation.model if args.judge else config.generation.model
            ),
        },
        **report,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    print(f"saved explanation eval report: {output}")
    metrics = payload["metrics"]
    table = Table(title="code explanation metrics")
    table.add_column("metric", style="cyan")
    table.add_column("value", justify="right")
    for key in [
        "cases",
        "token_f1",
        "key_token_f1",
        "bigram_f1",
        "judge_purpose_accuracy",
        "judge_behavior_accuracy",
        "judge_api_contract",
        "judge_groundedness",
        "judge_specificity",
        "judge_completeness",
        "judge_clarity",
        "judge_overall",
        "duration_ms",
    ]:
        if key in metrics:
            value = metrics[key]
            table.add_row(
                key, f"{value:.4f}" if isinstance(value, float) else str(value)
            )
    Console().print(table)
    return 0


def add_answer_arguments(parser: argparse.ArgumentParser) -> None:
    """The answering knobs, defined once.

    `answer` and `ask` run the same pipeline, so they must expose the same flags with the same
    defaults; two copies of this list is how a front-end silently stops matching the eval.
    """
    parser.add_argument(OptionName.LIMIT.value, type=int, default=None)
    parser.add_argument(
        "--context-files",
        type=int,
        default=None,
        help="Files to read into answer context. Defaults to 4 for hybrid_rerank, 8 otherwise.",
    )
    parser.add_argument("--context-lines", type=int, default=160)
    parser.add_argument(
        "--agentic-queries",
        action="store_true",
        help="Let the LLM generate multiple search queries before retrieval.",
    )
    parser.add_argument(
        "--query-count", type=int, default=4, help="Maximum LLM-generated search queries."
    )
    parser.add_argument(
        "--query-workers",
        type=int,
        default=4,
        help="Parallel retrieval workers for planned queries.",
    )
    parser.add_argument(
        "--agentic-query-rerank",
        action="store_true",
        help="Rerank the merged multi-query candidate pool before answering.",
    )
    parser.add_argument(
        "--show-context",
        action="store_true",
        help="Print the retrieved context that was sent to the model.",
    )
    parser.add_argument(
        "-j", OptionName.JSON.value, action="store_true", help="Emit the answer as JSON."
    )


def answer_pipeline_options(
    args: argparse.Namespace, config: AppConfig
) -> AnswerPipelineOptions:
    # Shared by `answer` and `evaluate-answers` so the product cannot drift from the eval.
    # `limit=None` means "take config.evaluation.limit" -- resolved in the factory, once.
    return AnswerPipelineOptions(
        limit=args.limit,
        context_files=args.context_files,
        context_lines=args.context_lines,
        agentic_queries=bool(args.agentic_queries),
        agentic_query_rerank=bool(args.agentic_query_rerank),
        agentic_query_search_strategy=getattr(
            args, "agentic_query_search_strategy", None
        ),
        query_count=args.query_count,
        query_workers=args.query_workers,
    )


def cmd_evaluate_answers(args: argparse.Namespace, config: AppConfig) -> int:
    if args.agentic_query_rerank and not args.agentic_queries:
        print(
            "error: --agentic-query-rerank requires --agentic-queries", file=sys.stderr
        )
        return 1
    dataset = answer_dataset_path(args)
    output = args.output or Path(".code-diver/reports/code-answer-e2e-eval.json")
    preparation = prepare_answer_benchmark(args, dataset, enabled=not bool(args.json))
    cases = AnswerDatasetLoader().load(dataset)
    if args.repo:
        cases = [
            case for case in cases if str(case.metadata.get("repo") or "") == args.repo
        ]
    requested_cases = max(int(args.cases or 0), 0)
    if (
        args.benchmark == "swe-qa-pro"
        and requested_cases > 0
        and len(cases) < requested_cases
    ):
        preparation = expand_answer_benchmark(
            args, dataset, requested_cases, enabled=not bool(args.json)
        )
        cases = AnswerDatasetLoader().load(dataset)
        if args.repo:
            cases = [
                case
                for case in cases
                if str(case.metadata.get("repo") or "") == args.repo
            ]
    cases = cases[:requested_cases]
    if not cases:
        print(f"error: no answer cases found in {dataset}", file=sys.stderr)
        return 1

    vector_store = make_vector_store(config, progress=not bool(args.json))
    if args.reindex or not vector_store.exists():
        if args.json:
            with contextlib.redirect_stdout(sys.stderr):
                cmd_index(args, config)
        else:
            cmd_index(args, config)
        vector_store = make_vector_store(config, progress=not bool(args.json))

    pipeline = AnswerPipelineFactory().create(
        config,
        vector_store,
        answer_pipeline_options(args, config),
        on_notice=None
        if args.json
        else (lambda text: status_console().print(f"[yellow]{text}[/yellow]")),
    )
    # The factory may back-fill llm_rerank.repository_context_path, so adopt its config.
    config = pipeline.config
    limit = pipeline.limit
    context_files = pipeline.context_files
    answer_provider = pipeline.answer_provider
    strategy = pipeline.retrieval_strategy
    repository_context = pipeline.repository_context
    query_planner = pipeline.query_planner
    query_retrieval_strategy = pipeline.query_retrieval_strategy
    query_result_reranker = pipeline.query_result_reranker
    agentic_query_search_strategy = pipeline.query_search_strategy
    repository_context_result = pipeline.repository_context_result
    judge = None
    judge_config = None
    if args.judge:
        judge_config = (
            ConfigLoader().load(args.judge_config) if args.judge_config else config
        )
        judge_config = apply_runtime_config(args, judge_config)
        if args.judge_model:
            judge_config = replace(
                judge_config,
                generation=replace(judge_config.generation, model=args.judge_model),
            )
        judge = AnswerJudge(
            create_generation_provider(judge_config), prompt_path=args.judge_prompt
        )

    worker_count = max(1, int(args.workers or config.evaluation.workers or 1))
    partial_output = args.partial_output or output.with_suffix(
        f"{output.suffix}.partial"
    )
    partial_rows: list[dict[str, Any]] = []
    if not args.json:
        render_status_panel(
            "E2E Answer Evaluation",
            [
                ("cases", len(cases)),
                ("root", config.root.resolve()),
                ("dataset", dataset),
                ("search", config.search.strategy),
                ("limit", limit),
                ("context", f"{context_files} files x {args.context_lines} lines"),
                (
                    "query mode",
                    "llm multi-query" if args.agentic_queries else "single query",
                ),
                ("query count", args.query_count if args.agentic_queries else 1),
                (
                    "query search",
                    agentic_query_search_strategy or config.search.strategy,
                ),
                ("query final rerank", bool(query_result_reranker)),
                (
                    "repo context",
                    f"{repository_context_result.mode} ({repository_context_result.chars} chars)"
                    if repository_context_result is not None
                    else "disabled",
                ),
                (
                    "answer model",
                    f"{config.generation.provider}:{config.generation.model}",
                ),
                ("judge", args.judge),
                ("workers", worker_count),
            ],
            border_style="green",
        )

    progress_bar = None
    task_id = None
    if not args.json:
        progress_bar = Progress(
            SpinnerColumn(style="green"),
            TextColumn("[bold green]evaluating e2e answer cases[/bold green]"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=status_console(),
        )
        progress_bar.start()
        task_id = progress_bar.add_task("answers", total=len(cases))
    try:

        def advance_progress(completed: int, _total: int, _case: object) -> None:
            if progress_bar is not None and task_id is not None:
                progress_bar.update(task_id, completed=completed)

        def write_partial(completed: int, total: int, row: dict[str, Any]) -> None:
            partial_rows.append(row)
            partial_output.parent.mkdir(parents=True, exist_ok=True)
            partial_output.write_text(
                json.dumps(
                    {
                        "partial": True,
                        "completed": completed,
                        "total": total,
                        "workers": worker_count,
                        "output": str(output),
                        "results": partial_rows,
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

        report = AnswerEvaluator(
            strategy,
            answer_provider,
            pipeline.context_builder,
            repository_context=repository_context,
            judge=judge,
            query_planner=query_planner,
            query_retrieval_strategy=query_retrieval_strategy,
            query_result_reranker=query_result_reranker,
            limit=limit,
            query_workers=args.query_workers,
            workers=worker_count,
            save_context=not bool(args.omit_context),
            restrict_citations_to_context=config.evaluation.restrict_citations_to_context,
            progress_callback=advance_progress,
            row_callback=write_partial,
        ).evaluate(cases)
    finally:
        if progress_bar is not None:
            progress_bar.stop()
        close_vector_store(vector_store)

    payload = {
        "benchmark": args.benchmark,
        "dataset": str(dataset),
        "prepared": preparation,
        "settings": {
            "root": str(config.root),
            "search_strategy": config.search.strategy,
            "limit": limit,
            "context_files": context_files,
            "context_lines": args.context_lines,
            "agentic_queries": bool(args.agentic_queries),
            "query_count": args.query_count if args.agentic_queries else 1,
            "query_workers": args.query_workers,
            "agentic_query_search_strategy": agentic_query_search_strategy
            or config.search.strategy,
            "agentic_query_rerank": bool(args.agentic_query_rerank),
            "repo_context_enabled": repository_context_result is not None,
            "repo_context_mode": repository_context_result.mode
            if repository_context_result is not None
            else None,
            "repo_context_chars": repository_context_result.chars
            if repository_context_result is not None
            else 0,
            "embedding_provider": config.embedding.provider,
            "embedding_model": config.embedding.model,
            "answer_provider": config.generation.provider,
            "answer_model": config.generation.model,
            # Read off the reranker object, not off the config. An arm that names a rerank model
            # the eval path ignores used to look identical to one that honours it, which is how a
            # whole 100-case arm came back as an unwitting replicate of its own control
            # (Finding 35). Recording what will actually run makes that unrepeatable.
            **final_rerank_settings(query_result_reranker),
            "judge_enabled": bool(args.judge),
            "judge_prompt": str(args.judge_prompt or AnswerJudge.DEFAULT_PROMPT_PATH),
            "judge_model": args.judge_model
            or (judge_config.generation.model if judge_config else None),
            "workers": worker_count,
            "context_text_saved": not bool(args.omit_context),
            # Part of the arm's identity: the same reranker with and without the citation
            # allowlist are different arms, and a report that does not say which one it was
            # cannot be compared to anything.
            "restrict_citations_to_context": config.evaluation.restrict_citations_to_context,
        },
        **report,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    print(f"saved e2e answer eval report: {output}")
    render_answer_metrics_table(payload["metrics"])
    return 0


def cmd_answer_report(args: argparse.Namespace, config: AppConfig) -> int:
    if args.judge:
        if len(args.reports) != 1:
            print("error: --judge accepts exactly one report", file=sys.stderr)
            return 1
        return cmd_answer_report_judge(args, config)
    comparison = AnswerReportMetrics().compare(args.reports)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(comparison, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    if args.json:
        print(json.dumps(comparison, indent=2, ensure_ascii=False))
        return 0
    render_answer_report_comparison(comparison)
    if args.output:
        print(f"saved answer report comparison: {args.output}")
    return 0


def cmd_answer_report_judge(args: argparse.Namespace, config: AppConfig) -> int:
    report_path = args.reports[0]
    payload = AnswerReportMetrics().load(report_path)
    judge_config = ConfigLoader().load(args.judge_config) if args.judge_config else config
    judge_config = apply_runtime_config(args, judge_config)
    if args.judge_model:
        judge_config = replace(
            judge_config,
            generation=replace(judge_config.generation, model=args.judge_model),
        )
    root = answer_report_root(payload, config)
    output = args.output or report_path.with_name(f"{report_path.stem}.judged.json")
    partial_output = output.with_suffix(f"{output.suffix}.partial")
    rows: list[dict[str, Any]] = []

    def write_partial(completed: int, total: int, row: dict[str, Any]) -> None:
        rows.append(row)
        partial_output.parent.mkdir(parents=True, exist_ok=True)
        partial_output.write_text(
            json.dumps(
                {
                    "partial": True,
                    "completed": completed,
                    "total": total,
                    "source": str(report_path),
                    "output": str(output),
                    "results": rows,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    progress_bar = None
    task_id = None
    source_rows = [row for row in payload.get("results") or [] if isinstance(row, dict)]
    if not args.json:
        render_status_panel(
            "Post-hoc Answer Judge",
            [
                ("source", report_path),
                ("output", output),
                ("cases", len(source_rows)),
                ("root", root or "(context_text only)"),
                ("judge model", f"{judge_config.generation.provider}:{judge_config.generation.model}"),
                ("prompt", args.judge_prompt or AnswerJudge.DEFAULT_PROMPT_PATH),
                ("workers", args.workers),
            ],
            border_style="magenta",
        )
        progress_bar = Progress(
            SpinnerColumn(style="magenta"),
            TextColumn("[bold magenta]judging saved answer rows[/bold magenta]"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=status_console(),
        )
        progress_bar.start()
        task_id = progress_bar.add_task("judge", total=len(source_rows))

    def advance(completed: int, _total: int, _row: dict[str, Any]) -> None:
        if progress_bar is not None and task_id is not None:
            progress_bar.update(task_id, completed=completed)

    try:
        judged = AnswerReportJudge(
            AnswerJudge(
                create_generation_provider(judge_config),
                prompt_path=args.judge_prompt,
            ),
            root=root,
            context_files=args.context_files,
            context_lines=args.context_lines,
            max_file_bytes=judge_config.scanner.max_file_bytes,
            workers=args.workers,
            progress_callback=advance,
            row_callback=write_partial,
        ).judge_payload(payload)
    finally:
        if progress_bar is not None:
            progress_bar.stop()

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(judged, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if args.json:
        print(json.dumps(judged, indent=2, ensure_ascii=False))
        return 0
    print(f"saved judged answer report: {output}")
    render_answer_metrics_table(judged["metrics"])
    return 0


def cmd_answer_pairwise(args: argparse.Namespace, config: AppConfig) -> int:
    baseline_payload = AnswerReportMetrics().load(args.baseline)
    arm_payload = AnswerReportMetrics().load(args.arm)
    judge_config = ConfigLoader().load(args.judge_config) if args.judge_config else config
    judge_config = apply_runtime_config(args, judge_config)
    if args.judge_model:
        judge_config = replace(
            judge_config,
            generation=replace(judge_config.generation, model=args.judge_model),
        )
    baseline_name = args.baseline_name or args.baseline.stem
    arm_name = args.arm_name or args.arm.stem
    if baseline_name == arm_name:
        print(
            f"error: baseline and arm resolve to the same label {baseline_name!r}; "
            "pass --baseline-name/--arm-name so the verdicts can be told apart",
            file=sys.stderr,
        )
        return 1
    output = args.output or Path(f"{args.arm.with_suffix('')}.pairwise-vs-{baseline_name}.json")
    if output.exists():
        print(f"error: refusing to overwrite existing {output}", file=sys.stderr)
        return 1

    progress_bar = None
    task_id = None
    if not args.json:
        render_status_panel(
            "Pairwise Answer Judge",
            [
                ("baseline", f"{baseline_name} ({args.baseline})"),
                ("arm", f"{arm_name} ({args.arm})"),
                ("output", output),
                ("judge model", f"{judge_config.generation.provider}:{judge_config.generation.model}"),
                ("prompt", args.judge_prompt or AnswerPairwiseJudge.DEFAULT_PROMPT_PATH),
                ("workers", args.workers),
            ],
            border_style="magenta",
        )
        progress_bar = Progress(
            SpinnerColumn(style="magenta"),
            TextColumn("[bold magenta]comparing answers[/bold magenta]"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=status_console(),
        )
        progress_bar.start()
        task_id = progress_bar.add_task("pairwise", total=None)

    def advance(completed: int, total: int, _verdict: Any) -> None:
        if progress_bar is not None and task_id is not None:
            progress_bar.update(task_id, completed=completed, total=total)

    try:
        result = AnswerPairwiseReport(
            AnswerPairwiseJudge(
                create_generation_provider(judge_config),
                prompt_path=args.judge_prompt,
            ),
            baseline_name=baseline_name,
            arm_name=arm_name,
            workers=args.workers,
            progress_callback=advance,
        ).compare_payloads(baseline_payload, arm_payload)
    finally:
        if progress_bar is not None:
            progress_bar.stop()

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    print(f"saved pairwise comparison: {output}")
    render_answer_pairwise_summary(result)
    return 0


def render_answer_pairwise_summary(result: dict[str, Any]) -> None:
    summary = result["summary"]
    arm, baseline = result["arm"], result["baseline"]
    table = Table(title=f"pairwise: {arm} vs {baseline}")
    table.add_column("dimension", style="cyan")
    table.add_column(f"{arm} wins", justify="right", style="bold")
    table.add_column(f"{baseline} wins", justify="right")
    table.add_column("ties", justify="right")
    table.add_column("sign p", justify="right")
    table.add_row(
        "OVERALL",
        str(summary["arm_wins"]),
        str(summary["arm_losses"]),
        str(summary["ties"]),
        f"{summary['sign_test_p']:.4f}",
    )
    for name, stats in summary["dimensions"].items():
        table.add_row(
            name,
            str(stats["arm_wins"]),
            str(stats["arm_losses"]),
            str(stats["ties"]),
            f"{stats['sign_test_p']:.4f}",
        )
    Console().print(table)
    Console().print(
        f"cases judged {result['cases_judged']}/{result['cases_paired']}"
        f"  win rate {summary['win_rate']:.1%}"
        f"  win rate among decided {summary['win_rate_decided']:.1%}"
    )
    # Printed every time, not only when it looks bad: a reader who is not told the position
    # split has no way to know whether a win rate reflects quality or reading order.
    Console().print(
        f"position-bias check: slot A won {summary['slot_a_win_share']:.1%} of "
        f"{summary['decided_cases']} decided cases (0.5 = unbiased)"
    )
    if result["judge_errors"]:
        Console().print(f"[yellow]judge errors: {len(result['judge_errors'])} case(s) dropped[/yellow]")


def answer_report_root(payload: dict[str, Any], config: AppConfig) -> Path | None:
    settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
    root = settings.get("root") if settings else None
    if root:
        return Path(str(root))
    return config.root if config.root else None


# Keys that render with a 95% CI in `answer_report_metric_cell`, on top of any key already
# matched by the `"_hit" in key` heuristic below. These are the deterministic gates -- bundle
# completeness and grounding binaries -- where a 100-case sweep needs the interval to tell a
# real gap from sampling noise, plus `judge_overall` for continuity with historical reports.
CI_RENDERED_METRICS: frozenset[str] = frozenset(
    {
        "context_bundle_complete",
        "candidate_bundle_complete",
        "answer_grounded",
        "answer_nonempty",
        "judge_overall",
    }
)


def render_answer_report_comparison(comparison: dict[str, Any]) -> None:
    table = Table(title="answer report comparison")
    table.add_column("report", style="cyan")
    table.add_column("primary (bundle)", justify="right", style="bold")
    table.add_column("retrieval", justify="right")
    table.add_column("context", justify="right")
    table.add_column("text / citations", justify="right")
    table.add_column("latency", justify="right")
    table.add_column("judge (SECONDARY,\nunvalidated)", justify="right")
    for report in comparison.get("reports") or []:
        metrics = report.get("metrics") or {}
        table.add_row(
            str(report.get("name") or "report"),
            "\n".join(
                [
                    f"context bundle {answer_report_metric_cell(metrics, 'context_bundle_complete')}",
                    f"candidate bundle {answer_report_metric_cell(metrics, 'candidate_bundle_complete')}",
                    f"grounded {answer_report_metric_cell(metrics, 'answer_grounded')}",
                    f"fabricated {answer_report_metric_cell(metrics, 'citation_fabricated_rate')}",
                ]
            ),
            "\n".join(
                [
                    f"cases {answer_report_metric_cell(metrics, 'cases')}",
                    f"hit@1 {answer_report_metric_cell(metrics, 'candidate_file_hit@1')}",
                    f"hit@3 {answer_report_metric_cell(metrics, 'candidate_file_hit@3')}",
                    f"hit@5 {answer_report_metric_cell(metrics, 'candidate_file_hit@5')}",
                    f"file hit {answer_report_metric_cell(metrics, 'file_hit')}",
                ]
            ),
            "\n".join(
                [
                    f"hit {answer_report_metric_cell(metrics, 'context_file_hit')}",
                    f"recall {answer_report_metric_cell(metrics, 'context_file_recall')}",
                    f"precision {answer_report_metric_cell(metrics, 'context_file_precision')}",
                ]
            ),
            "\n".join(
                [
                    f"token F1 {answer_report_metric_cell(metrics, 'token_f1')}",
                    f"key F1 {answer_report_metric_cell(metrics, 'key_token_f1')}",
                    f"citation path {answer_report_metric_cell(metrics, 'citation_path_valid_rate')}",
                    f"citation line {answer_report_metric_cell(metrics, 'citation_line_valid_rate')}",
                ]
            ),
            "\n".join(
                [
                    f"retrieval {answer_report_metric_cell(metrics, 'retrieval_duration_ms')} ms",
                    f"context {answer_report_metric_cell(metrics, 'context_duration_ms')} ms",
                    f"generation {answer_report_metric_cell(metrics, 'generation_duration_ms')} ms",
                ]
            ),
            "\n".join(
                [
                    f"correctness {answer_report_metric_cell(metrics, 'judge_answer_correctness')}",
                    f"grounding {answer_report_metric_cell(metrics, 'judge_evidence_grounding')}",
                    f"coverage {answer_report_metric_cell(metrics, 'judge_coverage')}",
                    f"citation qual {answer_report_metric_cell(metrics, 'judge_citation_quality')}",
                    f"specificity {answer_report_metric_cell(metrics, 'judge_specificity')}",
                    f"hallucination {answer_report_metric_cell(metrics, 'judge_hallucination_control')}",
                    f"abstained {answer_report_metric_cell(metrics, 'judge_abstained')}",
                    f"errors {answer_report_metric_cell(metrics, 'judge_error_count')}",
                    f"[dim]overall {answer_report_metric_cell(metrics, 'judge_overall')}[/dim]",
                ]
            ),
        )
    Console().print(table)


def answer_report_metric_cell(metrics: dict[str, Any], key: str) -> str:
    value = metrics.get(key)
    if not isinstance(value, (float, int)):
        return "-"
    if key.endswith("_ms"):
        return f"{float(value):.0f}"
    low = metrics.get(f"{key}_ci95_low")
    high = metrics.get(f"{key}_ci95_high")
    if isinstance(low, (float, int)) and isinstance(high, (float, int)) and (
        "_hit" in key or key in CI_RENDERED_METRICS
    ):
        return f"{float(value):.3f} [{float(low):.3f}, {float(high):.3f}]"
    return f"{float(value):.4f}"


def answer_dataset_path(args: argparse.Namespace) -> Path:
    if args.dataset is not None:
        return args.dataset
    if args.benchmark == "swe-qa-pro":
        repo_suffix = f"-{args.repo.replace('/', '-')}" if args.repo else ""
        return Path(f".code-diver/benchmarks/swe-qa-pro/answers{repo_suffix}.jsonl")
    return Path(".code-diver/eval/answer_cases.jsonl")


def prepare_answer_benchmark(
    args: argparse.Namespace, dataset: Path, *, enabled: bool = True
) -> dict[str, Any] | None:
    if args.benchmark != "swe-qa-pro":
        return None
    if dataset.exists():
        return None
    if not args.yes and not sys.stdin.isatty():
        raise RuntimeError(
            "SWE-QA-Pro answer dataset is missing; pass --yes to download/prepare it."
        )
    if not args.yes:
        print(
            "Benchmark 'swe-qa-pro' is not prepared.\n"
            "Source: TIGER-Lab/SWE-QA-Pro-Bench (test split).\n"
            f"Cases: {args.cases}\n"
            f"Repo filter: {args.repo or '(none)'}\n"
            f"Local output: {dataset}\n"
            "Download and prepare it now? [y/N] ",
            end="",
            file=sys.stderr,
        )
        if input().strip().lower() not in {"y", "yes"}:
            raise RuntimeError(f"Benchmark assets not prepared for '{args.benchmark}'.")
    with render_activity("preparing SWE-QA-Pro answer benchmark", enabled=enabled):
        return SweQaProDatasetPreparer().prepare(
            dataset, limit=max(int(args.cases or 1), 1), repo=args.repo
        )


def expand_answer_benchmark(
    args: argparse.Namespace,
    dataset: Path,
    requested_cases: int,
    *,
    enabled: bool = True,
) -> dict[str, Any]:
    if not args.yes and not sys.stdin.isatty():
        raise RuntimeError(
            f"SWE-QA-Pro answer dataset has fewer than {requested_cases} cases; pass --yes to expand it."
        )
    if not args.yes:
        print(
            f"Benchmark has fewer than {requested_cases} local cases.\n"
            f"Repo filter: {args.repo or '(none)'}\n"
            f"Local output: {dataset}\n"
            "Expand it now? [y/N] ",
            end="",
            file=sys.stderr,
        )
        if input().strip().lower() not in {"y", "yes"}:
            raise RuntimeError(f"Benchmark assets not expanded for '{args.benchmark}'.")
    with render_activity("expanding SWE-QA-Pro answer benchmark", enabled=enabled):
        return SweQaProDatasetPreparer().prepare(
            dataset, limit=requested_cases, repo=args.repo
        )


def _render_metrics_section(title: str, metrics: dict[str, Any], keys: tuple[str, ...]) -> None:
    present = [key for key in keys if key in metrics]
    if not present:
        return
    table = Table(title=title)
    table.add_column("metric", style="cyan")
    table.add_column("value", justify="right")
    for key in present:
        table.add_row(key, answer_report_metric_cell(metrics, key))
    Console().print(table)


def render_answer_metrics_table(metrics: dict[str, Any]) -> None:
    # `context_bundle_complete` leads: it is the deterministic, model-free bottleneck metric.
    # The judge criteria are printed in a visually separate, explicitly-labelled section
    # because until the local judge is validated its numbers are not comparable to historical
    # ones -- and a sum of the six criteria is never computed, since it rewards citation-format
    # density over correctness (a judge halo effect).
    _render_metrics_section(
        "e2e answer metrics -- PRIMARY (deterministic)",
        metrics,
        (
            *PRIMARY_METRICS,
            "planned_query_count",
            "planning_duration_ms",
            "rerank_duration_ms",
            "citation_count",
        ),
    )
    _render_metrics_section(
        "e2e answer metrics -- cost / latency",
        metrics,
        (*DURATION_METRICS, "answer_duration_ms_total"),
    )
    _render_metrics_section(
        "e2e answer metrics -- SECONDARY, unvalidated (LLM judge)",
        metrics,
        JUDGE_METRICS,
    )


def cmd_experiment(args: argparse.Namespace, config: AppConfig) -> int:
    if args.hypothesis:
        selected = set(args.hypothesis)
        config = replace(
            config,
            experiments=replace(
                config.experiments,
                hypotheses=[
                    hypothesis
                    for hypothesis in config.experiments.hypotheses
                    if hypothesis.name in selected
                ],
            ),
        )
        missing = selected - {
            hypothesis.name for hypothesis in config.experiments.hypotheses
        }
        if missing:
            raise ValueError(
                f"Unknown experiment hypothesis: {', '.join(sorted(missing))}"
            )
    vector_store = None if args.reindex else make_vector_store(config)
    needs_index = args.reindex or not vector_store.exists()
    if needs_index:
        if vector_store is not None:
            close_vector_store(vector_store)
        cmd_index(args, config)
        vector_store = make_vector_store(config)

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
        metric_rows, case_rows = ExperimentMetricsMapper().to_rows(
            experiment_run, config, args.config
        )
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
            print(
                f"  {name}: {value:.4f}"
                if isinstance(value, float)
                else f"  {name}: {value}"
            )
    if config.metrics.enabled:
        print(f"\nrecorded_rows: {saved_rows}")
    return 0


def cmd_monitor(args: argparse.Namespace, config: AppConfig) -> int:
    if args.trace is None and not config.trace.enabled:
        print(
            "Tracing is disabled in config. Pass --trace <path> to monitor an existing trace file."
        )
        return 1
    trace_path = args.trace or config.trace.artifact
    TraceMonitor(
        trace_path=trace_path,
        refresh_seconds=float(args.refresh),
        max_events=int(args.max_events),
    ).run()
    return 0


def normalize_query(query: str | list[str]) -> str:
    if isinstance(query, list):
        return " ".join(query).strip()
    return query.strip()


def run_search(config: AppConfig, query: str, limit: int) -> list[SearchResult]:
    vector_store = make_vector_store(config)
    try:
        if not vector_store.exists():
            raise ValueError(
                f"Index not found in {store_label(config)}. Run `code-diver index` first."
            )
        provider = make_embedding_provider(config, vector_store.metadata())
        prepared_query = make_plugin_manager(config).prepare_query(query)
        return make_retrieval_strategy(config, provider, vector_store).search(
            prepared_query, limit
        )
    finally:
        close_vector_store(vector_store)


def make_indexing_service(config: AppConfig, progress: bool = True) -> IndexingService:
    return IndexingService(
        make_codebase_scanner(config),
        make_plugin_manager(config),
        make_vector_store(config),
        IndexingOptions(
            embedding_batch_size=config.embedding.batch_size,
            embedding_workers=config.embedding.workers,
            embedding_max_input_chars=config.embedding.max_input_chars,
            embedding_max_input_tokens=config.embedding.max_input_tokens,
            embedding_token_safety_margin=config.embedding.token_safety_margin,
            progress=progress,
        ),
        make_trace_logger(config),
    )


def generate_local_eval_dataset(
    config: AppConfig, output: Path, case_count: int
) -> list[dict[str, Any]]:
    scanner = CodebaseScanner(
        include=config.scanner.include,
        exclude=config.scanner.exclude,
        max_file_bytes=config.scanner.max_file_bytes,
        line_chunks=False,
        file_summary_chunks=True,
        file_summary_head_line_max_chars=config.scanner.file_summary_head_line_max_chars,
        file_summary_head_block_max_chars=config.scanner.file_summary_head_block_max_chars,
        file_manifest_chunks=True,
        file_api_manifest_chunks=config.scanner.file_api_manifest_chunks,
        file_body_evidence_chunks=config.scanner.file_body_evidence_chunks,
        documentation_summary_chunks=config.scanner.documentation_summary_chunks,
        documentation_manifest_chunks=config.scanner.documentation_manifest_chunks,
        documentation_chunk_chunks=config.scanner.documentation_chunk_chunks,
        max_symbols_per_file=config.scanner.max_symbols_per_file,
    )
    return LocalEvalDatasetGenerator(scanner).generate(config.root, output, case_count)


def make_codebase_scanner(config: AppConfig):
    scanner = CodebaseScanner(
        include=config.scanner.include,
        exclude=config.scanner.exclude,
        max_file_bytes=config.scanner.max_file_bytes,
        line_chunks=config.scanner.line_chunks,
        chunk_lines=config.scanner.chunk_lines,
        structural_chunks=config.scanner.structural_chunks,
        symbol_chunks=config.scanner.symbol_chunks,
        symbol_body=config.scanner.symbol_body,
        file_summary_chunks=config.scanner.file_summary_chunks,
        file_summary_head_line_max_chars=config.scanner.file_summary_head_line_max_chars,
        file_summary_head_block_max_chars=config.scanner.file_summary_head_block_max_chars,
        file_summary_compact_budget=config.scanner.file_summary_compact_budget,
        file_summary_compact_path=config.scanner.file_summary_compact_path,
        file_summary_term_stopwords=config.scanner.file_summary_term_stopwords,
        file_manifest_chunks=config.scanner.file_manifest_chunks,
        file_manifest_symbol_surface=config.scanner.file_manifest_symbol_surface,
        file_api_manifest_chunks=config.scanner.file_api_manifest_chunks,
        file_body_evidence_chunks=config.scanner.file_body_evidence_chunks,
        file_purpose_chunks=config.scanner.file_purpose_chunks,
        symbol_chunk_chunks=config.scanner.symbol_chunk_chunks,
        documentation_summary_chunks=config.scanner.documentation_summary_chunks,
        documentation_manifest_chunks=config.scanner.documentation_manifest_chunks,
        documentation_chunk_chunks=config.scanner.documentation_chunk_chunks,
        max_symbols_per_file=config.scanner.max_symbols_per_file,
    )
    mode = config.indexing.mode
    if mode == "scanner":
        return scanner
    if mode == "orchestrated":
        return OrchestratedCodebaseScanner(
            scanner,
            create_generation_provider(config),
            config,
            make_trace_logger(config),
        )
    ai_scanner = AiCodebaseScanner(
        scanner, create_generation_provider(config), config.indexing.ai
    )
    if mode == "ai":
        return ai_scanner
    if mode == "hybrid":
        return HybridCodebaseScanner([scanner, ai_scanner])
    raise ValueError(f"Unknown indexing mode: {mode}")


def make_plugin_manager(config: AppConfig) -> PluginManager:
    return PluginManager([Path(path) for path in config.plugins])


def make_trace_logger(config: AppConfig) -> TraceLogger:
    return TraceLogger(config.trace)


def indexing_hypotheses(config: AppConfig, names: list[str] | None = None):
    selected_names = set(names or [])
    return [
        hypothesis
        for hypothesis in config.experiments.hypotheses
        if not selected_names or hypothesis.name in selected_names
        if "code_diver_index_selected"
        in resolve_hypothesis_tools(config, hypothesis.name)
    ]


def search_tool_hypotheses(config: AppConfig, names: list[str] | None = None):
    selected_names = set(names or [])
    return [
        hypothesis
        for hypothesis in config.experiments.hypotheses
        if not selected_names or hypothesis.name in selected_names
        if resolve_hypothesis_tools(config, hypothesis.name)
        if "code_diver_index_selected"
        not in resolve_hypothesis_tools(config, hypothesis.name)
    ]


def resolve_hypothesis_tools(config: AppConfig, hypothesis_name: str) -> list[str]:
    hypothesis = next(
        (
            candidate
            for candidate in config.experiments.hypotheses
            if candidate.name == hypothesis_name
        ),
        None,
    )
    if hypothesis is None:
        return []
    if hypothesis.tools:
        return hypothesis.tools
    if hypothesis.toolset:
        return config.pi.toolsets.get(hypothesis.toolset, [])
    return config.pi.tools


def config_for_indexing_hypothesis(
    config: AppConfig, hypothesis_name: str, run_id: str
) -> AppConfig:
    qdrant = replace(
        config.storage.qdrant,
        collection=f"{config.storage.qdrant.collection}_{hypothesis_name}_{run_id}",
    )
    return replace(
        config,
        artifact=suffixed_artifact_path(config.artifact, hypothesis_name, run_id),
        storage=replace(config.storage, qdrant=qdrant),
        graph=replace(
            config.graph,
            artifact=suffixed_artifact_path(
                config.graph.artifact, hypothesis_name, run_id
            ),
        ),
    )


def config_for_search_hypothesis(config: AppConfig, hypothesis: Any) -> AppConfig:
    search_config = config
    if getattr(hypothesis, "strategy", None):
        search_config = replace(
            search_config,
            search=replace(search_config.search, strategy=hypothesis.strategy),
        )
    if getattr(hypothesis, "generation", None) is not None:
        search_config = replace(search_config, generation=hypothesis.generation)
    if getattr(hypothesis, "graph_file_search", None) is not None:
        search_config = replace(
            search_config, graph_file_search=hypothesis.graph_file_search
        )
    if getattr(hypothesis, "hybrid_search", None) is not None:
        search_config = replace(search_config, hybrid_search=hypothesis.hybrid_search)
    if getattr(hypothesis, "llm_rerank", None) is not None:
        search_config = replace(search_config, llm_rerank=hypothesis.llm_rerank)
    if getattr(hypothesis, "cross_encoder_rerank", None) is not None:
        search_config = replace(
            search_config, cross_encoder_rerank=hypothesis.cross_encoder_rerank
        )
    return search_config


def indexing_hypothesis_log_path(
    config: AppConfig, hypothesis_name: str, run_id: str
) -> Path:
    base = (
        config.trace.artifact.parent
        if config.trace.artifact
        else Path(".code-diver/traces")
    )
    return base / "orchestrator-indexing" / run_id / f"{hypothesis_name}.jsonl"


def search_hypothesis_log_path(
    config: AppConfig, hypothesis_name: str, run_id: str
) -> Path:
    base = (
        config.trace.artifact.parent
        if config.trace.artifact
        else Path(".code-diver/traces")
    )
    return base / "orchestrator-search" / run_id / f"{hypothesis_name}.jsonl"


def make_graph_indexer(config: AppConfig):
    if not config.graph.enabled:
        return None

    def build(items: list[Any]) -> None:
        GraphIndexingService(
            CodeGraphBuilder(
                ast_enabled=config.graph.ast_enabled,
                reference_edges_enabled=config.graph.reference_edges_enabled,
                call_edges_enabled=config.graph.call_edges_enabled,
            ),
            CodeGraphStore(config.graph.artifact),
        ).build(config.root, items)

    return build


def suffixed_artifact_path(path: Path, hypothesis_name: str, run_id: str) -> Path:
    return path.with_name(f"{path.stem}_{hypothesis_name}_{run_id}{path.suffix}")


def fan_out_union_rerank_enabled(hypothesis: Any) -> bool:
    settings = getattr(hypothesis, "fan_out_fusion", None)
    return bool(settings is not None and settings.enabled and settings.union_rerank)


def make_fan_out_union_handler(
    config: AppConfig,
    provider: Any,
    vector_store: Any,
    settings: Any,
):
    """H-76: probes on the cross-encoder-less champion base, one cross-encoder pass over the union."""
    workers = int(getattr(settings, "max_probe_workers", 6) or 6)
    parallel = bool(getattr(settings, "parallel_probes", True))
    search = FanOutUnionRerankSearch(
        RetrievalStrategyFactory().create(
            RetrievalStrategyId.GRAPH_FILE.value, config, provider, vector_store
        ),
        RerankProviderFactory().create(config.cross_encoder_rerank),
        config.cross_encoder_rerank,
        repository_root=config.root,
        max_workers=workers if parallel else 1,
        union_candidate_limit=settings.union_candidate_limit,
        parallel_probes=parallel,
    )

    def handle(queries: list[str], limit: int, per_query_limit: int) -> list[str]:
        return search.paths(queries, limit, per_query_limit)

    return handle


def make_search_tool_handler(strategy: Any):
    kind_resolver = CodeItemIndexKindResolver()

    def handle(query: str, limit: int) -> str:
        results = strategy.search(query, limit)
        return json.dumps(
            [
                {
                    "id": result.item.id,
                    "path": result.item.path,
                    "title": result.item.title,
                    "startLine": result.item.start_line,
                    "endLine": result.item.end_line,
                    "score": result.score,
                    "indexKind": kind_resolver.resolve(result.item),
                    "preview": compact_preview(result.item.content, 360),
                }
                for result in results
            ],
            indent=2,
        )

    return handle


def format_index_composition(items: list[Any]) -> str:
    composition = IndexCompositionAnalyzer().analyze(items)
    items_by_kind = composition["items_by_kind"]
    if not items_by_kind:
        return "Index composition: empty"
    pairs = ", ".join(f"{kind}={count}" for kind, count in items_by_kind.items())
    content_mb = composition["content_bytes_total"] / 1_000_000
    return (
        f"Index composition: {pairs}; unique_paths={composition['unique_paths']}; "
        f"content_mb={content_mb:.2f}; content_bytes_mean={composition['content_bytes_mean']:.1f}"
    )


def make_rerank_tool_handler(config: AppConfig, generation_provider: Any):
    handler = RerankToolHandler(generation_provider, config.llm_rerank)

    def rerank(
        query: str, candidates: list[dict[str, Any]], limit: int, args: dict[str, Any]
    ) -> dict[str, Any]:
        return handler.rerank(query, candidates, limit, args)

    return rerank


def make_ephemeral_search_tool_handler(config: AppConfig):
    scanner = CodebaseScanner(
        include=config.scanner.include,
        exclude=config.scanner.exclude,
        max_file_bytes=config.scanner.max_file_bytes,
        line_chunks=False,
        chunk_lines=config.scanner.chunk_lines,
        structural_chunks=True,
        symbol_chunks=True,
        symbol_body=True,
        file_summary_chunks=False,
        file_manifest_chunks=False,
        file_api_manifest_chunks=False,
        file_body_evidence_chunks=False,
        documentation_summary_chunks=False,
        documentation_manifest_chunks=False,
        documentation_chunk_chunks=False,
        max_symbols_per_file=config.scanner.max_symbols_per_file,
    )
    service = EphemeralDeepIndexService(
        CandidateFileScanner(scanner),
        IndexingOptions(
            embedding_batch_size=config.embedding.batch_size,
            embedding_workers=config.embedding.workers,
            embedding_max_input_chars=config.embedding.max_input_chars,
            embedding_max_input_tokens=config.embedding.max_input_tokens,
            embedding_token_safety_margin=config.embedding.token_safety_margin,
            progress=False,
        ),
    )

    def search(
        query: str, files: list[str], limit: int, args: dict[str, Any]
    ) -> dict[str, Any]:
        provider = make_embedding_provider(config)
        index = service.build(
            config.root,
            files[: int(args.get("fileLimit") or args.get("file_limit") or 30)],
            provider,
        )
        search_result = service.search(index, provider, query, limit)
        return {
            "candidates": [
                {
                    "id": result.item.id,
                    "path": result.item.path,
                    "title": result.item.title,
                    "startLine": result.item.start_line,
                    "endLine": result.item.end_line,
                    "score": result.score,
                    "indexKind": CodeItemIndexKindResolver().resolve(result.item),
                    "breadcrumb": result.item.metadata.get("breadcrumb"),
                    "preview": compact_preview(result.item.content, 420),
                }
                for result in search_result.results
            ],
            "metrics": {
                "ephemeral_build_ms": index.build_ms,
                "ephemeral_query_ms": search_result.query_ms,
                "temporary_vectors": index.temporary_vectors,
                "cache_hits": index.cache_hits,
                "cache_misses": index.cache_misses,
                "cache_hit_rate": index.cache_hit_rate,
                "candidate_files": len(files),
            },
        }

    return search


def compact_preview(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


def direct_search_eval_result(case: Any, retrieved: list[str], limit: int):
    matched_ranks = [
        rank
        for rank, value in enumerate(retrieved[:limit], start=1)
        if direct_search_matches_any(value, case.expected)
    ]
    hit = bool(matched_ranks)
    reciprocal_rank = 1.0 / matched_ranks[0] if matched_ranks else 0.0
    match_count = len(matched_ranks)
    file_metrics = direct_search_file_metrics(case.expected, retrieved[:limit], limit)
    return EvalResult(
        case_id=case.id,
        query=case.query,
        expected=case.expected,
        retrieved=retrieved[:limit],
        hit=hit,
        reciprocal_rank=reciprocal_rank,
        precision=match_count / max(len(retrieved[:limit]), 1),
        recall=min(match_count / max(len(case.expected), 1), 1.0),
        retrieved_files=file_metrics["retrieved_files"],
        bucket=EvalCaseBucketClassifier().classify(case.query),
        file_hit=file_metrics["file_hit"],
        file_reciprocal_rank=file_metrics["file_mrr"],
        file_precision_at_r=file_metrics["file_precision_at_r"],
        file_recall=file_metrics["file_recall"],
        ndcg=file_metrics["ndcg"],
        average_precision=file_metrics["average_precision"],
    )


def direct_search_matches_any(path: str, expected: list[str]) -> bool:
    return any(direct_search_matches(path, value) for value in expected)


def direct_search_matches(path: str, expected: str) -> bool:
    normalized = expected.strip()
    if normalized.startswith("glob:"):
        return fnmatch.fnmatchcase(
            direct_search_file_path(path), normalized.removeprefix("glob:")
        )
    return (
        path == normalized or path.startswith((normalized + "#", normalized + "::", normalized.rstrip("/") + "/"))
    )


def direct_search_file_metrics(
    expected: list[str], retrieved: list[str], limit: int
) -> dict[str, Any]:
    files = dedupe_preserving_order(
        direct_search_file_path(value) for value in retrieved[:limit]
    )
    matched_ranks = [
        rank
        for rank, path in enumerate(files, start=1)
        if direct_search_matches_any(path, expected)
    ]
    expected_count = max(len(expected), 1)
    matched_expected_count = sum(
        1
        for value in expected
        if any(direct_search_matches(path, value) for path in files)
    )
    r = min(expected_count, limit)
    top_r = files[:r]
    return {
        "retrieved_files": files,
        "file_hit": bool(matched_ranks),
        "file_mrr": 1.0 / matched_ranks[0] if matched_ranks else 0.0,
        "file_precision_at_r": sum(
            1 for path in top_r if direct_search_matches_any(path, expected)
        )
        / max(r, 1),
        "file_recall": min(matched_expected_count / expected_count, 1.0),
        "ndcg": direct_search_ndcg(files, expected, limit),
        "average_precision": direct_search_average_precision(files, expected),
    }


def direct_search_file_path(value: str) -> str:
    return value.split("#", 1)[0].split("::", 1)[0]


def dedupe_preserving_order(values: Any) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        text = str(value)
        if text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def direct_search_ndcg(files: list[str], expected: list[str], limit: int) -> float:
    import math

    dcg = 0.0
    matched_expected: set[int] = set()
    for rank, path in enumerate(files[:limit], start=1):
        match_index = first_unmatched_direct_expected(path, expected, matched_expected)
        if match_index is not None:
            matched_expected.add(match_index)
            dcg += 1.0 / math.log2(rank + 1)
    ideal_relevant = min(len(expected), limit)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_relevant + 1))
    return dcg / ideal if ideal else 0.0


def direct_search_average_precision(files: list[str], expected: list[str]) -> float:
    hits = 0
    total = 0.0
    matched_expected: set[int] = set()
    for rank, path in enumerate(files, start=1):
        match_index = first_unmatched_direct_expected(path, expected, matched_expected)
        if match_index is None:
            continue
        matched_expected.add(match_index)
        hits += 1
        total += hits / rank
    return total / max(len(expected), 1)


def first_unmatched_direct_expected(
    path: str, expected: list[str], matched: set[int]
) -> int | None:
    for index, value in enumerate(expected):
        if index in matched:
            continue
        if direct_search_matches(path, value):
            return index
    return None


def direct_search_metrics(
    results: list[Any], durations_ms: list[float], limit: int
) -> dict[str, Any]:
    metrics = {
        "cases": len(results),
        f"hit_rate@{limit}": mean(1.0 if result.hit else 0.0 for result in results),
        f"mrr@{limit}": mean(result.reciprocal_rank for result in results),
        f"precision@{limit}": mean(result.precision for result in results),
        f"recall@{limit}": mean(result.recall for result in results),
        "hit_rate@1": mean(
            1.0
            if any(
                direct_search_matches_any(value, result.expected)
                for value in result.retrieved[:1]
            )
            else 0.0
            for result in results
        ),
        "hit_rate@3": mean(
            1.0
            if any(
                direct_search_matches_any(value, result.expected)
                for value in result.retrieved[:3]
            )
            else 0.0
            for result in results
        ),
        "hit_rate@5": mean(
            1.0
            if any(
                direct_search_matches_any(value, result.expected)
                for value in result.retrieved[:5]
            )
            else 0.0
            for result in results
        ),
        "file_hit_rate@1": mean(
            1.0 if direct_search_file_hit_at(result, 1) else 0.0 for result in results
        ),
        "file_hit_rate@3": mean(
            1.0 if direct_search_file_hit_at(result, 3) else 0.0 for result in results
        ),
        "file_hit_rate@5": mean(
            1.0 if direct_search_file_hit_at(result, 5) else 0.0 for result in results
        ),
        f"file_hit_rate@{limit}": mean(
            1.0 if result.file_hit else 0.0 for result in results
        ),
        f"file_mrr@{limit}": mean(result.file_reciprocal_rank for result in results),
        "file_precision@R": mean(result.file_precision_at_r for result in results),
        f"file_recall@{limit}": mean(result.file_recall for result in results),
        f"ndcg@{limit}": mean(result.ndcg for result in results),
        f"map@{limit}": mean(result.average_precision for result in results),
        "search_duration_ms_total": sum(durations_ms),
        "search_duration_ms_mean": mean(durations_ms),
        "search_duration_ms_p95": percentile(durations_ms, 0.95),
    }
    statistics = EvaluationStatistics()
    series = [
        (f"hit_rate@{limit}", (1.0 if result.hit else 0.0 for result in results), True),
        (f"mrr@{limit}", (result.reciprocal_rank for result in results), False),
        (f"precision@{limit}", (result.precision for result in results), False),
        (f"recall@{limit}", (result.recall for result in results), False),
        (
            "hit_rate@1",
            (
                1.0
                if any(
                    direct_search_matches_any(value, result.expected)
                    for value in result.retrieved[:1]
                )
                else 0.0
                for result in results
            ),
            True,
        ),
        (
            "hit_rate@3",
            (
                1.0
                if any(
                    direct_search_matches_any(value, result.expected)
                    for value in result.retrieved[:3]
                )
                else 0.0
                for result in results
            ),
            True,
        ),
        (
            "hit_rate@5",
            (
                1.0
                if any(
                    direct_search_matches_any(value, result.expected)
                    for value in result.retrieved[:5]
                )
                else 0.0
                for result in results
            ),
            True,
        ),
        (
            "file_hit_rate@1",
            (
                1.0 if direct_search_file_hit_at(result, 1) else 0.0
                for result in results
            ),
            True,
        ),
        (
            "file_hit_rate@3",
            (
                1.0 if direct_search_file_hit_at(result, 3) else 0.0
                for result in results
            ),
            True,
        ),
        (
            "file_hit_rate@5",
            (
                1.0 if direct_search_file_hit_at(result, 5) else 0.0
                for result in results
            ),
            True,
        ),
        (
            f"file_hit_rate@{limit}",
            (1.0 if result.file_hit else 0.0 for result in results),
            True,
        ),
        (
            f"file_mrr@{limit}",
            (result.file_reciprocal_rank for result in results),
            False,
        ),
        ("file_precision@R", (result.file_precision_at_r for result in results), False),
        (f"file_recall@{limit}", (result.file_recall for result in results), False),
        (f"ndcg@{limit}", (result.ndcg for result in results), False),
        (f"map@{limit}", (result.average_precision for result in results), False),
        ("search_duration_ms_mean", durations_ms, False),
    ]
    for name, values, binary in series:
        metrics.update(statistics.summarize(name, values, binary=binary))
    return metrics


def direct_search_file_hit_at(result: Any, limit: int) -> bool:
    return any(
        direct_search_matches_any(value, result.expected)
        for value in result.retrieved_files[:limit]
    )


def empty_agent_usage() -> dict[str, Any]:
    return {
        "model_calls": 0,
        "tool_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "total_cost": 0.0,
        "models": [],
    }


def merge_agent_usage(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key in [
        "model_calls",
        "tool_calls",
        "input_tokens",
        "output_tokens",
        "total_tokens",
    ]:
        target[key] += int(source.get(key) or 0)
    target["total_cost"] += float(source.get("total_cost") or 0.0)
    for model in source.get("models") or []:
        if model not in target["models"]:
            target["models"].append(model)


def mean(values: Any) -> float:
    materialized = list(values)
    if not materialized:
        return 0.0
    return sum(materialized) / len(materialized)


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(round((len(ordered) - 1) * quantile), len(ordered) - 1)
    return ordered[index]


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
        client = ClickHouseClient(
            metrics.url, metrics.username, metrics.password, metrics.timeout_seconds
        )
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
    return {
        SchemaKey.SCORE.value: result.score,
        SchemaKey.ITEM.value: result.item.to_json(),
    }


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
        "retrieved_files": result.retrieved_files or [],
        "bucket": result.bucket,
        "top_result_kind": result.top_result_kind,
        "first_relevant_kind": result.first_relevant_kind,
        "file_hit": result.file_hit,
        "file_reciprocal_rank": result.file_reciprocal_rank,
        "file_precision_at_r": result.file_precision_at_r,
        "file_recall": result.file_recall,
        "ndcg": result.ndcg,
        "average_precision": result.average_precision,
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
                "results": [
                    eval_result_to_json(result) for result in strategy_result.results
                ],
            }
            for strategy_result in run.strategy_results
        ],
    }
