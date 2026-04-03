from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console

from twitter_cleaner.config import Config

console = Console()


# ---------------------------------------------------------------------------
# Shared CLI options
# ---------------------------------------------------------------------------

def _common_delete_options(f):
    f = click.option("--dry-run", is_flag=True, help="Navigate but don't actually delete.")(f)
    f = click.option("--headless/--no-headless", default=True, show_default=True)(f)
    f = click.option("--min-delay", default=3.0, type=float, show_default=True)(f)
    f = click.option("--max-delay", default=6.0, type=float, show_default=True)(f)
    f = click.option(
        "--before",
        "before_date",
        default=None,
        metavar="YYYY-MM-DD",
        help="Only delete posts published before this date.",
    )(f)
    f = click.option(
        "--filter",
        "llm_description",
        default=None,
        metavar="TEXT",
        help='Describe what to delete, e.g. "angry political tweets". Requires --llm-provider.',
    )(f)
    f = click.option(
        "--llm-provider",
        default=None,
        type=click.Choice(["openai", "anthropic"], case_sensitive=False),
        help="LLM provider to use for --filter.",
    )(f)
    f = click.option(
        "--llm-api-key",
        default=None,
        envvar=["OPENAI_API_KEY", "ANTHROPIC_API_KEY"],
        help="API key for the LLM provider (or set OPENAI_API_KEY / ANTHROPIC_API_KEY env var).",
    )(f)
    return f


def _build_config(
    headless: bool,
    dry_run: bool,
    min_delay: float,
    max_delay: float,
) -> Config:
    cfg = Config(
        headless=headless,
        dry_run=dry_run,
        min_delay=min_delay,
        max_delay=max_delay,
    )
    try:
        cfg.validate()
    except ValueError as e:
        raise click.ClickException(str(e))
    return cfg


def _parse_before_date(before_date: str | None) -> datetime | None:
    if before_date is None:
        return None
    try:
        return datetime.strptime(before_date, "%Y-%m-%d")
    except ValueError:
        raise click.ClickException(f"Invalid date format: {before_date!r}. Use YYYY-MM-DD.")


def _build_llm_filter(provider: str | None, api_key: str | None, description: str | None):
    if not description:
        return None
    if not provider:
        raise click.ClickException("--llm-provider is required when using --filter.")
    if not api_key:
        raise click.ClickException(
            f"--llm-api-key (or OPENAI_API_KEY / ANTHROPIC_API_KEY env var) is required when using --filter."
        )
    from twitter_cleaner.filters.llm_filter import build_llm_filter
    return build_llm_filter(provider, api_key)


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
def main():
    """Twitter/X history cleaner — delete tweets, retweets, replies, and likes."""


# ---------------------------------------------------------------------------
# parse
# ---------------------------------------------------------------------------

@main.command()
@click.option(
    "--archive-dir",
    default="data",
    show_default=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Directory containing your Twitter archive data files (tweets.js, like.js, etc.).",
)
def parse(archive_dir: Path):
    """Load your Twitter archive into the progress database."""
    from twitter_cleaner.archive.parser import parse_likes, parse_tweets
    from twitter_cleaner.store.progress_db import ProgressDB

    cfg = Config()
    cfg.ensure_state_dir()
    db = ProgressDB(cfg.db_file)

    tweet_rows = []
    for rec in parse_tweets(archive_dir):
        url = f"https://x.com/{cfg.username}/status/{rec.id}" if cfg.username else ""
        tweet_rows.append((rec.id, rec.tweet_type.value, url, rec.created_at, rec.text))

    like_rows = []
    for rec in parse_likes(archive_dir):
        url = f"https://x.com/i/web/status/{rec.id}"
        like_rows.append((rec.id, "like", url, None, rec.text))

    tweet_count = db.bulk_insert_pending(tweet_rows) if tweet_rows else 0
    like_count = db.bulk_insert_pending(like_rows) if like_rows else 0

    db.close()
    console.print(f"[green]Parsed {len(tweet_rows)} tweets/retweets/replies, {len(like_rows)} likes.[/]")
    console.print(f"[green]New records added to DB: {tweet_count + like_count}[/]")
    console.print("[dim]Run 'twitter-cleaner status' to see full counts.[/]")


# ---------------------------------------------------------------------------
# delete subgroup
# ---------------------------------------------------------------------------

@main.group()
def delete():
    """Delete tweets, likes, or everything."""


@delete.command("tweets")
@_common_delete_options
def delete_tweets(
    dry_run, headless, min_delay, max_delay, before_date, llm_description, llm_provider, llm_api_key
):
    """Delete all tweets (including replies, retweets, and quotes)."""
    cfg = _build_config(headless, dry_run, min_delay, max_delay)
    dt = _parse_before_date(before_date)
    llm = _build_llm_filter(llm_provider, llm_api_key, llm_description)
    asyncio.run(_run_delete(cfg, item_types=["tweet", "reply", "retweet", "quote"],
                            before_date=dt, llm_filter=llm, llm_description=llm_description or ""))


@delete.command("likes")
@_common_delete_options
def delete_likes(
    dry_run, headless, min_delay, max_delay, before_date, llm_description, llm_provider, llm_api_key
):
    """Unlike all liked tweets."""
    cfg = _build_config(headless, dry_run, min_delay, max_delay)
    dt = _parse_before_date(before_date)
    llm = _build_llm_filter(llm_provider, llm_api_key, llm_description)
    asyncio.run(_run_delete(cfg, item_types=["like"],
                            before_date=dt, llm_filter=llm, llm_description=llm_description or ""))


@delete.command("all")
@_common_delete_options
def delete_all(
    dry_run, headless, min_delay, max_delay, before_date, llm_description, llm_provider, llm_api_key
):
    """Delete all tweets and unlike all likes."""
    cfg = _build_config(headless, dry_run, min_delay, max_delay)
    dt = _parse_before_date(before_date)
    llm = _build_llm_filter(llm_provider, llm_api_key, llm_description)
    asyncio.run(_run_delete(cfg, item_types=None,
                            before_date=dt, llm_filter=llm, llm_description=llm_description or ""))


async def _run_delete(cfg, item_types, before_date, llm_filter, llm_description):
    from twitter_cleaner.browser.session import TwitterSession
    from twitter_cleaner.store.progress_db import ProgressDB
    from twitter_cleaner.worker.runner import run_deletion

    cfg.ensure_state_dir()
    db = ProgressDB(cfg.db_file)

    if cfg.dry_run:
        console.print("[yellow]DRY RUN — no items will actually be deleted.[/]")

    session = TwitterSession(cfg)
    try:
        page = await session.start()
        await run_deletion(
            page=page,
            db=db,
            config=cfg,
            item_types=item_types,
            before_date=before_date,
            llm_filter=llm_filter,
            llm_description=llm_description,
        )
    finally:
        await session.close()
        db.close()

    console.print("[bold green]Done![/]")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@main.command()
def status():
    """Show deletion progress counts by type."""
    from twitter_cleaner.display.progress_ui import print_stats_table
    from twitter_cleaner.store.progress_db import ProgressDB

    cfg = Config()
    db_path = cfg.db_file
    if not db_path.exists():
        console.print("[yellow]No progress database found. Run 'parse' first.[/]")
        return

    db = ProgressDB(db_path)
    stats = db.stats_by_type()
    db.close()

    if not stats:
        console.print("[yellow]No records in database.[/]")
        return

    print_stats_table(stats)


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------

@main.command()
@click.option(
    "--type",
    "item_type",
    default=None,
    type=click.Choice(["tweet", "reply", "retweet", "quote", "like"]),
    help="Only reset items of this type.",
)
@click.option(
    "--status",
    "from_status",
    default="failed",
    show_default=True,
    type=click.Choice(["failed", "skipped", "done"]),
    help="Reset items with this status back to pending.",
)
def reset(item_type: str | None, from_status: str):
    """Re-queue items for retry (default: re-queues failed items)."""
    from twitter_cleaner.store.progress_db import ProgressDB

    cfg = Config()
    db_path = cfg.db_file
    if not db_path.exists():
        console.print("[yellow]No progress database found. Run 'parse' first.[/]")
        return

    db = ProgressDB(db_path)
    count = db.reset_status(item_type, from_status)
    db.close()
    console.print(f"[green]Reset {count} items from '{from_status}' → 'pending'.[/]")
