from __future__ import annotations

import json
from functools import partial
from pathlib import Path

import pytest
from click.testing import CliRunner

from twitter_cleaner.cli import (
    _build_llm_filter,
    _parse_date,
    _parse_date_range,
    main,
)
from twitter_cleaner.config import Config
import click


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def runner():
    return CliRunner()


def _js(varname: str, data: list) -> str:
    return f"window.YTD.{varname}.part0 = {json.dumps(data)}"


@pytest.fixture
def patched_config(monkeypatch, tmp_path):
    """Make Config() always use tmp_path as state_dir and 'testuser' as username."""
    monkeypatch.setenv("TWITTER_USERNAME", "testuser")
    monkeypatch.setattr(
        "twitter_cleaner.cli.Config",
        partial(Config, state_dir=tmp_path, username="testuser"),
    )
    return tmp_path


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------

class TestParseDate:
    def test_valid_date(self):
        dt = _parse_date("2023-06-15", "--before")
        assert dt.year == 2023
        assert dt.month == 6
        assert dt.day == 15

    def test_none_returns_none(self):
        assert _parse_date(None, "--before") is None

    def test_invalid_format_raises(self):
        with pytest.raises(click.ClickException, match="Invalid date"):
            _parse_date("15/06/2023", "--before")

    def test_invalid_value_raises(self):
        with pytest.raises(click.ClickException, match="Invalid date"):
            _parse_date("not-a-date", "--before")


# ---------------------------------------------------------------------------
# _parse_date_range
# ---------------------------------------------------------------------------

class TestParseDateRange:
    def test_valid_range(self):
        before, after = _parse_date_range("2024-01-01", "2022-01-01")
        assert before.year == 2024
        assert after.year == 2022

    def test_both_none(self):
        before, after = _parse_date_range(None, None)
        assert before is None
        assert after is None

    def test_only_before(self):
        before, after = _parse_date_range("2024-01-01", None)
        assert before is not None
        assert after is None

    def test_after_equal_to_before_raises(self):
        with pytest.raises(click.ClickException, match="earlier"):
            _parse_date_range("2023-01-01", "2023-01-01")

    def test_after_newer_than_before_raises(self):
        with pytest.raises(click.ClickException, match="earlier"):
            _parse_date_range("2022-01-01", "2024-01-01")


# ---------------------------------------------------------------------------
# _build_llm_filter
# ---------------------------------------------------------------------------

class TestBuildLlmFilter:
    def test_no_description_returns_none(self):
        assert _build_llm_filter(None, None, None, None) is None
        assert _build_llm_filter("openai", "key", None, None) is None

    def test_description_without_provider_raises(self):
        with pytest.raises(click.ClickException, match="--llm-provider"):
            _build_llm_filter(None, "key", "angry tweets", None)

    def test_description_without_api_key_raises(self):
        with pytest.raises(click.ClickException, match="--llm-api-key"):
            _build_llm_filter("openai", None, "angry tweets", None)

    def test_valid_builds_filter(self):
        from twitter_cleaner.filters.llm_filter import OpenAIFilter
        f = _build_llm_filter("openai", "fake-key", "angry tweets", None)
        assert isinstance(f, OpenAIFilter)


# ---------------------------------------------------------------------------
# status command
# ---------------------------------------------------------------------------

class TestStatusCommand:
    def test_no_database(self, runner, patched_config, tmp_path):
        result = runner.invoke(main, ["status"])
        assert result.exit_code == 0
        assert "No progress database" in result.output

    def test_empty_database(self, runner, patched_config, tmp_path):
        from twitter_cleaner.store.progress_db import ProgressDB
        db_path = tmp_path / "progress.db"
        db = ProgressDB(db_path)
        db.close()
        result = runner.invoke(main, ["status"])
        assert result.exit_code == 0
        assert "No records" in result.output

    def test_with_data(self, runner, patched_config, tmp_path):
        from twitter_cleaner.store.progress_db import ProgressDB
        db_path = tmp_path / "progress.db"
        db = ProgressDB(db_path)
        db.bulk_insert_pending([("1", "tweet", "http://x.com/u/status/1", None, "hi")])
        db.close()
        result = runner.invoke(main, ["status"])
        assert result.exit_code == 0
        assert "tweet" in result.output


# ---------------------------------------------------------------------------
# reset command
# ---------------------------------------------------------------------------

class TestResetCommand:
    def test_no_database(self, runner, patched_config):
        result = runner.invoke(main, ["reset"])
        assert result.exit_code == 0
        assert "No progress database" in result.output

    def test_reset_failed_items(self, runner, patched_config, tmp_path):
        from twitter_cleaner.store.progress_db import ProgressDB
        db_path = tmp_path / "progress.db"
        db = ProgressDB(db_path)
        db.bulk_insert_pending([("1", "tweet", None, None, None)])
        db.mark_failed("1", "tweet", "err")
        db.close()

        result = runner.invoke(main, ["reset"])
        assert result.exit_code == 0
        assert "1" in result.output

    def test_reset_specific_type(self, runner, patched_config, tmp_path):
        from twitter_cleaner.store.progress_db import ProgressDB
        db_path = tmp_path / "progress.db"
        db = ProgressDB(db_path)
        db.bulk_insert_pending([("1", "tweet", None, None, None)])
        db.mark_failed("1", "tweet", "err")
        db.close()

        result = runner.invoke(main, ["reset", "--type", "tweets"])
        assert result.exit_code == 0

    def test_reset_skipped_status(self, runner, patched_config, tmp_path):
        from twitter_cleaner.store.progress_db import ProgressDB
        db_path = tmp_path / "progress.db"
        db = ProgressDB(db_path)
        db.bulk_insert_pending([("1", "tweet", None, None, None)])
        db.mark_skipped("1", "tweet")
        db.close()

        result = runner.invoke(main, ["reset", "--status", "skipped"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# parse command
# ---------------------------------------------------------------------------

class TestParseCommand:
    def _make_archive(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        tweets = [{"tweet": {"id": "1", "full_text": "hi", "created_at": "Mon Jan 01 00:00:00 +0000 2022", "entities": {"urls": []}}}]
        (data_dir / "tweets.js").write_text(_js("tweets", tweets), encoding="utf-8")
        return data_dir

    def test_no_archive_files(self, runner, patched_config, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        result = runner.invoke(main, ["parse", "--archive-dir", str(empty_dir)])
        assert result.exit_code != 0
        assert "No archive files" in result.output

    def test_valid_archive_inserts_records(self, runner, patched_config, tmp_path):
        data_dir = self._make_archive(tmp_path)
        result = runner.invoke(main, ["parse", "--archive-dir", str(data_dir)])
        assert result.exit_code == 0
        assert "tweet" in result.output.lower() or "Parsed" in result.output

    def test_valid_archive_with_likes(self, runner, patched_config, tmp_path):
        data_dir = tmp_path / "data2"
        data_dir.mkdir()
        likes = [{"like": {"tweetId": "99", "fullText": "liked"}}]
        (data_dir / "like.js").write_text(_js("like", likes), encoding="utf-8")
        result = runner.invoke(main, ["parse", "--archive-dir", str(data_dir)])
        assert result.exit_code == 0
