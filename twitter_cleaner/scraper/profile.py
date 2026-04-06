from __future__ import annotations

import asyncio
import re
from typing import AsyncIterator

from playwright.async_api import Page

from twitter_cleaner.display.progress_ui import console

# Stops scrolling after this many consecutive scrolls with no new tweets found
_MAX_EMPTY_SCROLLS = 5
_SCROLL_PAUSE = 2.0  # seconds between scrolls

_STATUS_RE = re.compile(r"/status/(\d+)")


async def scrape_tweets(page: Page, username: str) -> AsyncIterator[tuple[str, str]]:
    """
    Scroll the user's tweets + replies timeline and yield (tweet_id, tweet_type) tuples.
    tweet_type is 'tweet', 'reply', or 'retweet' — best-effort from the UI.
    """
    # Tweets tab (own tweets + quotes)
    async for item in _scrape_tab(page, f"https://x.com/{username}", username, "tweet"):
        yield item

    # With-replies tab (catches replies)
    async for item in _scrape_tab(page, f"https://x.com/{username}/with_replies", username, "reply"):
        yield item


async def scrape_likes(page: Page, username: str) -> AsyncIterator[tuple[str, str]]:
    """Scroll the likes tab and yield (tweet_id, 'like') tuples."""
    async for item in _scrape_tab(page, f"https://x.com/{username}/likes", username, "like"):
        yield item


async def _scrape_tab(
    page: Page, url: str, username: str, default_type: str
) -> AsyncIterator[tuple[str, str]]:
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(2)

    seen: set[str] = set()
    empty_scrolls = 0

    while empty_scrolls < _MAX_EMPTY_SCROLLS:
        # Collect all status links currently in the DOM
        links = await page.locator("article[data-testid='tweet'] a[href*='/status/']").all()

        new_found = 0
        for link in links:
            href = await link.get_attribute("href") or ""
            match = _STATUS_RE.search(href)
            if not match:
                continue
            tweet_id = match.group(1)
            if tweet_id in seen:
                continue
            seen.add(tweet_id)
            new_found += 1

            # Determine type from context where possible
            tweet_type = _infer_type(href, username, default_type)
            yield tweet_id, tweet_type

        if new_found == 0:
            empty_scrolls += 1
        else:
            empty_scrolls = 0
            console.print(f"[dim]  found {len(seen)} so far...[/]")

        # Scroll down
        await page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
        await asyncio.sleep(_SCROLL_PAUSE)


def _infer_type(href: str, username: str, default_type: str) -> str:
    """
    Best-effort type inference from the URL.
    - If the href contains another user's handle before /status/, it's likely a retweet or reply.
    - Otherwise fall back to the tab's default type.
    """
    # e.g. /someoneelse/status/123 → not our tweet
    parts = href.strip("/").split("/")
    if len(parts) >= 3 and parts[0].lower() != username.lower() and parts[1] == "status":
        return default_type  # could be RT or reply; caller knows which tab we're on
    return default_type
