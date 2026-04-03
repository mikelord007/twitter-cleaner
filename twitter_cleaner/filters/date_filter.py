from __future__ import annotations

from datetime import datetime, timezone


# Twitter archive date format: "Mon Jan 01 00:00:00 +0000 2024"
_ARCHIVE_FMT = "%a %b %d %H:%M:%S %z %Y"


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
        return True  # include if date unknown
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    return dt < cutoff


def after_date(created_at: str, cutoff: datetime) -> bool:
    """Return True if the tweet was posted after the cutoff date."""
    dt = parse_tweet_date(created_at)
    if dt is None:
        return True  # include if date unknown
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
