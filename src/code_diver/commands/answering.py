from __future__ import annotations

import argparse
import contextlib
import json
import sys
from dataclasses import replace
from pathlib import Path
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

from ..answering import (
    AnswerJudge,
    AnswerPairwiseJudge,
    AnswerPairwiseReport,
    AnswerReportJudge,
    AnswerReportMetrics,
)
from ..answering.answer_pipeline_factory import AnswerPipelineFactory
from ..answering.answer_pipeline_options import AnswerPipelineOptions
from ..answering.answer_report_metrics import (
    DURATION_METRICS,
    JUDGE_METRICS,
    PRIMARY_METRICS,
)
from ..answering.answer_service import AnswerService
from ..config import AppConfig, ConfigLoader
from ..generation import create_generation_provider
from ..pi import (
    AgyCliAgentRunner,
    GeminiCliAgentRunner,
    PiRunner,
    PiSessionOptions,
)
from ..pi.repository_context_resolver import build_repository_context
from ..runtime import QdrantRuntimeManager
from ..settings import VectorStoreProviderId
from ..store import create_vector_store

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


def normalize_query(query: str | list[str] | None) -> str:
    """Normalize query strings or list of tokens into a single trimmed string."""
    if query is None:
        return ""
    if isinstance(query, list):
        return " ".join(query).strip()
    return query.strip()


def compact_preview(text: str, limit: int) -> str:
    """Return a single-line compact whitespace preview truncated to limit."""
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


def status_console() -> Console:
    """Return the console instance used for status messages and progress reporting."""
    return Console(stderr=True, color_system="auto")


def render_status_panel(
    title: str, rows: list[tuple[str, object]], border_style: str = "cyan"
) -> None:
    """Render a structured status panel to stderr."""
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
    """Render a single status line prefixed with [code-diver]."""
    status_console().print(f"[{style}]\\[code-diver][/{style}] {message}")


@contextlib.contextmanager
def render_activity(message: str, enabled: bool = True, style: str = "cyan"):
    """Context manager to display an active spinner and message."""
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
        yield


def store_label(config: AppConfig) -> str:
    """Format a human-readable identifier for the configured vector store."""
    provider = config.storage.provider
    if provider == VectorStoreProviderId.QDRANT.value:
        return f"{provider}:{config.storage.qdrant.collection}"
    return str(config.artifact)


def close_vector_store(vector_store: Any) -> None:
    """Close the vector store connection if applicable."""
    close = getattr(vector_store, "close", None)
    if callable(close):
        close()


def ensure_storage_runtime(config: AppConfig, progress: bool = True) -> None:
    """Ensure supporting runtime dependencies (e.g. Qdrant) are ready."""
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
    """Create and return a vector store instance for the given configuration."""
    ensure_storage_runtime(config, progress=progress)
    return create_vector_store(config)


def make_search_agent_runner(config: AppConfig):
    """Instantiate the appropriate agent runner based on the configured provider."""
    if config.pi.provider in AgyCliAgentRunner.PROVIDERS:
        return AgyCliAgentRunner()
    if config.pi.provider in GeminiCliAgentRunner.PROVIDERS:
        return GeminiCliAgentRunner()
    return PiRunner()


def answer_pipeline_options(
    args: argparse.Namespace, config: AppConfig
) -> AnswerPipelineOptions:
    """Build AnswerPipelineOptions from parsed CLI arguments and AppConfig."""
    return AnswerPipelineOptions(
        limit=getattr(args, "limit", None),
        context_files=getattr(args, "context_files", None),
        context_lines=getattr(args, "context_lines", None),
        agentic_queries=bool(getattr(args, "agentic_queries", False)),
        agentic_query_rerank=bool(getattr(args, "agentic_query_rerank", False)),
        agentic_query_search_strategy=getattr(
            args, "agentic_query_search_strategy", None
        ),
        query_count=getattr(args, "query_count", None),
        query_workers=getattr(args, "query_workers", None),
    )


def answer_outcome_to_json(outcome: Any, include_context: bool) -> dict[str, Any]:
    """Convert an AnswerOutcome into a JSON-serializable dictionary."""
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
    """Display an AnswerOutcome using Rich formatting."""
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


def cmd_answer(args: argparse.Namespace, config: AppConfig) -> int:
    """Execute grounded question answering using candidate retrieval and context generation."""
    query = normalize_query(args.query)
    if not query:
        print("error: answer requires a question.", file=sys.stderr)
        return 1
    vector_store = make_vector_store(config, progress=not bool(getattr(args, "json", False)))
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
            enabled=not bool(getattr(args, "json", False)),
            style="green",
        ):
            pipeline = AnswerPipelineFactory().create(
                config,
                vector_store,
                answer_pipeline_options(args, config),
                on_notice=None
                if getattr(args, "json", False)
                else (lambda text: status_console().print(f"[yellow]{text}[/yellow]")),
            )
            service = AnswerService.from_pipeline(
                pipeline,
                restrict_citations_to_context=pipeline.config.evaluation.restrict_citations_to_context,
            )
            outcome = service.answer(query)
    finally:
        close_vector_store(vector_store)
    if getattr(args, "json", False):
        print(
            json.dumps(
                answer_outcome_to_json(
                    outcome, bool(getattr(args, "show_context", False))
                ),
                indent=2,
            )
        )
        return 0 if outcome.parse_error is None else 1
    return render_answer(outcome, pipeline, bool(getattr(args, "show_context", False)))


def cmd_ask(args: argparse.Namespace, config: AppConfig) -> int:
    """Execute question answering, either via direct pipeline or through an exploration agent."""
    if not getattr(args, "agent", False):
        # The default: one question, one grounded answer, through the measured pipeline.
        return cmd_answer(args, config)
    build_repository_context(config)
    return make_search_agent_runner(config).run_print(
        config,
        getattr(args, "config", None),
        normalize_query(args.query),
        toolset=getattr(args, "toolset", None),
        hypothesis=getattr(args, "hypothesis", None),
    )


def chat_prompt_and_session(
    args: argparse.Namespace, config: AppConfig
) -> tuple[str | None, PiSessionOptions]:
    """Parse interactive chat prompt and session configuration from CLI args."""
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


def cmd_chat(args: argparse.Namespace, config: AppConfig) -> int:
    """Start an interactive chat session with the code exploration agent."""
    build_repository_context(config)
    prompt, session = chat_prompt_and_session(args, config)
    return make_search_agent_runner(config).run_interactive(
        config,
        getattr(args, "config", None),
        prompt,
        toolset=getattr(args, "toolset", None),
        hypothesis=getattr(args, "hypothesis", None),
        session=session,
    )


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


def answer_report_root(payload: dict[str, Any], config: AppConfig) -> Path | None:
    """Extract repository root path from a report payload, falling back to config."""
    settings = (
        payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
    )
    root = settings.get("root") if settings else None
    if root:
        return Path(str(root))
    return config.root if config.root else None


def answer_report_metric_cell(metrics: dict[str, Any], key: str) -> str:
    """Format a metric value for table display, appending 95% confidence intervals when present."""
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


def render_answer_report_comparison(comparison: dict[str, Any]) -> None:
    """Render a table comparing multiple evaluation reports across primary and secondary metrics."""
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


def apply_runtime_config(args: argparse.Namespace, config: AppConfig) -> AppConfig:
    """Resolve and apply runtime CLI options to AppConfig."""
    try:
        from ..cli import apply_runtime_config as _apply

        return _apply(args, config)
    except ImportError:
        return config


def cmd_answer_report_judge(args: argparse.Namespace, config: AppConfig) -> int:
    """Evaluate an existing answer report using an LLM judge."""
    report_path = args.reports[0]
    payload = AnswerReportMetrics().load(report_path)
    judge_config = (
        ConfigLoader().load(args.judge_config)
        if getattr(args, "judge_config", None)
        else config
    )
    judge_config = apply_runtime_config(args, judge_config)
    if getattr(args, "judge_model", None):
        judge_config = replace(
            judge_config,
            generation=replace(judge_config.generation, model=args.judge_model),
        )
    root = answer_report_root(payload, config)
    output = getattr(args, "output", None) or report_path.with_name(
        f"{report_path.stem}.judged.json"
    )
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
    source_rows = [
        row for row in payload.get("results") or [] if isinstance(row, dict)
    ]
    if not getattr(args, "json", False):
        render_status_panel(
            "Post-hoc Answer Judge",
            [
                ("source", report_path),
                ("output", output),
                ("cases", len(source_rows)),
                ("root", root or "(context_text only)"),
                (
                    "judge model",
                    f"{judge_config.generation.provider}:{judge_config.generation.model}",
                ),
                (
                    "prompt",
                    getattr(args, "judge_prompt", None)
                    or AnswerJudge.DEFAULT_PROMPT_PATH,
                ),
                ("workers", getattr(args, "workers", 1)),
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
                prompt_path=getattr(args, "judge_prompt", None),
            ),
            root=root,
            context_files=getattr(args, "context_files", None),
            context_lines=getattr(args, "context_lines", None),
            max_file_bytes=judge_config.scanner.max_file_bytes,
            workers=getattr(args, "workers", 1),
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
    if getattr(args, "json", False):
        print(json.dumps(judged, indent=2, ensure_ascii=False))
        return 0
    print(f"saved judged answer report: {output}")
    render_answer_metrics_table(judged["metrics"])
    return 0


def cmd_answer_report(args: argparse.Namespace, config: AppConfig) -> int:
    """Compare or judge answer evaluation reports."""
    if getattr(args, "judge", False):
        if len(args.reports) != 1:
            print("error: --judge accepts exactly one report", file=sys.stderr)
            return 1
        return cmd_answer_report_judge(args, config)
    comparison = AnswerReportMetrics().compare(args.reports)
    if getattr(args, "output", None):
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(comparison, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    if getattr(args, "json", False):
        print(json.dumps(comparison, indent=2, ensure_ascii=False))
        return 0
    render_answer_report_comparison(comparison)
    if getattr(args, "output", None):
        print(f"saved answer report comparison: {args.output}")
    return 0


def render_answer_pairwise_summary(result: dict[str, Any]) -> None:
    """Render summary table and statistics for pairwise answer comparison."""
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
        Console().print(
            f"[yellow]judge errors: {len(result['judge_errors'])} case(s) dropped[/yellow]"
        )


def cmd_answer_pairwise(args: argparse.Namespace, config: AppConfig) -> int:
    """Run head-to-head pairwise comparison between two answer evaluation reports."""
    baseline_payload = AnswerReportMetrics().load(args.baseline)
    arm_payload = AnswerReportMetrics().load(args.arm)
    judge_config = (
        ConfigLoader().load(args.judge_config)
        if getattr(args, "judge_config", None)
        else config
    )
    judge_config = apply_runtime_config(args, judge_config)
    if getattr(args, "judge_model", None):
        judge_config = replace(
            judge_config,
            generation=replace(judge_config.generation, model=args.judge_model),
        )
    baseline_name = getattr(args, "baseline_name", None) or args.baseline.stem
    arm_name = getattr(args, "arm_name", None) or args.arm.stem
    if baseline_name == arm_name:
        print(
            f"error: baseline and arm resolve to the same label {baseline_name!r}; "
            "pass --baseline-name/--arm-name so the verdicts can be told apart",
            file=sys.stderr,
        )
        return 1
    output = getattr(args, "output", None) or Path(
        f"{args.arm.with_suffix('')}.pairwise-vs-{baseline_name}.json"
    )
    if output.exists():
        print(f"error: refusing to overwrite existing {output}", file=sys.stderr)
        return 1

    progress_bar = None
    task_id = None
    if not getattr(args, "json", False):
        render_status_panel(
            "Pairwise Answer Judge",
            [
                ("baseline", f"{baseline_name} ({args.baseline})"),
                ("arm", f"{arm_name} ({args.arm})"),
                ("output", output),
                (
                    "judge model",
                    f"{judge_config.generation.provider}:{judge_config.generation.model}",
                ),
                (
                    "prompt",
                    getattr(args, "judge_prompt", None)
                    or AnswerPairwiseJudge.DEFAULT_PROMPT_PATH,
                ),
                ("workers", getattr(args, "workers", 1)),
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
                prompt_path=getattr(args, "judge_prompt", None),
            ),
            baseline_name=baseline_name,
            arm_name=arm_name,
            workers=getattr(args, "workers", 1),
            progress_callback=advance,
        ).compare_payloads(baseline_payload, arm_payload)
    finally:
        if progress_bar is not None:
            progress_bar.stop()

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    print(f"saved pairwise comparison: {output}")
    render_answer_pairwise_summary(result)
    return 0


def _render_metrics_section(
    title: str, metrics: dict[str, Any], keys: tuple[str, ...]
) -> None:
    """Render a section of the answer metrics table."""
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
    """Render end-to-end answer metrics in primary, cost/latency, and judge sections."""
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


__all__ = [
    "CI_RENDERED_METRICS",
    "answer_outcome_to_json",
    "answer_pipeline_options",
    "answer_report_metric_cell",
    "answer_report_root",
    "apply_runtime_config",
    "chat_prompt_and_session",
    "close_vector_store",
    "cmd_answer",
    "cmd_answer_pairwise",
    "cmd_answer_report",
    "cmd_answer_report_judge",
    "cmd_ask",
    "cmd_chat",
    "compact_preview",
    "ensure_storage_runtime",
    "final_rerank_settings",
    "make_search_agent_runner",
    "make_vector_store",
    "normalize_query",
    "render_activity",
    "render_answer",
    "render_answer_metrics_table",
    "render_answer_pairwise_summary",
    "render_answer_report_comparison",
    "render_status_line",
    "render_status_panel",
    "status_console",
    "store_label",
]
