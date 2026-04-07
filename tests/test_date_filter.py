from __future__ import annotations

from datetime import datetime, timezone

import pytest

from twitter_cleaner.filters.date_filter import (
    _ARCHIVE_FMT,
    _TWITTER_EPOCH_MS,
    after_date,
    before_date,
    in_date_range,
    parse_tweet_date,
    tweet_id_to_created_at,
)


# ---------------------------------------------------------------------------
# tweet_id_to_created_at
# ---------------------------------------------------------------------------

class TestTweetIdToCreatedAt:
    def test_known_snowflake(self):
        # Snowflake 20 bits shifted right gives timestamp
        # id 1354143047122325504 was a real tweet from ~Jan 26 2021
        result = tweet_id_to_created_at("1354143047122325504")
        assert result is not None
        dt = datetime.strptime(result, _ARCHIVE_FMT)
        assert dt.year == 2021

    def test_non_numeric_returns_none(self):
        assert tweet_id_to_created_at("not-a-number") is None

    def test_empty_string_returns_none(self):
        assert tweet_id_to_created_at("") is None

    def test_zero_id_returns_epoch_area(self):
        result = tweet_id_to_created_at("0")
        assert result is not None  # id 0 → timestamp at epoch offset

    def test_very_large_id_returns_none_or_str(self):
        # Overflow-safe: should either return None or a valid string
        result = tweet_id_to_created_at("9" * 30)
        # Either None (OSError/OverflowError) or a valid date string
        if result is not None:
            datetime.strptime(result, _ARCHIVE_FMT)

    def test_returns_utc_format(self):
        result = tweet_id_to_created_at("1354143047122325504")
        assert "+0000" in result


# ---------------------------------------------------------------------------
# parse_tweet_date
# ---------------------------------------------------------------------------

class TestParseTweetDate:
    def test_valid_date(self):
        dt = parse_tweet_date("Mon Jan 01 00:00:00 +0000 2022")
        assert dt is not None
        assert dt.year == 2022
        assert dt.month == 1
        assert dt.day == 1

    def test_empty_string_returns_none(self):
        assert parse_tweet_date("") is None

    def test_none_string_returns_none(self):
        assert parse_tweet_date(None) is None

    def test_wrong_format_returns_none(self):
        assert parse_tweet_date("2022-01-01") is None
        assert parse_tweet_date("January 1 2022") is None

    def test_timezone_info_present(self):
        dt = parse_tweet_date("Mon Jan 01 12:00:00 +0000 2022")
        assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# before_date
# ---------------------------------------------------------------------------

class TestBeforeDate:
    CUTOFF = datetime(2023, 1, 1, tzinfo=timezone.utc)

    def test_before_returns_true(self):
        assert before_date("Mon Jan 01 00:00:00 +0000 2022", self.CUTOFF)

    def test_after_returns_false(self):
        assert not before_date("Mon Jan 01 00:00:00 +0000 2024", self.CUTOFF)

    def test_equal_returns_false(self):
        # "before" is strictly less than
        assert not before_date("Sun Jan 01 00:00:00 +0000 2023", self.CUTOFF)

    def test_unknown_date_returns_false(self):
        assert not before_date("", self.CUTOFF)
        assert not before_date("bad-date", self.CUTOFF)

    def test_naive_cutoff_gets_utc(self):
        naive_cutoff = datetime(2023, 1, 1)
        assert before_date("Mon Jan 01 00:00:00 +0000 2022", naive_cutoff)


# ---------------------------------------------------------------------------
# after_date
# ---------------------------------------------------------------------------

class TestAfterDate:
    CUTOFF = datetime(2023, 1, 1, tzinfo=timezone.utc)

    def test_after_returns_true(self):
        assert after_date("Mon Jan 01 00:00:00 +0000 2024", self.CUTOFF)

    def test_before_returns_false(self):
        assert not after_date("Mon Jan 01 00:00:00 +0000 2022", self.CUTOFF)

    def test_equal_returns_false(self):
        assert not after_date("Sun Jan 01 00:00:00 +0000 2023", self.CUTOFF)

    def test_unknown_date_returns_false(self):
        assert not after_date("", self.CUTOFF)

    def test_naive_cutoff_gets_utc(self):
        naive_cutoff = datetime(2023, 1, 1)
        assert after_date("Mon Jan 01 00:00:00 +0000 2024", naive_cutoff)


# ---------------------------------------------------------------------------
# in_date_range
# ---------------------------------------------------------------------------

class TestInDateRange:
    BEFORE = datetime(2024, 1, 1, tzinfo=timezone.utc)
    AFTER = datetime(2022, 1, 1, tzinfo=timezone.utc)
    IN_RANGE = "Mon Jan 01 00:00:00 +0000 2023"
    TOO_NEW = "Mon Jan 01 00:00:00 +0000 2025"
    TOO_OLD = "Mon Jan 01 00:00:00 +0000 2021"

    def test_within_range(self):
        assert in_date_range(self.IN_RANGE, self.BEFORE, self.AFTER)

    def test_too_new_fails_before(self):
        assert not in_date_range(self.TOO_NEW, self.BEFORE, self.AFTER)

    def test_too_old_fails_after(self):
        assert not in_date_range(self.TOO_OLD, self.BEFORE, self.AFTER)

    def test_only_before(self):
        assert in_date_range(self.IN_RANGE, before=self.BEFORE, after=None)
        assert not in_date_range(self.TOO_NEW, before=self.BEFORE, after=None)

    def test_only_after(self):
        assert in_date_range(self.IN_RANGE, before=None, after=self.AFTER)
        assert not in_date_range(self.TOO_OLD, before=None, after=self.AFTER)

    def test_no_filters_always_true(self):
        assert in_date_range(self.IN_RANGE, before=None, after=None)
        assert in_date_range("", before=None, after=None)

    def test_unknown_date_with_filter_returns_false(self):
        assert not in_date_range("", before=self.BEFORE, after=None)
        assert not in_date_range("bad", before=None, after=self.AFTER)
