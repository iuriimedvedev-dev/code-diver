from __future__ import annotations

from typing import Any

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..domain import EvalResult


class EvaluationRenderer:
    def __init__(self, color: bool = True):
        self.console = Console(color_system="auto" if color else None)

    def render(
        self,
        metrics: dict[str, Any],
        results: list[EvalResult],
        *,
        benchmark: dict[str, str | None] | None = None,
        details: bool = False,
    ) -> None:
        renderables = [self._summary_panel(metrics, benchmark)]
        if details:
            renderables.append(self._details_table(results))
        self.console.print(Group(*renderables))

    def _summary_panel(self, metrics: dict[str, Any], benchmark: dict[str, str | None] | None) -> Panel:
        title = self._gradient_title("code-diver evaluate")
        table = Table.grid(expand=True)
        table.add_column(ratio=1)
        table.add_column(ratio=1)
        if benchmark is not None:
            table.add_row("[bold]benchmark[/bold]", str(benchmark["name"]))
            table.add_row("[bold]dataset[/bold]", str(benchmark["dataset"]))
        for key in self._summary_keys(metrics):
            table.add_row(f"[bold]{key}[/bold]", self._format_value(metrics[key]))
        return Panel(table, title=title, border_style="cyan", padding=(0, 1))

    def _details_table(self, results: list[EvalResult]) -> Table:
        table = Table(title="cases", show_lines=False)
        table.add_column("case", overflow="fold")
        table.add_column("status", no_wrap=True)
        table.add_column("rr", justify="right")
        table.add_column("expected", overflow="fold")
        table.add_column("top", overflow="fold")
        for result in results:
            status = "[green]hit[/green]" if result.hit else "[red]miss[/red]"
            table.add_row(
                result.case_id,
                status,
                f"{result.reciprocal_rank:.4f}",
                ", ".join(result.expected),
                ", ".join(result.retrieved[:3]),
            )
        return table

    def _summary_keys(self, metrics: dict[str, Any]) -> list[str]:
        preferred = [
            "cases",
            "hit_rate@1",
            "hit_rate@3",
            "hit_rate@5",
            "hit_rate@10",
            "recall@10",
            "precision@10",
            "file_recall@10",
            "ndcg@10",
            "map@10",
            "search_duration_ms_mean",
            "search_duration_ms_p95",
            "degraded",
            "degraded_cases",
            "degraded_case_rate",
        ]
        return [key for key in preferred if key in metrics]

    def _format_value(self, value: Any) -> str:
        if isinstance(value, float):
            return f"{value:.4f}"
        return str(value)

    def _gradient_title(self, text: str) -> Text:
        colors = ["bright_cyan", "cyan", "blue", "magenta", "bright_magenta"]
        title = Text()
        for index, char in enumerate(text):
            title.append(char, style=f"bold {colors[index % len(colors)]}")
        return title
