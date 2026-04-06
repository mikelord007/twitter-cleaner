from __future__ import annotations

from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table

from twitter_cleaner.store.progress_db import ItemStats

console = Console()

TYPE_ORDER = ["tweet", "quote", "reply", "retweet", "like"]
TYPE_LABELS = {
    "tweet": "Posts   ",
    "quote": "Quotes  ",
    "reply": "Replies ",
    "retweet": "Reposts ",
    "like": "Likes   ",
}


def _make_progress() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("[green]{task.fields[done]}✓"),
        TextColumn("[red]{task.fields[failed]}✗"),
        TextColumn("[dim]{task.fields[skipped]} skipped"),
        console=console,
    )


class DeletionProgress:
    def __init__(self, types_totals: dict[str, int], overall_total: int) -> None:
        self._progress = _make_progress()
        self._type_tasks: dict[str, object] = {}

        for t in TYPE_ORDER:
            total = types_totals.get(t, 0)
            if total > 0:
                self._type_tasks[t] = self._progress.add_task(
                    TYPE_LABELS.get(t, t),
                    total=total,
                    done=0,
                    failed=0,
                    skipped=0,
                )

        self._overall_task = self._progress.add_task(
            "[bold cyan]Overall ",
            total=overall_total,
            done=0,
            failed=0,
            skipped=0,
        )

        from rich.live import Live
        self._live = Live(self._progress, console=console, refresh_per_second=4)

    def __enter__(self) -> "DeletionProgress":
        self._live.start()
        return self

    def __exit__(self, *_) -> None:
        self._live.stop()

    def update(self, stats_by_type: dict[str, ItemStats], overall: ItemStats) -> None:
        for t, task_id in self._type_tasks.items():
            s = stats_by_type.get(t, ItemStats())
            self._progress.update(
                task_id,
                completed=s.done + s.failed + s.skipped,
                done=s.done,
                failed=s.failed,
                skipped=s.skipped,
            )
        self._progress.update(
            self._overall_task,
            completed=overall.done + overall.failed + overall.skipped,
            done=overall.done,
            failed=overall.failed,
            skipped=overall.skipped,
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
