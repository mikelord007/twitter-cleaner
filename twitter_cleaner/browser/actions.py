from __future__ import annotations

import asyncio
import random
from typing import Literal

from playwright.async_api import Locator, Page, TimeoutError as PlaywrightTimeout

ActionResult = Literal["done", "skipped", "failed", "blocked"]


def _is_login_page(url: str) -> bool:
    return "login" in url or "i/flow/login" in url or "i/flow/signup" in url

_UNAVAILABLE_TEXTS = [
    "This Tweet is unavailable",
    "This post is unavailable",
    "Something went wrong",
    "Hmm, this page doesn't exist",
]

TIMEOUT = 10_000  # ms


async def _is_unavailable(page: Page) -> bool:
    for text in _UNAVAILABLE_TEXTS:
        if await page.get_by_text(text).count() > 0:
            return True
    return False


async def _highlight(locator: Locator) -> None:
    """Outline the element in black to show what would be clicked in dry-run."""
    await locator.evaluate(
        "el => el.style.cssText += '; outline: 3px solid black !important; outline-offset: 2px !important;'"
    )
    await asyncio.sleep(1.5)


async def delete_tweet(
    page: Page, tweet_id: str, username: str, dry_run: bool = False
) -> ActionResult:
    url = f"https://x.com/{username}/status/{tweet_id}"
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=20000)
    except PlaywrightTimeout:
        return "failed"

    if _is_login_page(page.url):
        return "blocked"

    if resp and resp.status == 404:
        return "skipped"

    await asyncio.sleep(1.5)

    if await _is_unavailable(page):
        return "skipped"

    try:
        # Scope to the article for this specific tweet so we don't hit
        # a parent tweet's caret when viewing a reply/quote in a thread.
        tweet_article = page.locator(
            f'article[data-testid="tweet"]:has(a[href*="/status/{tweet_id}"])'
        ).last
        await tweet_article.wait_for(state="visible", timeout=TIMEOUT)

        caret = tweet_article.locator('[data-testid="caret"]')
        await caret.wait_for(state="visible", timeout=TIMEOUT)
        await caret.click()
        await asyncio.sleep(0.5)

        # Find "Delete" menu item
        delete_item = page.get_by_role("menuitem", name="Delete")
        await delete_item.wait_for(state="visible", timeout=TIMEOUT)

        if dry_run:
            await _highlight(delete_item)
            return "done"

        await delete_item.hover()
        await asyncio.sleep(random.uniform(0.2, 0.5))
        await delete_item.click()
        await asyncio.sleep(0.5)

        # Confirm deletion
        confirm_btn = page.locator('[data-testid="confirmationSheetConfirm"]')
        await confirm_btn.wait_for(state="visible", timeout=TIMEOUT)
        await confirm_btn.click()
        await asyncio.sleep(1)

        return "done"

    except PlaywrightTimeout:
        return "failed"
    except Exception:
        return "failed"


async def undo_retweet(
    page: Page, tweet_id: str, username: str, dry_run: bool = False
) -> ActionResult:
    url = f"https://x.com/{username}/status/{tweet_id}"
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=20000)
    except PlaywrightTimeout:
        return "failed"

    if _is_login_page(page.url):
        return "blocked"

    if resp and resp.status == 404:
        return "skipped"

    await asyncio.sleep(1.5)

    if await _is_unavailable(page):
        return "skipped"

    try:
        # Wait for either button to appear — whichever shows up first tells us the state.
        await page.locator('[data-testid="unretweet"], [data-testid="retweet"]').first.wait_for(
            state="visible", timeout=TIMEOUT
        )
        # If only the hollow "retweet" button is present, it's already unretweeted.
        if await page.locator('[data-testid="unretweet"]').count() == 0:
            return "skipped"

        retweet_btn = page.locator('[data-testid="unretweet"]').first
        await retweet_btn.click()
        await asyncio.sleep(0.5)

        # "Undo Repost" menu item appears after clicking the retweet button
        undo_item = page.get_by_role("menuitem", name="Undo Repost")
        if await undo_item.count() == 0:
            undo_item = page.get_by_role("menuitem", name="Undo repost")
        if await undo_item.count() == 0:
            undo_item = page.get_by_role("menuitem", name="Undo retweet")
        await undo_item.wait_for(state="visible", timeout=TIMEOUT)

        if dry_run:
            await _highlight(undo_item)
            return "done"

        await undo_item.hover()
        await asyncio.sleep(random.uniform(0.2, 0.5))
        await undo_item.click()
        await asyncio.sleep(1)

        return "done"

    except PlaywrightTimeout:
        return "skipped"
    except Exception:
        return "failed"


async def unlike_tweet(
    page: Page, tweet_id: str, dry_run: bool = False
) -> ActionResult:
    url = f"https://x.com/i/web/status/{tweet_id}"
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=20000)
    except PlaywrightTimeout:
        return "failed"

    if _is_login_page(page.url):
        return "blocked"

    if resp and resp.status == 404:
        return "skipped"

    await asyncio.sleep(1.5)

    if await _is_unavailable(page):
        return "skipped"

    try:
        # Wait for either the like or unlike button to appear (page may still be loading)
        heart = page.locator('[data-testid="like"], [data-testid="unlike"]').first
        await heart.wait_for(state="visible", timeout=TIMEOUT)

        unlike_btn = page.locator('[data-testid="unlike"]').first
        if await unlike_btn.count() == 0:
            # Tweet is not liked (or already unliked)
            return "skipped"

        if dry_run:
            await _highlight(unlike_btn)
            return "done"

        await unlike_btn.hover()
        await asyncio.sleep(random.uniform(0.2, 0.5))
        await unlike_btn.click()
        await asyncio.sleep(1)

        return "done"

    except PlaywrightTimeout:
        return "failed"
    except Exception:
        return "failed"
