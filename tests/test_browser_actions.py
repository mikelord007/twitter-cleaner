from __future__ import annotations

"""
Browser action tests using a real Chromium instance (headless) via
pytest-playwright / async_playwright.

Each test intercepts https://x.com/** at the network layer and serves
locally-crafted HTML that mimics the relevant Twitter DOM structure.
This lets us test every code path in actions.py without hitting the
real network.
"""

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeout

from twitter_cleaner.browser.actions import (
    _is_login_page,
    _is_unavailable,
    delete_tweet,
    undo_retweet,
    unlike_tweet,
)
import twitter_cleaner.browser.actions as actions_mod


# ---------------------------------------------------------------------------
# HTML templates
# ---------------------------------------------------------------------------

def _tweet_page(username: str, tweet_id: str) -> str:
    """All interactive elements pre-shown — the mock only needs them visible,
    not hidden-then-revealed, so we skip JS open/close simulation."""
    return f"""<!DOCTYPE html><html><body>
<article data-testid="tweet">
  <a href="/{username}/status/{tweet_id}">link</a>
  <div data-testid="caret">&#8942;</div>
</article>
<div role="menuitem">Delete</div>
<div data-testid="confirmationSheetConfirm">Confirm</div>
</body></html>"""


def _retweet_page(username: str, tweet_id: str) -> str:
    return f"""<!DOCTYPE html><html><body>
<article data-testid="tweet">
  <a href="/{username}/status/{tweet_id}">link</a>
  <div data-testid="unretweet">RT</div>
</article>
<div role="menuitem">Undo Repost</div>
</body></html>"""


def _already_unretweeted_page(username: str, tweet_id: str) -> str:
    return f"""<!DOCTYPE html><html><body>
<article data-testid="tweet">
  <a href="/{username}/status/{tweet_id}">link</a>
  <div data-testid="retweet">RT</div>
</article>
</body></html>"""


def _like_page(tweet_id: str) -> str:
    return f"""<!DOCTYPE html><html><body>
<article data-testid="tweet">
  <a href="/i/web/status/{tweet_id}">link</a>
  <div data-testid="unlike">&#9829;</div>
</article>
</body></html>"""


def _already_liked_page(tweet_id: str) -> str:
    return f"""<!DOCTYPE html><html><body>
<article data-testid="tweet">
  <a href="/i/web/status/{tweet_id}">link</a>
  <div data-testid="like">&#9825;</div>
</article>
</body></html>"""


def _unavailable_page() -> str:
    return """<!DOCTYPE html><html><body>
<div>This Tweet is unavailable</div>
</body></html>"""


def _login_html() -> str:
    return """<!DOCTYPE html><html><body><h1>Log in to X</h1></body></html>"""


async def _route_html(page, url_pattern: str, html: str, status: int = 200):
    """Intercept requests matching url_pattern and serve html."""
    async def handler(route):
        await route.fulfill(
            status=status,
            content_type="text/html",
            body=html,
        )
    await page.route(url_pattern, handler)


async def _route_redirect(page, url_pattern: str, location: str):
    """Intercept requests and redirect to location (which must also be routed)."""
    async def handler(route):
        await route.fulfill(
            status=302,
            headers={"Location": location},
        )
    await page.route(url_pattern, handler)


async def _route_404(page, url_pattern: str):
    async def handler(route):
        await route.fulfill(status=404, body="Not Found")
    await page.route(url_pattern, handler)


# ---------------------------------------------------------------------------
# _is_login_page  (pure string — no browser needed)
# ---------------------------------------------------------------------------

class TestIsLoginPage:
    def test_login_in_path(self):
        assert _is_login_page("https://x.com/i/flow/login")

    def test_signup_in_path(self):
        assert _is_login_page("https://x.com/i/flow/signup")

    def test_login_substring(self):
        assert _is_login_page("https://x.com/login?redirect=home")

    def test_home_is_not_login(self):
        assert not _is_login_page("https://x.com/home")

    def test_status_url_is_not_login(self):
        assert not _is_login_page("https://x.com/user/status/123")

    def test_empty_string(self):
        assert not _is_login_page("")


# ---------------------------------------------------------------------------
# _is_unavailable  (needs live page)
# ---------------------------------------------------------------------------

class TestIsUnavailable:
    async def test_unavailable_tweet_text(self, page):
        await page.set_content("<div>This Tweet is unavailable</div>")
        assert await _is_unavailable(page)

    async def test_unavailable_post_text(self, page):
        await page.set_content("<div>This post is unavailable</div>")
        assert await _is_unavailable(page)

    async def test_something_went_wrong(self, page):
        await page.set_content("<div>Something went wrong</div>")
        assert await _is_unavailable(page)

    async def test_page_doesnt_exist(self, page):
        await page.set_content("<div>Hmm, this page doesn't exist</div>")
        assert await _is_unavailable(page)

    async def test_normal_page_not_unavailable(self, page):
        await page.set_content("<div>A normal tweet here</div>")
        assert not await _is_unavailable(page)

    async def test_empty_page(self, page):
        await page.set_content("<html><body></body></html>")
        assert not await _is_unavailable(page)


# ---------------------------------------------------------------------------
# delete_tweet
# ---------------------------------------------------------------------------

class TestDeleteTweet:
    USERNAME = "testuser"
    TWEET_ID = "123456"

    async def test_success(self, page, monkeypatch):
        monkeypatch.setattr(actions_mod, "TIMEOUT", 5000)
        url_pat = f"**/status/{self.TWEET_ID}"
        await _route_html(page, url_pat, _tweet_page(self.USERNAME, self.TWEET_ID))
        result = await delete_tweet(page, self.TWEET_ID, self.USERNAME)
        assert result == "done"

    async def test_dry_run_returns_done_without_confirming(self, page, monkeypatch):
        monkeypatch.setattr(actions_mod, "TIMEOUT", 5000)
        await _route_html(
            page,
            f"**/status/{self.TWEET_ID}",
            _tweet_page(self.USERNAME, self.TWEET_ID),
        )
        result = await delete_tweet(page, self.TWEET_ID, self.USERNAME, dry_run=True)
        assert result == "done"

    async def test_blocked_on_login_redirect(self, page, monkeypatch):
        monkeypatch.setattr(actions_mod, "TIMEOUT", 5000)
        login_url = "https://x.com/i/flow/login"
        await _route_redirect(page, f"**/status/{self.TWEET_ID}", login_url)
        await _route_html(page, "**/i/flow/login", _login_html())
        result = await delete_tweet(page, self.TWEET_ID, self.USERNAME)
        assert result == "blocked"

    async def test_skipped_on_404(self, page, monkeypatch):
        monkeypatch.setattr(actions_mod, "TIMEOUT", 5000)
        await _route_404(page, f"**/status/{self.TWEET_ID}")
        result = await delete_tweet(page, self.TWEET_ID, self.USERNAME)
        assert result == "skipped"

    async def test_skipped_on_unavailable_page(self, page, monkeypatch):
        monkeypatch.setattr(actions_mod, "TIMEOUT", 5000)
        await _route_html(page, f"**/status/{self.TWEET_ID}", _unavailable_page())
        result = await delete_tweet(page, self.TWEET_ID, self.USERNAME)
        assert result == "skipped"

    async def test_failed_on_navigation_timeout(self, page, monkeypatch):
        monkeypatch.setattr(actions_mod, "TIMEOUT", 5000)

        async def slow_goto(*args, **kwargs):
            raise PlaywrightTimeout("nav timeout")

        monkeypatch.setattr(page, "goto", slow_goto)
        result = await delete_tweet(page, self.TWEET_ID, self.USERNAME)
        assert result == "failed"

    async def test_failed_when_caret_missing(self, page, monkeypatch):
        # Page has the article but no caret → wait_for times out
        monkeypatch.setattr(actions_mod, "TIMEOUT", 200)
        html = f"""<html><body>
<article data-testid="tweet">
  <a href="/{self.USERNAME}/status/{self.TWEET_ID}">link</a>
</article></body></html>"""
        await _route_html(page, f"**/status/{self.TWEET_ID}", html)
        result = await delete_tweet(page, self.TWEET_ID, self.USERNAME)
        assert result == "failed"

    async def test_failed_when_article_missing(self, page, monkeypatch):
        monkeypatch.setattr(actions_mod, "TIMEOUT", 200)
        html = "<html><body><p>No tweet article here</p></body></html>"
        await _route_html(page, f"**/status/{self.TWEET_ID}", html)
        result = await delete_tweet(page, self.TWEET_ID, self.USERNAME)
        assert result == "failed"


# ---------------------------------------------------------------------------
# undo_retweet
# ---------------------------------------------------------------------------

class TestUndoRetweet:
    USERNAME = "testuser"
    TWEET_ID = "789012"

    async def test_success(self, page, monkeypatch):
        monkeypatch.setattr(actions_mod, "TIMEOUT", 5000)
        await _route_html(
            page,
            f"**/status/{self.TWEET_ID}",
            _retweet_page(self.USERNAME, self.TWEET_ID),
        )
        result = await undo_retweet(page, self.TWEET_ID, self.USERNAME)
        assert result == "done"

    async def test_dry_run(self, page, monkeypatch):
        monkeypatch.setattr(actions_mod, "TIMEOUT", 5000)
        await _route_html(
            page,
            f"**/status/{self.TWEET_ID}",
            _retweet_page(self.USERNAME, self.TWEET_ID),
        )
        result = await undo_retweet(page, self.TWEET_ID, self.USERNAME, dry_run=True)
        assert result == "done"

    async def test_skipped_when_already_unretweeted(self, page, monkeypatch):
        monkeypatch.setattr(actions_mod, "TIMEOUT", 5000)
        await _route_html(
            page,
            f"**/status/{self.TWEET_ID}",
            _already_unretweeted_page(self.USERNAME, self.TWEET_ID),
        )
        result = await undo_retweet(page, self.TWEET_ID, self.USERNAME)
        assert result == "skipped"

    async def test_blocked_on_login_redirect(self, page, monkeypatch):
        monkeypatch.setattr(actions_mod, "TIMEOUT", 5000)
        login_url = "https://x.com/i/flow/login"
        await _route_redirect(page, f"**/status/{self.TWEET_ID}", login_url)
        await _route_html(page, "**/i/flow/login", _login_html())
        result = await undo_retweet(page, self.TWEET_ID, self.USERNAME)
        assert result == "blocked"

    async def test_skipped_on_404(self, page, monkeypatch):
        monkeypatch.setattr(actions_mod, "TIMEOUT", 5000)
        await _route_404(page, f"**/status/{self.TWEET_ID}")
        result = await undo_retweet(page, self.TWEET_ID, self.USERNAME)
        assert result == "skipped"

    async def test_skipped_on_unavailable(self, page, monkeypatch):
        monkeypatch.setattr(actions_mod, "TIMEOUT", 5000)
        await _route_html(page, f"**/status/{self.TWEET_ID}", _unavailable_page())
        result = await undo_retweet(page, self.TWEET_ID, self.USERNAME)
        assert result == "skipped"

    async def test_failed_on_navigation_timeout(self, page, monkeypatch):
        monkeypatch.setattr(actions_mod, "TIMEOUT", 5000)

        async def slow_goto(*args, **kwargs):
            raise PlaywrightTimeout("nav timeout")

        monkeypatch.setattr(page, "goto", slow_goto)
        result = await undo_retweet(page, self.TWEET_ID, self.USERNAME)
        assert result == "failed"

    async def test_skipped_when_button_missing(self, page, monkeypatch):
        # No retweet OR unretweet button → timeout → skipped (per code)
        monkeypatch.setattr(actions_mod, "TIMEOUT", 200)
        html = f"""<html><body>
<article data-testid="tweet">
  <a href="/{self.USERNAME}/status/{self.TWEET_ID}">link</a>
</article></body></html>"""
        await _route_html(page, f"**/status/{self.TWEET_ID}", html)
        result = await undo_retweet(page, self.TWEET_ID, self.USERNAME)
        assert result == "skipped"


# ---------------------------------------------------------------------------
# unlike_tweet
# ---------------------------------------------------------------------------

class TestUnlikeTweet:
    TWEET_ID = "345678"

    async def test_success(self, page, monkeypatch):
        monkeypatch.setattr(actions_mod, "TIMEOUT", 5000)
        await _route_html(
            page,
            f"**/status/{self.TWEET_ID}",
            _like_page(self.TWEET_ID),
        )
        result = await unlike_tweet(page, self.TWEET_ID)
        assert result == "done"

    async def test_dry_run(self, page, monkeypatch):
        monkeypatch.setattr(actions_mod, "TIMEOUT", 5000)
        await _route_html(
            page,
            f"**/status/{self.TWEET_ID}",
            _like_page(self.TWEET_ID),
        )
        result = await unlike_tweet(page, self.TWEET_ID, dry_run=True)
        assert result == "done"

    async def test_skipped_when_not_liked(self, page, monkeypatch):
        monkeypatch.setattr(actions_mod, "TIMEOUT", 5000)
        await _route_html(
            page,
            f"**/status/{self.TWEET_ID}",
            _already_liked_page(self.TWEET_ID),
        )
        result = await unlike_tweet(page, self.TWEET_ID)
        assert result == "skipped"

    async def test_blocked_on_login_redirect(self, page, monkeypatch):
        monkeypatch.setattr(actions_mod, "TIMEOUT", 5000)
        login_url = "https://x.com/i/flow/login"
        await _route_redirect(page, f"**/status/{self.TWEET_ID}", login_url)
        await _route_html(page, "**/i/flow/login", _login_html())
        result = await unlike_tweet(page, self.TWEET_ID)
        assert result == "blocked"

    async def test_skipped_on_404(self, page, monkeypatch):
        monkeypatch.setattr(actions_mod, "TIMEOUT", 5000)
        await _route_404(page, f"**/status/{self.TWEET_ID}")
        result = await unlike_tweet(page, self.TWEET_ID)
        assert result == "skipped"

    async def test_skipped_on_unavailable(self, page, monkeypatch):
        monkeypatch.setattr(actions_mod, "TIMEOUT", 5000)
        await _route_html(page, f"**/status/{self.TWEET_ID}", _unavailable_page())
        result = await unlike_tweet(page, self.TWEET_ID)
        assert result == "skipped"

    async def test_failed_on_navigation_timeout(self, page, monkeypatch):
        monkeypatch.setattr(actions_mod, "TIMEOUT", 5000)

        async def slow_goto(*args, **kwargs):
            raise PlaywrightTimeout("nav timeout")

        monkeypatch.setattr(page, "goto", slow_goto)
        result = await unlike_tweet(page, self.TWEET_ID)
        assert result == "failed"

    async def test_failed_when_heart_button_missing(self, page, monkeypatch):
        # Neither like nor unlike button present → timeout → failed
        monkeypatch.setattr(actions_mod, "TIMEOUT", 200)
        html = "<html><body><p>no buttons here</p></body></html>"
        await _route_html(page, f"**/status/{self.TWEET_ID}", html)
        result = await unlike_tweet(page, self.TWEET_ID)
        assert result == "failed"
