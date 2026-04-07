from __future__ import annotations

import json
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from twitter_cleaner.store.progress_db import ProgressDB


# ---------------------------------------------------------------------------
# Speed: kill all intentional sleeps and random delays in production code
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def instant(*_):
        pass

    monkeypatch.setattr("twitter_cleaner.browser.actions.asyncio.sleep", instant)
    monkeypatch.setattr("twitter_cleaner.worker.runner.asyncio.sleep", instant)
    monkeypatch.setattr("twitter_cleaner.scraper.profile.asyncio.sleep", instant)
    monkeypatch.setattr("random.uniform", lambda a, b: 0.0)


# ---------------------------------------------------------------------------
# SQLite progress DB (in-memory via tmp_path)
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path) -> ProgressDB:
    d = ProgressDB(tmp_path / "test.db")
    yield d
    d.close()


# ---------------------------------------------------------------------------
# Archive directory with minimal JS fixture files
# ---------------------------------------------------------------------------

def _js(varname: str, data: list) -> str:
    return f"window.YTD.{varname}.part0 = {json.dumps(data)}"


@pytest.fixture
def archive_dir(tmp_path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture
def tweet_archive(archive_dir) -> Path:
    """Archive dir pre-populated with two tweets (one plain, one retweet)."""
    tweets = [
        {"tweet": {"id": "1", "full_text": "hello world", "created_at": "Mon Jan 01 00:00:00 +0000 2022", "entities": {"urls": []}}},
        {"tweet": {"id": "2", "full_text": "RT @other: hi", "created_at": "Tue Jan 02 00:00:00 +0000 2022", "entities": {"urls": []}}},
    ]
    (archive_dir / "tweets.js").write_text(_js("tweets", tweets), encoding="utf-8")
    return archive_dir


@pytest.fixture
def like_archive(archive_dir) -> Path:
    """Archive dir pre-populated with one like."""
    likes = [{"like": {"tweetId": "999", "fullText": "liked tweet text"}}]
    (archive_dir / "like.js").write_text(_js("like", likes), encoding="utf-8")
    return archive_dir


# ---------------------------------------------------------------------------
# Async Playwright browser / page  (headless Chromium)
# Function-scoped: each test gets its own Playwright + browser + page so
# there are no event-loop ownership conflicts between fixtures and tests.
# ---------------------------------------------------------------------------

@pytest.fixture
async def page():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context()
        pg = await ctx.new_page()
        yield pg
        await ctx.close()
        await browser.close()
