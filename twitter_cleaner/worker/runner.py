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
    consecutive_failures = 0

    while True:
        batch = db.get_pending(item_types, BATCH_SIZE)
        if not batch:
            break

        # Apply in-memory filters to batch
        if before_date or after_date or llm_filter:
            batch = _apply_filters(db, batch, before_date, after_date, llm_filter, llm_description)
        if not batch:
            # All items in this batch were filtered out (marked skipped) — re-query
            continue

        for row in batch:
            tweet_id = row["id"]
            row_type = row["type"]

            result = await _process_one(page, tweet_id, row_type, config)

            if result == "done":
                db.mark_done(tweet_id, row_type)
                consecutive_failures = 0
            elif result == "skipped":
                db.mark_skipped(tweet_id, row_type)
                consecutive_failures = 0
            else:
                db.mark_failed(tweet_id, row_type, "action returned failed")
                consecutive_failures += 1
                if consecutive_failures >= 5:
                    backoff = min(60 * (2 ** (consecutive_failures - 5)), 600)
                    console.print(
                        f"[yellow]Too many failures — backing off for {backoff}s[/]"
                    )
                    await asyncio.sleep(backoff)

            live_by_type = db.stats_by_type()
            if item_types:
                live_by_type = {t: s for t, s in live_by_type.items() if t in item_types}
            ui.update(live_by_type, db.stats(item_types))

            jitter = random.uniform(config.min_delay, config.max_delay)
            await asyncio.sleep(jitter)


def _apply_filters(db, batch, before_date, after_date, llm_filter, llm_description, dry_run=False):
    from twitter_cleaner.filters.date_filter import in_date_range

    filtered = []
    for row in batch:
        if before_date or after_date:
            tweet_date = row["tweet_date"] or ""
            if not in_date_range(tweet_date, before=before_date, after=after_date):
                if not dry_run:
                    db.mark_skipped(row["id"], row["type"])
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
