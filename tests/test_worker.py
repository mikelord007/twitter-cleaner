from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from twitter_cleaner.config import Config
from twitter_cleaner.store.progress_db import ItemStats, ProgressDB
from twitter_cleaner.worker.runner import (
    _apply_filters,
    _count_filtered_totals,
    _process_one,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cfg():
    return Config(username="testuser", dry_run=False, min_delay=0, max_delay=0, stealth=False)


@pytest.fixture
def dry_cfg():
    return Config(username="testuser", dry_run=True, min_delay=0, max_delay=0, stealth=False)


def _insert(db: ProgressDB, items: list[tuple]) -> None:
    """Insert (id, type, date, text) rows as pending."""
    rows = [(id_, type_, f"http://x.com/u/status/{id_}", date, text)
            for id_, type_, date, text in items]
    db.bulk_insert_pending(rows)


DATE_2022 = "Mon Jan 01 00:00:00 +0000 2022"
DATE_2023 = "Sun Jan 01 00:00:00 +0000 2023"
DATE_2024 = "Mon Jan 01 00:00:00 +0000 2024"

BEFORE_2024 = datetime(2024, 1, 1, tzinfo=timezone.utc)
AFTER_2022 = datetime(2022, 1, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# _count_filtered_totals
# ---------------------------------------------------------------------------

class TestCountFilteredTotals:
    def test_all_in_range(self, db):
        _insert(db, [("1", "tweet", DATE_2023, "hi"), ("2", "like", DATE_2023, "x")])
        counts = _count_filtered_totals(db, None, BEFORE_2024, AFTER_2022)
        assert counts.get("tweet", 0) == 1
        assert counts.get("like", 0) == 1

    def test_none_in_range(self, db):
        _insert(db, [("1", "tweet", DATE_2024, "hi")])  # not before 2024
        counts = _count_filtered_totals(db, None, BEFORE_2024, None)
        assert counts.get("tweet", 0) == 0

    def test_type_filter_respected(self, db):
        _insert(db, [("1", "tweet", DATE_2023, "t"), ("2", "like", DATE_2023, "l")])
        counts = _count_filtered_totals(db, ["tweet"], BEFORE_2024, None)
        assert "tweet" in counts
        assert "like" not in counts

    def test_unknown_date_not_counted(self, db):
        _insert(db, [("1", "tweet", None, "hi")])
        counts = _count_filtered_totals(db, None, BEFORE_2024, None)
        assert counts.get("tweet", 0) == 0


# ---------------------------------------------------------------------------
# _apply_filters
# ---------------------------------------------------------------------------

class TestApplyFilters:
    def _rows(self, db: ProgressDB) -> list:
        return db.get_pending(limit=999_999)

    def test_no_filters_returns_all(self, db):
        _insert(db, [("1", "tweet", DATE_2023, "hi"), ("2", "like", DATE_2022, "x")])
        rows = _apply_filters(db, self._rows(db), None, None, None, "")
        assert len(rows) == 2

    def test_date_filter_before(self, db):
        _insert(db, [
            ("1", "tweet", DATE_2022, "old"),
            ("2", "tweet", DATE_2024, "new"),
        ])
        rows = _apply_filters(db, self._rows(db), BEFORE_2024, None, None, "")
        ids = [r["id"] for r in rows]
        assert "1" in ids
        assert "2" not in ids

    def test_date_filter_after(self, db):
        _insert(db, [
            ("1", "tweet", DATE_2022, "old"),
            ("2", "tweet", DATE_2024, "new"),
        ])
        rows = _apply_filters(db, self._rows(db), None, AFTER_2022, None, "")
        ids = [r["id"] for r in rows]
        assert "2" in ids
        assert "1" not in ids

    def test_date_filter_range(self, db):
        _insert(db, [
            ("1", "tweet", DATE_2022, "old"),
            ("2", "tweet", DATE_2023, "mid"),
            ("3", "tweet", DATE_2024, "new"),
        ])
        rows = _apply_filters(db, self._rows(db), BEFORE_2024, AFTER_2022, None, "")
        ids = [r["id"] for r in rows]
        assert ids == ["2"]

    def test_llm_filter_match(self, db):
        _insert(db, [("1", "tweet", None, "crypto tweet")])
        llm = MagicMock()
        llm.classify_batch.return_value = [True]
        rows = _apply_filters(db, self._rows(db), None, None, llm, "about crypto")
        assert len(rows) == 1

    def test_llm_filter_no_match_marks_skipped(self, db):
        _insert(db, [("1", "tweet", None, "good morning")])
        llm = MagicMock()
        llm.classify_batch.return_value = [False]
        rows = _apply_filters(db, self._rows(db), None, None, llm, "about crypto")
        assert rows == []
        assert db.stats().skipped == 1

    def test_llm_filter_no_match_dry_run_does_not_skip(self, db):
        _insert(db, [("1", "tweet", None, "good morning")])
        llm = MagicMock()
        llm.classify_batch.return_value = [False]
        rows = _apply_filters(db, self._rows(db), None, None, llm, "about crypto", dry_run=True)
        assert rows == []
        assert db.stats().skipped == 0  # not written to DB in dry_run

    def test_llm_called_with_correct_texts(self, db):
        _insert(db, [("1", "tweet", None, "hello world")])
        llm = MagicMock()
        llm.classify_batch.return_value = [True]
        _apply_filters(db, self._rows(db), None, None, llm, "the description")
        llm.classify_batch.assert_called_once_with(["hello world"], "the description")

    def test_empty_text_defaults_to_empty_string(self, db):
        _insert(db, [("1", "tweet", None, None)])
        llm = MagicMock()
        llm.classify_batch.return_value = [True]
        _apply_filters(db, self._rows(db), None, None, llm, "desc")
        texts, _ = llm.classify_batch.call_args.args
        assert texts == [""]

    def test_date_and_llm_combined(self, db):
        _insert(db, [
            ("1", "tweet", DATE_2023, "crypto"),
            ("2", "tweet", DATE_2024, "crypto"),  # too new
        ])
        llm = MagicMock()
        llm.classify_batch.return_value = [True]
        rows = _apply_filters(db, self._rows(db), BEFORE_2024, None, llm, "crypto")
        assert len(rows) == 1
        assert rows[0]["id"] == "1"

    def test_empty_batch_with_llm_not_called(self, db):
        llm = MagicMock()
        rows = _apply_filters(db, [], None, None, llm, "desc")
        assert rows == []
        llm.classify_batch.assert_not_called()


# ---------------------------------------------------------------------------
# _process_one
# ---------------------------------------------------------------------------

class TestProcessOne:
    async def test_like_calls_unlike_tweet(self, cfg):
        page = MagicMock()
        with patch("twitter_cleaner.worker.runner.actions.unlike_tweet", new_callable=AsyncMock) as mock:
            mock.return_value = "done"
            result = await _process_one(page, "123", "like", cfg)
        assert result == "done"
        args, kwargs = mock.call_args
        assert args[0] is page
        assert args[1] == "123"
        assert kwargs["dry_run"] is False

    async def test_retweet_calls_undo_retweet(self, cfg):
        page = MagicMock()
        with patch("twitter_cleaner.worker.runner.actions.undo_retweet", new_callable=AsyncMock) as mock:
            mock.return_value = "done"
            result = await _process_one(page, "123", "retweet", cfg)
        assert result == "done"
        args, kwargs = mock.call_args
        assert args[0] is page
        assert args[1] == "123"
        assert args[2] == "testuser"
        assert kwargs["dry_run"] is False

    async def test_tweet_calls_delete_tweet(self, cfg):
        page = MagicMock()
        with patch("twitter_cleaner.worker.runner.actions.delete_tweet", new_callable=AsyncMock) as mock:
            mock.return_value = "done"
            result = await _process_one(page, "123", "tweet", cfg)
        assert result == "done"
        args, kwargs = mock.call_args
        assert args[0] is page
        assert args[1] == "123"
        assert args[2] == "testuser"
        assert kwargs["dry_run"] is False

    async def test_reply_calls_delete_tweet(self, cfg):
        with patch("twitter_cleaner.worker.runner.actions.delete_tweet", new_callable=AsyncMock) as mock:
            mock.return_value = "skipped"
            result = await _process_one(MagicMock(), "55", "reply", cfg)
        assert result == "skipped"

    async def test_quote_calls_delete_tweet(self, cfg):
        with patch("twitter_cleaner.worker.runner.actions.delete_tweet", new_callable=AsyncMock) as mock:
            mock.return_value = "failed"
            result = await _process_one(MagicMock(), "66", "quote", cfg)
        assert result == "failed"

    async def test_dry_run_forwarded(self, dry_cfg):
        with patch("twitter_cleaner.worker.runner.actions.delete_tweet", new_callable=AsyncMock) as mock:
            mock.return_value = "done"
            await _process_one(MagicMock(), "1", "tweet", dry_cfg)
        _, kwargs = mock.call_args
        assert kwargs["dry_run"] is True
