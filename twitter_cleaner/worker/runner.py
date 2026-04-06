from __future__ import annotations

import asyncio
import random
from datetime import datetime
from typing import TYPE_CHECKING

from twitter_cleaner.browser import actions
from twitter_cleaner.config import Config
from twitter_cleaner.display.progress_ui import DeletionProgress, console
from twitter_cleaner.store.progress_db import ProgressDB

if TYPE_CHECKING:
    from playwright.async_api import Page


BATCH_SIZE = 50
LONG_BREAK_EVERY = 50   # actions between long pauses
LONG_BREAK_MIN   = 180  # seconds
LONG_BREAK_MAX   = 360  # seconds


async def run_deletion(
    page: "Page",
    db: ProgressDB,
    config: Config,
    item_types: list[str] | None = None,
    before_date: datetime | None = None,
    after_date: datetime | None = None,
    llm_filter=None,
    llm_description: str = "",
) -> None:
    from twitter_cleaner.store.progress_db import ItemStats

    initial_by_type = db.stats_by_type()
    if item_types:
        initial_by_type = {t: s for t, s in initial_by_type.items() if t in item_types}

    if before_date or after_date:
        types_totals = _count_filtered_totals(db, item_types, before_date, after_date)
    else:
        types_totals = {t: s.pending + s.failed for t, s in initial_by_type.items()}
    overall_total = sum(types_totals.values())

    dry_run = config.dry_run

    with DeletionProgress(types_totals, overall_total) as ui:
        if dry_run:
            await _run_dry(
                page, db, config, ui,
                item_types, before_date, after_date, llm_filter, llm_description,
                initial_by_type, overall_total,
            )
        else:
            await _run_live(
                page, db, config, ui,
                item_types, before_date, after_date, llm_filter, llm_description,
            )


async def _run_dry(page, db, config, ui, item_types, before_date, after_date,
                   llm_filter, llm_description, initial_by_type, overall_total):
    from twitter_cleaner.store.progress_db import ItemStats

    # Fetch ALL pending items upfront — batching doesn't work in dry-run because
    # nothing is written to DB, so get_pending would return the same items repeatedly.
    all_items = db.get_pending(item_types, limit=999_999)
    if before_date or after_date or llm_filter:
        all_items = _apply_filters(db, all_items, before_date, after_date,
                                   llm_filter, llm_description, dry_run=True)

    dry_run_by_type: dict[str, ItemStats] = {
        t: ItemStats(pending=s.pending + s.failed) for t, s in initial_by_type.items()
    }
    dry_run_overall = ItemStats(pending=overall_total)

    for row in all_items:
        tweet_id = row["id"]
        row_type = row["type"]
        result = await _process_one(page, tweet_id, row_type, config)

        s = dry_run_by_type.setdefault(row_type, ItemStats())
        if result == "skipped":
            s.skipped += 1
            dry_run_overall.skipped += 1
        else:
            s.done += 1
            dry_run_overall.done += 1
        ui.update(dry_run_by_type, dry_run_overall)

        jitter = random.uniform(config.min_delay, config.max_delay)
        await asyncio.sleep(jitter)


async def _run_live(page, db, config, ui, item_types, before_date, after_date,
                    llm_filter, llm_description):
    from twitter_cleaner.store.progress_db import ItemStats

    consecutive_failures = 0
    action_count = 0

    # When filters are active the DB stats include items outside the range
    # (they get marked skipped), which would make the bar overshoot the
    # filtered total shown at startup. Track counts locally instead.
    use_local_stats = bool(before_date or after_date or llm_filter)
    local_by_type: dict[str, ItemStats] = {}
    local_overall = ItemStats()

    # When a date filter is active, items outside the range stay pending in the DB.
    # Normal batch pagination would keep re-fetching the same non-matching items
    # forever (or break early and miss items that DO match later in the sort order).
    # Pre-fetching everything and filtering in memory avoids both problems.
    if before_date or after_date or llm_filter:
        all_pending = db.get_pending(item_types, limit=999_999)
        work_list = _apply_filters(db, all_pending, before_date, after_date, llm_filter, llm_description)
    else:
        work_list = None  # use normal batching below

    def _next_batch(idx: int):
        if work_list is not None:
            chunk = work_list[idx: idx + BATCH_SIZE]
            return chunk, idx + len(chunk)
        batch = db.get_pending(item_types, BATCH_SIZE)
        return batch, 0  # idx unused for normal batching

    idx = 0
    while True:
        batch, idx = _next_batch(idx)
        if not batch:
            break

        for row in batch:
            tweet_id = row["id"]
            row_type = row["type"]

            result = await _process_one(page, tweet_id, row_type, config)

            if result == "blocked":
                console.print(
                    "\n[bold red]Twitter has ended your session.[/]\n"
                    "[yellow]This usually means Twitter detected automation or rate-limited your IP.[/]\n"
                    "Progress is saved. Try the following:\n"
                    "  1. Wait 15–30 minutes before retrying.\n"
                    "  2. Increase delays:  --min-delay 8 --max-delay 15\n"
                    "  3. If using --no-stealth, remove it to re-enable long pauses.\n"
                    "  4. Log in again manually when you rerun the command.\n"
                )
                return
            elif result == "done":
                db.mark_done(tweet_id, row_type)
                consecutive_failures = 0
                action_count += 1
            elif result == "skipped":
                db.mark_skipped(tweet_id, row_type)
                consecutive_failures = 0
            else:
                db.mark_failed(tweet_id, row_type, "action returned failed")
                consecutive_failures += 1
                if consecutive_failures >= 5:
                    backoff = min(60 * (2 ** (consecutive_failures - 5)), 600)
                    console.print(
                        f"[yellow]{consecutive_failures} failures in a row — "
                        f"Twitter may be slowing down responses. "
                        f"Backing off for {backoff}s...[/]"
                    )
                    await asyncio.sleep(backoff)

            if use_local_stats:
                s = local_by_type.setdefault(row_type, ItemStats())
                if result == "done":
                    s.done += 1
                    local_overall.done += 1
                elif result == "skipped":
                    s.skipped += 1
                    local_overall.skipped += 1
                elif result == "failed":
                    s.failed += 1
                    local_overall.failed += 1
                ui.update(local_by_type, local_overall)
            else:
                live_by_type = db.stats_by_type()
                if item_types:
                    live_by_type = {t: s for t, s in live_by_type.items() if t in item_types}
                ui.update(live_by_type, db.stats(item_types))

            # Periodic long break to avoid rate-limit detection.
            if config.stealth and action_count > 0 and action_count % LONG_BREAK_EVERY == 0:
                pause = random.uniform(LONG_BREAK_MIN, LONG_BREAK_MAX)
                console.print(
                    f"[cyan]Pausing for {pause:.0f}s after {action_count} actions "
                    f"to avoid rate-limiting...[/]"
                )
                await asyncio.sleep(pause)
            else:
                jitter = random.uniform(config.min_delay, config.max_delay)
                await asyncio.sleep(jitter)


def _count_filtered_totals(
    db,
    item_types: list[str] | None,
    before_date,
    after_date,
) -> dict[str, int]:
    """Pre-scan pending items and count only those that pass the date filter."""
    from twitter_cleaner.filters.date_filter import in_date_range

    counts: dict[str, int] = {}
    for row in db.pending_dates(item_types):
        tweet_date = row["tweet_date"] or ""
        if in_date_range(tweet_date, before=before_date, after=after_date):
            counts[row["type"]] = counts.get(row["type"], 0) + 1
    return counts


def _apply_filters(db, batch, before_date, after_date, llm_filter, llm_description, dry_run=False):
    from twitter_cleaner.filters.date_filter import in_date_range

    filtered = []
    for row in batch:
        if before_date or after_date:
            tweet_date = row["tweet_date"] or ""
            if not in_date_range(tweet_date, before=before_date, after=after_date):
                # Date filter is session-scoped — leave the item pending in the DB
                # so it can be picked up by a future run without a date restriction.
                continue
        filtered.append(row)

    if llm_filter and filtered:
        tweet_texts = [row["tweet_text"] or "" for row in filtered]
        matches = llm_filter.classify_batch(tweet_texts, llm_description)
        result = []
        for row, match in zip(filtered, matches):
            if match:
                result.append(row)
            elif not dry_run:
                db.mark_skipped(row["id"], row["type"])
        return result

    return filtered


async def _process_one(page: "Page", tweet_id: str, row_type: str, config: Config) -> str:
    username = config.username
    dry_run = config.dry_run

    if row_type == "like":
        return await actions.unlike_tweet(page, tweet_id, dry_run=dry_run)
    elif row_type == "retweet":
        return await actions.undo_retweet(page, tweet_id, username, dry_run=dry_run)
    else:
        # tweet, reply, quote
        return await actions.delete_tweet(page, tweet_id, username, dry_run=dry_run)
