from __future__ import annotations

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text

from twitter_cleaner.store.progress_db import ItemStats

console = Console()


class DeletionProgress:
    def __init__(self, label: str, total: int) -> None:
        self._label = label
        self._total = total
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TextColumn("[green]{task.fields[done]} done"),
            TextColumn("[red]{task.fields[failed]} failed"),
            TextColumn("[yellow]{task.fields[skipped]} skipped"),
        )
        self._task = self._progress.add_task(
            label, total=total, done=0, failed=0, skipped=0
        )
        self._live = Live(self._progress, console=console, refresh_per_second=4)

    def __enter__(self) -> "DeletionProgress":
        self._live.start()
        return self

    def __exit__(self, *_) -> None:
        self._live.stop()

    def update(self, stats: ItemStats) -> None:
        completed = stats.done + stats.failed + stats.skipped
        self._progress.update(
            self._task,
            completed=completed,
            done=stats.done,
            failed=stats.failed,
            skipped=stats.skipped,
        )


def print_stats_table(stats_by_type: dict[str, ItemStats]) -> None:
    table = Table(title="Progress", show_header=True, header_style="bold magenta")
    table.add_column("Type")
    table.add_column("Pending", style="yellow", justify="right")
    table.add_column("Done", style="green", justify="right")
    table.add_column("Failed", style="red", justify="right")
    table.add_column("Skipped", style="dim", justify="right")
    table.add_column("Total", justify="right")

    for item_type, s in sorted(stats_by_type.items()):
        table.add_row(
            item_type,
            str(s.pending),
            str(s.done),
            str(s.failed),
            str(s.skipped),
            str(s.total),
        )

    console.print(table)
