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
    f = click.option("--headless/--no-headless", default=False, show_default=True)(f)
    f = click.option(
        "--stealth/--no-stealth",
        default=True,
        show_default=True,
        help="Stealth mode: periodic long pauses every 50 actions to avoid rate-limiting. "
             "Pass --no-stealth to skip these breaks.",
    )(f)
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
        "--after",
        "after_date",
        default=None,
        metavar="YYYY-MM-DD",
        help="Only delete posts published after this date.",
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
        type=click.Choice(["openai", "anthropic", "openrouter"], case_sensitive=False),
        help="LLM provider to use for --filter.",
    )(f)
    f = click.option(
        "--llm-model",
        default=None,
        metavar="MODEL",
        help="Model name to use (e.g. gpt-4o, claude-opus-4-6, mistralai/mistral-7b-instruct). "
             "Defaults to a cheap model for each provider.",
    )(f)
    f = click.option(
        "--llm-api-key",
        default=None,
        envvar=["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"],
        help="API key for the LLM provider (or set OPENAI_API_KEY / ANTHROPIC_API_KEY / OPENROUTER_API_KEY env var).",
    )(f)
    return f


def _build_config(
    headless: bool,
    dry_run: bool,
    min_delay: float,
    max_delay: float,
    stealth: bool = True,
) -> Config:
    cfg = Config(
        headless=headless,
        dry_run=dry_run,
        stealth=stealth,
        min_delay=min_delay,
        max_delay=max_delay,
    )
    try:
        cfg.validate()
    except ValueError as e:
        raise click.ClickException(str(e))
    return cfg


def _parse_date(value: str | None, flag: str) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise click.ClickException(f"Invalid date for {flag}: {value!r}. Use YYYY-MM-DD.")


def _parse_date_range(
    before: str | None, after: str | None
) -> tuple[datetime | None, datetime | None]:
    dt_before = _parse_date(before, "--before")
    dt_after = _parse_date(after, "--after")
    if dt_before and dt_after and dt_after >= dt_before:
        raise click.ClickException("--after must be earlier than --before.")
    return dt_before, dt_after


def _build_llm_filter(
    provider: str | None,
    api_key: str | None,
    description: str | None,
    model: str | None,
):
    if not description:
        return None
    if not provider:
        raise click.ClickException("--llm-provider is required when using --filter.")
    if not api_key:
        raise click.ClickException(
            "--llm-api-key (or OPENAI_API_KEY / ANTHROPIC_API_KEY / OPENROUTER_API_KEY env var) "
            "is required when using --filter."
        )
    from twitter_cleaner.filters.llm_filter import build_llm_filter
    return build_llm_filter(provider, api_key, model)


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
def main():
    """Twitter/X history cleaner — delete tweets, retweets, replies, and likes."""


# ---------------------------------------------------------------------------
# parse (archive-based)
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
    import sqlite3

    from twitter_cleaner.archive.parser import parse_likes, parse_tweets
    from twitter_cleaner.store.progress_db import ProgressDB

    # Check for archive files before doing anything else.
    tweet_files = list(archive_dir.glob("tweets*.js"))
    like_files = list(archive_dir.glob("like*.js"))
    if not tweet_files and not like_files:
        raise click.ClickException(
            f"No archive files found in '{archive_dir}'.\n"
            "Expected tweets.js (or tweets-part1.js, …) and/or like.js.\n"
            "Make sure you extracted your Twitter archive and are pointing at the 'data' folder."
        )

    cfg = Config()
    cfg.ensure_state_dir()
    try:
        db = ProgressDB(cfg.db_file)
    except sqlite3.OperationalError as e:
        raise click.ClickException(f"Cannot open progress database: {e}")

    tweet_rows = []
    for rec in parse_tweets(archive_dir):
        url = f"https://x.com/{cfg.username}/status/{rec.id}" if cfg.username else ""
        tweet_rows.append((rec.id, rec.tweet_type.value, url, rec.created_at, rec.text))

    from twitter_cleaner.filters.date_filter import tweet_id_to_created_at
    like_rows = []
    likes_no_date = 0
    for rec in parse_likes(archive_dir):
        url = f"https://x.com/i/web/status/{rec.id}"
        derived = tweet_id_to_created_at(rec.id)
        if derived is None:
            likes_no_date += 1
        like_rows.append((rec.id, "like", url, derived, rec.text))

    tweet_new, tweet_backfilled = db.bulk_insert_pending(tweet_rows) if tweet_rows else (0, 0)
    like_new, like_backfilled = db.bulk_insert_pending(like_rows) if like_rows else (0, 0)

    null_in_db = db._conn.execute("SELECT COUNT(*) FROM items WHERE tweet_date IS NULL").fetchone()[0]
    sample_like = db._conn.execute("SELECT id, tweet_date FROM items WHERE type='like' LIMIT 1").fetchone()

    db.close()
    console.print(f"[green]Parsed {len(tweet_rows)} tweets/retweets/replies, {len(like_rows)} likes.[/]")
    console.print(f"[green]New records added: {tweet_new + like_new}[/]")
    console.print(f"[dim]Backfilled: {tweet_backfilled + like_backfilled}  |  Likes with no derivable date: {likes_no_date}  |  Still NULL in DB: {null_in_db}[/]")
    if sample_like:
        console.print(f"[dim]Sample like — id: {sample_like['id']}  tweet_date: {sample_like['tweet_date']!r}[/]")
    console.print("[dim]Run 'twitter-cleaner status' to see full counts.[/]")


# ---------------------------------------------------------------------------
# scrape (live profile — alternative to parse)
# ---------------------------------------------------------------------------

@main.command()
@click.option(
    "--tweets/--no-tweets", default=True, show_default=True,
    help="Scrape the tweets + replies tabs.",
)
@click.option(
    "--likes/--no-likes", default=True, show_default=True,
    help="Scrape the likes tab.",
)
@click.option("--headless/--no-headless", default=False, show_default=True)
def scrape(tweets: bool, likes: bool, headless: bool):
    """
    Scrape your live Twitter profile instead of using a downloaded archive.

    Scrolls your tweets and/or likes tabs and loads found IDs into the
    progress database. Limited to roughly your last 3200 tweets by Twitter.
    Use 'parse' with a downloaded archive to get your full history.
    """
    asyncio.run(_run_scrape(tweets, likes, headless))


async def _run_scrape(do_tweets: bool, do_likes: bool, headless: bool) -> None:
    from twitter_cleaner.browser.session import TwitterSession
    from twitter_cleaner.errors import handle_errors
    from twitter_cleaner.scraper.profile import scrape_likes, scrape_tweets
    from twitter_cleaner.store.progress_db import ProgressDB

    cfg = Config()
    try:
        cfg.validate()
    except ValueError as e:
        raise click.ClickException(str(e))

    cfg.headless = headless
    cfg.ensure_state_dir()

    async with handle_errors():
        db = ProgressDB(cfg.db_file)
        session = TwitterSession(cfg)
        try:
            page = await session.start()

            from twitter_cleaner.filters.date_filter import tweet_id_to_created_at

            if do_tweets:
                console.print(f"[bold]Scraping tweets/replies for @{cfg.username}...[/]")
                rows = []
                async for tweet_id, tweet_type in scrape_tweets(page, cfg.username):
                    url = f"https://x.com/{cfg.username}/status/{tweet_id}"
                    rows.append((tweet_id, tweet_type, url, tweet_id_to_created_at(tweet_id), None))
                new, _ = db.bulk_insert_pending(rows)
                console.print(f"[green]Tweets: found {len(rows)}, {new} new added to DB.[/]")

            if do_likes:
                console.print(f"[bold]Scraping likes for @{cfg.username}...[/]")
                rows = []
                async for tweet_id, _ in scrape_likes(page, cfg.username):
                    url = f"https://x.com/i/web/status/{tweet_id}"
                    rows.append((tweet_id, "like", url, tweet_id_to_created_at(tweet_id), None))
                new, _ = db.bulk_insert_pending(rows)
                console.print(f"[green]Likes: found {len(rows)}, {new} new added to DB.[/]")

        finally:
            await session.close()
            db.close()

    console.print("[dim]Run 'twitter-cleaner status' to see full counts.[/]")


# ---------------------------------------------------------------------------
# delete command
# ---------------------------------------------------------------------------

@main.command("delete")
@click.option(
    "--type", "types",
    multiple=True,
    type=click.Choice(["tweet", "reply", "quote", "retweet", "like"], case_sensitive=False),
    help="Types to delete. Repeatable. Defaults to all five if omitted.",
)
@_common_delete_options
def delete(
    types, dry_run, headless, stealth, min_delay, max_delay, before_date, after_date,
    llm_description, llm_provider, llm_model, llm_api_key,
):
    """Delete your Twitter history. Use --type to target specific kinds."""
    cfg = _build_config(headless, dry_run, min_delay, max_delay, stealth=stealth)
    dt_before, dt_after = _parse_date_range(before_date, after_date)
    llm = _build_llm_filter(llm_provider, llm_api_key, llm_description, llm_model)
    item_types = list(types) if types else None
    asyncio.run(_run_delete(cfg, item_types=item_types,
                            before_date=dt_before, after_date=dt_after,
                            llm_filter=llm, llm_description=llm_description or ""))


async def _run_delete(cfg, item_types, before_date, after_date, llm_filter, llm_description):
    from twitter_cleaner.browser.session import TwitterSession
    from twitter_cleaner.errors import handle_errors
    from twitter_cleaner.store.progress_db import ProgressDB
    from twitter_cleaner.worker.runner import run_deletion

    cfg.ensure_state_dir()

    async with handle_errors():
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
                after_date=after_date,
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
    import sqlite3

    from twitter_cleaner.display.progress_ui import print_stats_table
    from twitter_cleaner.store.progress_db import ProgressDB

    cfg = Config()
    db_path = cfg.db_file
    if not db_path.exists():
        console.print(
            "[yellow]No progress database found.[/]\n"
            "Run 'twitter-cleaner parse' first to load your archive."
        )
        return

    try:
        db = ProgressDB(db_path)
        stats = db.stats_by_type()
        db.close()
    except sqlite3.DatabaseError as e:
        raise click.ClickException(
            f"Could not read progress database: {e}\n"
            "Fix: delete .twitter_cleaner/progress.db and run 'twitter-cleaner parse' again."
        )

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
    import sqlite3

    from twitter_cleaner.store.progress_db import ProgressDB

    cfg = Config()
    db_path = cfg.db_file
    if not db_path.exists():
        console.print(
            "[yellow]No progress database found.[/]\n"
            "Run 'twitter-cleaner parse' first to load your archive."
        )
        return

    try:
        db = ProgressDB(db_path)
        count = db.reset_status(item_type, from_status)
        db.close()
    except sqlite3.OperationalError as e:
        raise click.ClickException(
            f"Database error: {e}\n"
            "If the database is locked, close any other running twitter-cleaner instances."
        )
    console.print(f"[green]Reset {count} items from '{from_status}' → 'pending'.[/]")
