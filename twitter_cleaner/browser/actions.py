from __future__ import annotations

import asyncio
from typing import Literal

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

ActionResult = Literal["done", "skipped", "failed"]

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


async def delete_tweet(
    page: Page, tweet_id: str, username: str, dry_run: bool = False
) -> ActionResult:
    url = f"https://x.com/{username}/status/{tweet_id}"
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=20000)
    except PlaywrightTimeout:
        return "failed"

    if resp and resp.status == 404:
        return "skipped"

    await asyncio.sleep(1.5)

    if await _is_unavailable(page):
        return "skipped"

    if dry_run:
        return "done"

    try:
        # Open the caret / "more" menu on the tweet
        caret = page.locator('[data-testid="caret"]').first
        await caret.wait_for(state="visible", timeout=TIMEOUT)
        await caret.click()
        await asyncio.sleep(0.5)

        # Click "Delete" menu item
        delete_item = page.get_by_role("menuitem", name="Delete")
        await delete_item.wait_for(state="visible", timeout=TIMEOUT)
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

    if resp and resp.status == 404:
        return "skipped"

    await asyncio.sleep(1.5)

    if await _is_unavailable(page):
        return "skipped"

    if dry_run:
        return "done"

    try:
        caret = page.locator('[data-testid="caret"]').first
        await caret.wait_for(state="visible", timeout=TIMEOUT)
        await caret.click()
        await asyncio.sleep(0.5)

        undo_item = page.get_by_role("menuitem", name="Undo repost")
        if await undo_item.count() == 0:
            undo_item = page.get_by_role("menuitem", name="Undo retweet")
        await undo_item.wait_for(state="visible", timeout=TIMEOUT)
        await undo_item.click()
        await asyncio.sleep(1)

        return "done"

    except PlaywrightTimeout:
        return "failed"
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

    if resp and resp.status == 404:
        return "skipped"

    await asyncio.sleep(1.5)

    if await _is_unavailable(page):
        return "skipped"

    if dry_run:
        return "done"

    try:
        unlike_btn = page.locator('[data-testid="unlike"]').first
        if await unlike_btn.count() == 0:
            # Tweet is not liked (or already unliked)
            return "skipped"

        await unlike_btn.wait_for(state="visible", timeout=TIMEOUT)
        await unlike_btn.click()
        await asyncio.sleep(1)

        return "done"

    except PlaywrightTimeout:
        return "failed"
    except Exception:
        return "failed"
