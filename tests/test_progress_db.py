from __future__ import annotations

import pytest

from twitter_cleaner.store.progress_db import ItemStats, ProgressDB


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _row(id: str, type_: str, date: str | None = None, text: str | None = None) -> tuple:
    return (id, type_, f"https://x.com/u/status/{id}", date, text)


# ---------------------------------------------------------------------------
# ItemStats
# ---------------------------------------------------------------------------

class TestItemStats:
    def test_total(self):
        s = ItemStats(pending=1, done=2, failed=3, skipped=4)
        assert s.total == 10

    def test_all_zeros(self):
        assert ItemStats().total == 0


# ---------------------------------------------------------------------------
# bulk_insert_pending
# ---------------------------------------------------------------------------

class TestBulkInsertPending:
    def test_insert_new_rows(self, db):
        new, backfilled = db.bulk_insert_pending([_row("1", "tweet")])
        assert new == 1
        assert backfilled == 0

    def test_duplicate_ignored(self, db):
        db.bulk_insert_pending([_row("1", "tweet")])
        new, _ = db.bulk_insert_pending([_row("1", "tweet")])
        assert new == 0

    def test_same_id_different_type_both_inserted(self, db):
        new1, _ = db.bulk_insert_pending([_row("1", "tweet")])
        new2, _ = db.bulk_insert_pending([_row("1", "like")])
        assert new1 == 1
        assert new2 == 1

    def test_backfill_tweet_date_on_existing_null(self, db):
        db.bulk_insert_pending([_row("1", "tweet", date=None)])
        _, backfilled = db.bulk_insert_pending([_row("1", "tweet", date="Mon Jan 01 00:00:00 +0000 2022")])
        assert backfilled == 1

    def test_no_backfill_when_date_already_set(self, db):
        db.bulk_insert_pending([_row("1", "tweet", date="Mon Jan 01 00:00:00 +0000 2022")])
        _, backfilled = db.bulk_insert_pending([_row("1", "tweet", date="Tue Jan 02 00:00:00 +0000 2022")])
        assert backfilled == 0

    def test_empty_list(self, db):
        new, backfilled = db.bulk_insert_pending([])
        assert new == 0
        assert backfilled == 0

    def test_multiple_rows_at_once(self, db):
        rows = [_row(str(i), "tweet") for i in range(10)]
        new, _ = db.bulk_insert_pending(rows)
        assert new == 10

    def test_status_defaults_to_pending(self, db):
        db.bulk_insert_pending([_row("1", "tweet")])
        pending = db.get_pending()
        assert pending[0]["status"] == "pending"


# ---------------------------------------------------------------------------
# get_pending
# ---------------------------------------------------------------------------

class TestGetPending:
    def test_returns_pending_items(self, db):
        db.bulk_insert_pending([_row("1", "tweet")])
        rows = db.get_pending()
        assert len(rows) == 1

    def test_does_not_return_done(self, db):
        db.bulk_insert_pending([_row("1", "tweet")])
        db.mark_done("1", "tweet")
        assert db.get_pending() == []

    def test_does_not_return_skipped(self, db):
        db.bulk_insert_pending([_row("1", "tweet")])
        db.mark_skipped("1", "tweet")
        assert db.get_pending() == []

    def test_returns_failed_items(self, db):
        db.bulk_insert_pending([_row("1", "tweet")])
        db.mark_failed("1", "tweet", "oops")
        rows = db.get_pending()
        assert len(rows) == 1

    def test_excludes_items_with_retry_count_3(self, db):
        db.bulk_insert_pending([_row("1", "tweet")])
        db.mark_failed("1", "tweet", "e1")
        db.mark_failed("1", "tweet", "e2")
        db.mark_failed("1", "tweet", "e3")
        assert db.get_pending() == []

    def test_type_filter(self, db):
        db.bulk_insert_pending([_row("1", "tweet"), _row("2", "like")])
        rows = db.get_pending(item_types=["tweet"])
        assert len(rows) == 1
        assert rows[0]["type"] == "tweet"

    def test_limit_respected(self, db):
        db.bulk_insert_pending([_row(str(i), "tweet") for i in range(20)])
        rows = db.get_pending(limit=5)
        assert len(rows) == 5

    def test_empty_db_returns_empty(self, db):
        assert db.get_pending() == []

    def test_type_ordering(self, db):
        # tweet=1, like=5 → tweet should come first
        db.bulk_insert_pending([_row("1", "like"), _row("2", "tweet")])
        rows = db.get_pending()
        assert rows[0]["type"] == "tweet"
        assert rows[1]["type"] == "like"


# ---------------------------------------------------------------------------
# mark_done / mark_failed / mark_skipped
# ---------------------------------------------------------------------------

class TestMarkStatus:
    def test_mark_done(self, db):
        db.bulk_insert_pending([_row("1", "tweet")])
        db.mark_done("1", "tweet")
        assert db.stats().done == 1
        assert db.stats().pending == 0

    def test_mark_failed_increments_retry_count(self, db):
        db.bulk_insert_pending([_row("1", "tweet")])
        db.mark_failed("1", "tweet", "error message")
        rows = db.get_pending()
        assert rows[0]["retry_count"] == 1
        assert rows[0]["error_msg"] == "error message"

    def test_mark_failed_twice_retry_count_2(self, db):
        db.bulk_insert_pending([_row("1", "tweet")])
        db.mark_failed("1", "tweet", "e")
        db.mark_failed("1", "tweet", "e")
        assert db.get_pending()[0]["retry_count"] == 2

    def test_mark_skipped(self, db):
        db.bulk_insert_pending([_row("1", "like")])
        db.mark_skipped("1", "like")
        assert db.stats().skipped == 1
        assert db.stats().pending == 0

    def test_mark_nonexistent_item_no_error(self, db):
        db.mark_done("999", "tweet")  # should not raise

    def test_mark_done_only_affects_matching_row(self, db):
        db.bulk_insert_pending([_row("1", "tweet"), _row("2", "tweet")])
        db.mark_done("1", "tweet")
        assert db.stats().done == 1
        assert db.stats().pending == 1


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

class TestStats:
    def test_empty_db(self, db):
        s = db.stats()
        assert s.total == 0

    def test_all_statuses(self, db):
        db.bulk_insert_pending([
            _row("1", "tweet"),
            _row("2", "tweet"),
            _row("3", "tweet"),
            _row("4", "tweet"),
        ])
        db.mark_done("1", "tweet")
        db.mark_failed("2", "tweet", "e")
        db.mark_skipped("3", "tweet")
        s = db.stats()
        assert s.pending == 1
        assert s.done == 1
        assert s.failed == 1
        assert s.skipped == 1

    def test_type_filter(self, db):
        db.bulk_insert_pending([_row("1", "tweet"), _row("2", "like")])
        db.mark_done("1", "tweet")
        s = db.stats(item_types=["tweet"])
        assert s.done == 1
        assert s.pending == 0

    def test_type_filter_excludes_other_types(self, db):
        db.bulk_insert_pending([_row("1", "tweet"), _row("2", "like")])
        s = db.stats(item_types=["like"])
        assert s.pending == 1
        assert s.total == 1


# ---------------------------------------------------------------------------
# stats_by_type
# ---------------------------------------------------------------------------

class TestStatsByType:
    def test_multiple_types(self, db):
        db.bulk_insert_pending([_row("1", "tweet"), _row("2", "like")])
        stats = db.stats_by_type()
        assert "tweet" in stats
        assert "like" in stats
        assert stats["tweet"].pending == 1
        assert stats["like"].pending == 1

    def test_empty_returns_empty_dict(self, db):
        assert db.stats_by_type() == {}

    def test_done_counted_per_type(self, db):
        db.bulk_insert_pending([_row("1", "tweet"), _row("2", "like")])
        db.mark_done("1", "tweet")
        stats = db.stats_by_type()
        assert stats["tweet"].done == 1
        assert stats["like"].pending == 1


# ---------------------------------------------------------------------------
# pending_dates
# ---------------------------------------------------------------------------

class TestPendingDates:
    def test_returns_date_and_type(self, db):
        db.bulk_insert_pending([_row("1", "tweet", date="Mon Jan 01 00:00:00 +0000 2022")])
        rows = db.pending_dates()
        assert len(rows) == 1
        assert rows[0]["type"] == "tweet"
        assert rows[0]["tweet_date"] == "Mon Jan 01 00:00:00 +0000 2022"

    def test_excludes_done(self, db):
        db.bulk_insert_pending([_row("1", "tweet")])
        db.mark_done("1", "tweet")
        assert db.pending_dates() == []

    def test_type_filter(self, db):
        db.bulk_insert_pending([_row("1", "tweet"), _row("2", "like")])
        rows = db.pending_dates(item_types=["tweet"])
        assert all(r["type"] == "tweet" for r in rows)

    def test_no_limit(self, db):
        rows = [_row(str(i), "tweet") for i in range(200)]
        db.bulk_insert_pending(rows)
        assert len(db.pending_dates()) == 200


# ---------------------------------------------------------------------------
# reset_status
# ---------------------------------------------------------------------------

class TestResetStatus:
    def test_reset_failed_to_pending(self, db):
        db.bulk_insert_pending([_row("1", "tweet")])
        db.mark_failed("1", "tweet", "e")
        count = db.reset_status(None, "failed")
        assert count == 1
        assert db.stats().pending == 1
        assert db.stats().failed == 0

    def test_reset_skipped_to_pending(self, db):
        db.bulk_insert_pending([_row("1", "tweet")])
        db.mark_skipped("1", "tweet")
        db.reset_status(None, "skipped")
        assert db.stats().pending == 1

    def test_reset_specific_type(self, db):
        db.bulk_insert_pending([_row("1", "tweet"), _row("2", "like")])
        db.mark_failed("1", "tweet", "e")
        db.mark_failed("2", "like", "e")
        db.reset_status("tweet", "failed")
        stats = db.stats_by_type()
        assert stats["tweet"].pending == 1
        assert stats["like"].failed == 1

    def test_reset_returns_count(self, db):
        db.bulk_insert_pending([_row("1", "tweet"), _row("2", "tweet")])
        db.mark_failed("1", "tweet", "e")
        db.mark_failed("2", "tweet", "e")
        count = db.reset_status(None, "failed")
        assert count == 2

    def test_reset_resets_retry_count(self, db):
        db.bulk_insert_pending([_row("1", "tweet")])
        db.mark_failed("1", "tweet", "e")
        db.reset_status(None, "failed")
        rows = db.get_pending()
        assert rows[0]["retry_count"] == 0

    def test_reset_nothing_returns_zero(self, db):
        db.bulk_insert_pending([_row("1", "tweet")])
        count = db.reset_status(None, "failed")
        assert count == 0
