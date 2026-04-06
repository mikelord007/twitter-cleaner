from __future__ import annotations

import contextlib
import sqlite3
from typing import AsyncIterator

import click


@contextlib.asynccontextmanager
async def handle_errors() -> AsyncIterator[None]:
    """Wrap an async block and convert known exceptions into friendly CLI errors."""
    try:
        yield
    except (click.ClickException, click.Abort, SystemExit):
        raise
    except KeyboardInterrupt:
        raise click.Abort()
    except Exception as exc:
        raise _friendly(exc) from exc


def _friendly(exc: Exception) -> click.ClickException:
    # Playwright errors
    try:
        from playwright.async_api import Error as _PWError, TimeoutError as _PWTimeout
        if isinstance(exc, (_PWError, _PWTimeout)):
            return click.ClickException(_playwright_msg(str(exc)))
    except ImportError:
        pass

    # SQLite errors
    if isinstance(exc, sqlite3.OperationalError):
        msg = str(exc)
        if "locked" in msg:
            return click.ClickException(
                "Progress database is locked by another process.\n"
                "Make sure no other instance of twitter-cleaner is running, then retry."
            )
        if "no such table" in msg or "no such column" in msg:
            return click.ClickException(
                "Progress database schema is outdated or corrupted.\n"
                "Fix: delete .twitter_cleaner/progress.db and run 'twitter-cleaner parse' again."
            )
        if "unable to open" in msg:
            return click.ClickException(
                f"Cannot open progress database: {msg}\n"
                "Check that .twitter_cleaner/ is writable and you have enough disk space."
            )
        if "disk I/O" in msg or "disk full" in msg:
            return click.ClickException(
                "Disk I/O error writing to the progress database.\n"
                "Check available disk space."
            )
        return click.ClickException(f"Database error: {exc}")

    if isinstance(exc, sqlite3.DatabaseError):
        return click.ClickException(
            "Progress database is corrupted.\n"
            "Fix: delete .twitter_cleaner/progress.db and run 'twitter-cleaner parse' again."
        )

    # File / permission errors
    if isinstance(exc, PermissionError):
        return click.ClickException(
            f"Permission denied: {exc.filename or exc}\n"
            "Check that the file or directory is not open in another program."
        )

    # Login / session errors raised explicitly by this tool
    if isinstance(exc, RuntimeError):
        msg = str(exc)
        if "Login timed out" in msg:
            return click.ClickException(
                "Login timed out after 5 minutes.\n"
                "Run the command again and complete the login in the browser window that opens."
            )
        if "Login did not complete" in msg:
            return click.ClickException(
                "Login was not completed successfully.\n"
                "Make sure you entered the correct credentials and finished any 2FA steps."
            )
        return click.ClickException(f"Error: {exc}")

    return click.ClickException(f"{type(exc).__name__}: {exc}")


def _playwright_msg(msg: str) -> str:
    low = msg.lower()
    if "executable doesn't exist" in low or ("chrome" in low and "not found" in low):
        return (
            "Chrome was not found on your system.\n"
            "Install Google Chrome, or run:  playwright install chrome"
        )
    if "target closed" in low or "browser closed" in low or "browser has been closed" in low or "context or browser" in low:
        return (
            "The browser was closed unexpectedly.\n"
            "Progress is saved — rerun the same command to resume."
        )
    if "page crashed" in low:
        return (
            "The browser page crashed.\n"
            "Progress is saved — rerun the same command to resume."
        )
    if "err_internet_disconnected" in low or "err_name_not_resolved" in low:
        return "No internet connection. Check your network and try again."
    if "net::err_" in low or "ns_error_" in low:
        return (
            f"Network error communicating with Twitter. Check your connection.\n"
            f"Detail: {msg}"
        )
    if "timeout" in low:
        return (
            "Timed out waiting for Twitter to respond.\n"
            "Twitter may be slow or rate-limiting requests. Wait a few minutes, then retry.\n"
            "Tip: increase --min-delay / --max-delay to slow down requests."
        )
    return f"Browser error: {msg}"
