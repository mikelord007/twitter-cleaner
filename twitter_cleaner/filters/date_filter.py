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
