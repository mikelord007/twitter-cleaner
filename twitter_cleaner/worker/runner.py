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
    llm_filter=None,
    llm_description: str = "",
) -> None:
    stats = db.stats(item_types)
    total = stats.pending + stats.failed
    label = "/".join(item_types) if item_types else "all"

    with DeletionProgress(label, total) as ui:
        consecutive_failures = 0

        while True:
            batch = db.get_pending(item_types, BATCH_SIZE)
            if not batch:
                break

            # Apply in-memory filters to batch
            if before_date or llm_filter:
                batch = _apply_filters(db, batch, before_date, llm_filter, llm_description)
            if not batch:
                # All items in this batch were filtered out — re-query for next batch
                # (the filtered items were marked skipped, so they won't re-appear)
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

                ui.update(db.stats(item_types))

                jitter = random.uniform(config.min_delay, config.max_delay)
                await asyncio.sleep(jitter)


def _apply_filters(db, batch, before_date, llm_filter, llm_description):
    from twitter_cleaner.filters.date_filter import before_date as check_before

    filtered = []
    for row in batch:
        if before_date and row["type"] != "like":
            tweet_date = row["tweet_date"] or ""
            if not check_before(tweet_date, before_date):
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
            else:
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
