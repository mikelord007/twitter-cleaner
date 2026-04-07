from __future__ import annotations

import sqlite3

import pytest
import click

from twitter_cleaner.errors import _friendly, _playwright_msg, handle_errors


# ---------------------------------------------------------------------------
# handle_errors context manager
# ---------------------------------------------------------------------------

class TestHandleErrors:
    async def test_click_exception_passes_through(self):
        with pytest.raises(click.ClickException):
            async with handle_errors():
                raise click.ClickException("boom")

    async def test_click_abort_passes_through(self):
        with pytest.raises(click.Abort):
            async with handle_errors():
                raise click.Abort()

    async def test_system_exit_passes_through(self):
        with pytest.raises(SystemExit):
            async with handle_errors():
                raise SystemExit(0)

    async def test_keyboard_interrupt_becomes_abort(self):
        with pytest.raises(click.Abort):
            async with handle_errors():
                raise KeyboardInterrupt()

    async def test_generic_exception_becomes_click_exception(self):
        with pytest.raises(click.ClickException):
            async with handle_errors():
                raise RuntimeError("something broke")

    async def test_no_exception_passes(self):
        async with handle_errors():
            pass  # should not raise


# ---------------------------------------------------------------------------
# _friendly — SQLite errors
# ---------------------------------------------------------------------------

class TestFriendlySQLite:
    def test_locked(self):
        exc = sqlite3.OperationalError("database is locked")
        result = _friendly(exc)
        assert "locked" in result.format_message().lower()

    def test_no_such_table(self):
        exc = sqlite3.OperationalError("no such table: items")
        result = _friendly(exc)
        assert "schema" in result.format_message().lower() or "corrupted" in result.format_message().lower()

    def test_no_such_column(self):
        exc = sqlite3.OperationalError("no such column: foo")
        result = _friendly(exc)
        assert isinstance(result, click.ClickException)

    def test_unable_to_open(self):
        exc = sqlite3.OperationalError("unable to open database file")
        result = _friendly(exc)
        assert "writable" in result.format_message() or "open" in result.format_message()

    def test_disk_io(self):
        exc = sqlite3.OperationalError("disk I/O error")
        result = _friendly(exc)
        assert "disk" in result.format_message().lower()

    def test_disk_full(self):
        exc = sqlite3.OperationalError("disk full")
        result = _friendly(exc)
        assert "disk" in result.format_message().lower()

    def test_generic_operational_error(self):
        exc = sqlite3.OperationalError("some other db error")
        result = _friendly(exc)
        assert isinstance(result, click.ClickException)

    def test_database_error(self):
        exc = sqlite3.DatabaseError("corrupted")
        result = _friendly(exc)
        assert "corrupted" in result.format_message().lower()


# ---------------------------------------------------------------------------
# _friendly — other error types
# ---------------------------------------------------------------------------

class TestFriendlyOtherErrors:
    def test_permission_error(self):
        exc = PermissionError("permission denied")
        exc.filename = "/some/file"
        result = _friendly(exc)
        assert "Permission" in result.format_message() or "permission" in result.format_message()

    def test_permission_error_no_filename(self):
        exc = PermissionError("denied")
        exc.filename = None
        result = _friendly(exc)
        assert isinstance(result, click.ClickException)

    def test_runtime_login_timeout(self):
        exc = RuntimeError("Login timed out after 5 minutes")
        result = _friendly(exc)
        assert "5 minutes" in result.format_message()

    def test_runtime_login_did_not_complete(self):
        exc = RuntimeError("Login did not complete -- please try again.")
        result = _friendly(exc)
        assert "credentials" in result.format_message() or "Login" in result.format_message()

    def test_runtime_generic(self):
        exc = RuntimeError("mystery error")
        result = _friendly(exc)
        assert isinstance(result, click.ClickException)

    def test_generic_exception(self):
        exc = ValueError("oops")
        result = _friendly(exc)
        assert "ValueError" in result.format_message()

    def test_playwright_timeout_message(self):
        try:
            from playwright.async_api import TimeoutError as PWTimeout
        except ImportError:
            pytest.skip("playwright not installed")
        exc = PWTimeout("Timeout 10000ms exceeded")
        result = _friendly(exc)
        assert "Timed out" in result.format_message() or "Twitter" in result.format_message()

    def test_playwright_error_browser_closed(self):
        try:
            from playwright.async_api import Error as PWError
        except ImportError:
            pytest.skip("playwright not installed")
        exc = PWError("Target closed")
        result = _friendly(exc)
        assert "closed" in result.format_message().lower()


# ---------------------------------------------------------------------------
# _playwright_msg — all branches
# ---------------------------------------------------------------------------

class TestPlaywrightMsg:
    def test_chrome_not_found_executable(self):
        msg = _playwright_msg("Executable doesn't exist at /usr/bin/chromium")
        assert "Chrome" in msg or "playwright install" in msg

    def test_chrome_not_found_not_found(self):
        msg = _playwright_msg("chrome browser not found on PATH")
        assert "Chrome" in msg

    def test_target_closed(self):
        msg = _playwright_msg("Target closed")
        assert "closed" in msg.lower() or "resume" in msg.lower()

    def test_browser_closed(self):
        msg = _playwright_msg("Browser has been closed")
        assert "closed" in msg.lower()

    def test_context_or_browser(self):
        msg = _playwright_msg("context or browser has been closed")
        assert "closed" in msg.lower()

    def test_page_crashed(self):
        msg = _playwright_msg("Page crashed")
        assert "crashed" in msg.lower() or "resume" in msg.lower()

    def test_internet_disconnected(self):
        msg = _playwright_msg("net::ERR_INTERNET_DISCONNECTED")
        assert "internet" in msg.lower() or "network" in msg.lower()

    def test_err_name_not_resolved(self):
        msg = _playwright_msg("net::ERR_NAME_NOT_RESOLVED")
        assert "network" in msg.lower() or "connection" in msg.lower()

    def test_net_err_generic(self):
        msg = _playwright_msg("net::ERR_CONNECTION_REFUSED")
        assert "Network" in msg or "Twitter" in msg

    def test_timeout(self):
        msg = _playwright_msg("Timeout 30000ms exceeded waiting for element")
        assert "Timed out" in msg or "timeout" in msg.lower()

    def test_generic_browser_error(self):
        msg = _playwright_msg("Some unknown playwright error")
        assert "Browser error" in msg
