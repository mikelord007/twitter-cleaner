from __future__ import annotations

"""
Tests for scraper/profile.py.

The scroll-based scraper tests use a real Chromium page (headless).
We serve static HTML with tweet article elements and patch _MAX_EMPTY_SCROLLS
to 1 so the loop exits quickly without real network scrolling.
"""

import pytest

from twitter_cleaner.scraper.profile import _infer_type, scrape_likes, scrape_tweets
import twitter_cleaner.scraper.profile as scraper_mod


# ---------------------------------------------------------------------------
# _infer_type  (pure function — no page needed)
# ---------------------------------------------------------------------------

class TestInferType:
    def test_own_tweet(self):
        assert _infer_type("/alice/status/123", "alice", "tweet") == "tweet"

    def test_other_user_still_returns_default(self):
        # _infer_type always returns default_type; the distinction is in the caller
        assert _infer_type("/bob/status/123", "alice", "tweet") == "tweet"

    def test_reply_default(self):
        assert _infer_type("/alice/status/99", "alice", "reply") == "reply"

    def test_like_default(self):
        assert _infer_type("/anyone/status/55", "alice", "like") == "like"

    def test_short_href(self):
        # href with fewer than 3 parts should not crash
        assert _infer_type("/status/123", "alice", "tweet") == "tweet"

    def test_empty_href(self):
        assert _infer_type("", "alice", "tweet") == "tweet"

    def test_case_insensitive_username(self):
        # Alice vs ALICE
        assert _infer_type("/ALICE/status/1", "alice", "tweet") == "tweet"


# ---------------------------------------------------------------------------
# Scraper integration tests  (Playwright)
# ---------------------------------------------------------------------------

def _tweet_list_html(username: str, tweet_ids: list[str]) -> str:
    """HTML page with a list of tweet articles."""
    articles = "\n".join(
        f'<article data-testid="tweet">'
        f'  <a href="/{username}/status/{tid}">tweet {tid}</a>'
        f'</article>'
        for tid in tweet_ids
    )
    return f"<!DOCTYPE html><html><body>{articles}</body></html>"


def _likes_list_html(tweet_ids: list[str]) -> str:
    """HTML page with like articles from other users."""
    articles = "\n".join(
        f'<article data-testid="tweet">'
        f'  <a href="/other/status/{tid}">tweet {tid}</a>'
        f'</article>'
        for tid in tweet_ids
    )
    return f"<!DOCTYPE html><html><body>{articles}</body></html>"


async def _route_html(page, url_pattern: str, html: str) -> None:
    async def handler(route):
        await route.fulfill(status=200, content_type="text/html", body=html)
    await page.route(url_pattern, handler)


class TestScrapeTweets:
    USERNAME = "alice"

    async def test_yields_tweet_ids(self, page, monkeypatch):
        monkeypatch.setattr(scraper_mod, "_MAX_EMPTY_SCROLLS", 1)
        html = _tweet_list_html(self.USERNAME, ["1", "2", "3"])
        await _route_html(page, f"**/{self.USERNAME}", html)
        await _route_html(page, f"**/{self.USERNAME}/with_replies", "<html><body></body></html>")

        results = []
        async for item in scrape_tweets(page, self.USERNAME):
            results.append(item)

        ids = [r[0] for r in results]
        assert "1" in ids
        assert "2" in ids
        assert "3" in ids

    async def test_deduplicates_ids_within_same_tab(self, page, monkeypatch):
        monkeypatch.setattr(scraper_mod, "_MAX_EMPTY_SCROLLS", 1)
        # Two articles with the same ID in the same tab — seen set deduplicates within a tab
        html = f"""<!DOCTYPE html><html><body>
<article data-testid="tweet"><a href="/{self.USERNAME}/status/42">t</a></article>
<article data-testid="tweet"><a href="/{self.USERNAME}/status/42">t</a></article>
</body></html>"""
        await _route_html(page, f"**/{self.USERNAME}", html)
        await _route_html(page, f"**/{self.USERNAME}/with_replies", "<html><body></body></html>")

        results = []
        async for item in scrape_tweets(page, self.USERNAME):
            results.append(item)

        ids = [r[0] for r in results]
        assert ids.count("42") == 1

    async def test_empty_page_yields_nothing(self, page, monkeypatch):
        monkeypatch.setattr(scraper_mod, "_MAX_EMPTY_SCROLLS", 1)
        empty = "<html><body></body></html>"
        await _route_html(page, f"**/{self.USERNAME}", empty)
        await _route_html(page, f"**/{self.USERNAME}/with_replies", empty)

        results = []
        async for item in scrape_tweets(page, self.USERNAME):
            results.append(item)

        assert results == []

    async def test_yields_tuple_of_id_and_type(self, page, monkeypatch):
        monkeypatch.setattr(scraper_mod, "_MAX_EMPTY_SCROLLS", 1)
        html = _tweet_list_html(self.USERNAME, ["99"])
        await _route_html(page, f"**/{self.USERNAME}", html)
        await _route_html(page, f"**/{self.USERNAME}/with_replies", "<html><body></body></html>")

        results = []
        async for item in scrape_tweets(page, self.USERNAME):
            results.append(item)

        assert len(results) > 0
        tweet_id, tweet_type = results[0]
        assert isinstance(tweet_id, str)
        assert isinstance(tweet_type, str)


class TestScrapeLikes:
    USERNAME = "alice"

    async def test_yields_like_ids(self, page, monkeypatch):
        monkeypatch.setattr(scraper_mod, "_MAX_EMPTY_SCROLLS", 1)
        html = _likes_list_html(["10", "20", "30"])
        await _route_html(page, f"**/{self.USERNAME}/likes", html)

        results = []
        async for item in scrape_likes(page, self.USERNAME):
            results.append(item)

        ids = [r[0] for r in results]
        assert "10" in ids
        assert "20" in ids

    async def test_yields_like_as_type(self, page, monkeypatch):
        monkeypatch.setattr(scraper_mod, "_MAX_EMPTY_SCROLLS", 1)
        html = _likes_list_html(["55"])
        await _route_html(page, f"**/{self.USERNAME}/likes", html)

        results = []
        async for item in scrape_likes(page, self.USERNAME):
            results.append(item)

        assert len(results) > 0
        _, tweet_type = results[0]
        assert tweet_type == "like"

    async def test_empty_likes_page(self, page, monkeypatch):
        monkeypatch.setattr(scraper_mod, "_MAX_EMPTY_SCROLLS", 1)
        await _route_html(page, f"**/{self.USERNAME}/likes", "<html><body></body></html>")

        results = []
        async for item in scrape_likes(page, self.USERNAME):
            results.append(item)

        assert results == []
