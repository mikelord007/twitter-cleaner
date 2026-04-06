from __future__ import annotations

from datetime import datetime, timezone


# Twitter archive date format: "Mon Jan 01 00:00:00 +0000 2024"
_ARCHIVE_FMT = "%a %b %d %H:%M:%S %z %Y"

# Twitter snowflake epoch (ms)
_TWITTER_EPOCH_MS = 1288834974657


def tweet_id_to_created_at(tweet_id: str) -> str | None:
    """Derive approximate creation date from a Twitter snowflake ID."""
    try:
        ts_ms = (int(tweet_id) >> 22) + _TWITTER_EPOCH_MS
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        return dt.strftime(_ARCHIVE_FMT)
    except (ValueError, OSError, OverflowError):
        return None


def parse_tweet_date(created_at: str) -> datetime | None:
    if not created_at:
        return None
    try:
        return datetime.strptime(created_at, _ARCHIVE_FMT)
    except ValueError:
        return None


def before_date(created_at: str, cutoff: datetime) -> bool:
    """Return True if the tweet was posted before the cutoff date."""
    dt = parse_tweet_date(created_at)
    if dt is None:
        return False  # skip if date unknown — don't delete without confirmation
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    return dt < cutoff


def after_date(created_at: str, cutoff: datetime) -> bool:
    """Return True if the tweet was posted after the cutoff date."""
    dt = parse_tweet_date(created_at)
    if dt is None:
        return False  # skip if date unknown — don't delete without confirmation
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    return dt > cutoff


def in_date_range(
    created_at: str,
    before: datetime | None,
    after: datetime | None,
) -> bool:
    """Return True if the tweet falls within the specified date range."""
    if before and not before_date(created_at, before):
        return False
    if after and not after_date(created_at, after):
        return False
    return True
